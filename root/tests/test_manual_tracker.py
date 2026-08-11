from src.app.config import AppConfig
from src.app.db import connect
from src.app.metrics import dashboard_metrics
from src.server import create_app


def make_app(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    app.config.update(TESTING=True)
    return app


def fight_fields(index, fighter_a, fighter_b, *, confidence="60", pick=None):
    return {
        f"fighter_a_{index}": fighter_a,
        f"fighter_b_{index}": fighter_b,
        f"picked_fighter_{index}": pick or fighter_a,
        f"confidence_{index}": confidence,
        f"predicted_method_{index}": "decision",
        f"gender_{index}": "male",
        f"weight_class_{index}": "WW",
        f"card_section_{index}": "main_card",
        f"moneyline_{index}": "-140",
        f"sportsbook_{index}": "TestBook",
        f"stake_{index}": "0.50",
    }


def create_card(client, form):
    response = client.post("/events/new", data=form)
    assert response.status_code == 302
    return int(response.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_whole_card_entry_allows_drafts_and_saves_atomically(tmp_path):
    app = make_app(tmp_path)
    form = {"promotion": "UFC", "name": "UFC Test Card", "event_date": "2026-08-15", "fight_count": "15"}
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    form.update({"fighter_a_2": "Fighter C", "fighter_b_2": "Fighter D"})

    event_id = create_card(app.test_client(), form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM wagers").fetchone()[0] == 1


def test_manual_tracker_pages_render(tmp_path):
    client = make_app(tmp_path).test_client()

    assert client.get("/").status_code == 200
    assert client.get("/events").status_code == 200
    assert client.get("/events/new").status_code == 200


def test_incomplete_fight_rolls_back_the_card_save(tmp_path):
    app = make_app(tmp_path)
    form = {"promotion": "UFC", "name": "Broken Card", "event_date": "2026-08-15", "fight_count": "15"}
    form.update({"fighter_a_1": "Fighter A"})

    response = app.test_client().post("/events/new", data=form)

    assert response.status_code == 200
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_edit_and_settle_card_updates_bankroll_idempotently(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = {"promotion": "UFC", "name": "Settlement Card", "event_date": "2026-08-15", "fight_count": "15"}
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, form)

    edited = dict(form)
    edited["confidence_1"] = "70"
    response = client.post(f"/events/{event_id}/edit", data=edited)
    assert response.status_code == 302

    with connect(app.config["DATABASE_PATH"]) as connection:
        fight_id = connection.execute("SELECT id FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0]
        assert connection.execute("SELECT confidence FROM predictions").fetchone()[0] == 70

    settle_form = {f"winner_{fight_id}": "Fighter A"}
    response = client.post(f"/events/{event_id}/settle", data=settle_form)
    assert response.status_code == 302
    client.post(f"/events/{event_id}/settle", data=settle_form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        wager = connection.execute("SELECT status, profit_cents FROM wagers").fetchone()
        assert tuple(wager) == ("won", 36)
        assert connection.execute("SELECT COUNT(*) FROM wagers").fetchone()[0] == 1

    metrics = dashboard_metrics(app.config["DATABASE_PATH"])
    assert metrics["current_bankroll_cents"] == 786
    assert metrics["wins"] == 1
    assert metrics["losses"] == 0


def test_canceled_fight_is_void_and_excluded_from_bankroll(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = {"promotion": "UFC", "name": "Canceled Card", "event_date": "2026-08-15", "fight_count": "15"}
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        fight_id = connection.execute("SELECT id FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0]
    client.post(f"/events/{event_id}/settle", data={f"winner_{fight_id}": "canceled"})

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert tuple(connection.execute("SELECT status, profit_cents FROM wagers").fetchone()) == ("void", 0)
    metrics = dashboard_metrics(app.config["DATABASE_PATH"])
    assert metrics["current_bankroll_cents"] == 750
    assert metrics["total_wagered_cents"] == 0


def test_draw_fight_is_a_push_and_remains_in_wager_totals(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = {"promotion": "UFC", "name": "Draw Card", "event_date": "2026-08-15", "fight_count": "15"}
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        fight_id = connection.execute("SELECT id FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0]
    client.post(f"/events/{event_id}/settle", data={f"winner_{fight_id}": "draw"})

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert tuple(connection.execute("SELECT status, profit_cents FROM wagers").fetchone()) == ("push", 0)
    metrics = dashboard_metrics(app.config["DATABASE_PATH"])
    assert metrics["pushes"] == 1
    assert metrics["total_wagered_cents"] == 50
