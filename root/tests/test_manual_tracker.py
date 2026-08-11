from src.app.db import connect
from src.app.metrics import dashboard_metrics
from src.server import create_app
from src.app.config import AppConfig


def make_app(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    app.config.update(TESTING=True)
    return app


def fight_fields(index, fighter_a, fighter_b, *, confidence="60", pick="fighter_a"):
    return {
        f"fighter_a_{index}": fighter_a,
        f"fighter_b_{index}": fighter_b,
        f"analyst_{index}": "theweasle",
        f"picked_fighter_{index}": pick,
        f"confidence_{index}": confidence,
        f"predicted_method_{index}": "decision",
        f"gender_{index}": "male",
        f"weight_class_{index}": "WW",
        f"card_section_{index}": "main_card",
        f"moneyline_{index}": "-140",
        f"sportsbook_{index}": "TestBook",
        f"stake_{index}": "0.50",
    }


def fight_only_fields(index, fighter_a, fighter_b):
    return {
        f"fighter_a_{index}": fighter_a,
        f"fighter_b_{index}": fighter_b,
        f"analyst_{index}": "theweasle",
        f"picked_fighter_{index}": "",
        f"confidence_{index}": "",
        f"predicted_method_{index}": "",
        f"moneyline_{index}": "",
        f"sportsbook_{index}": "",
        f"stake_{index}": "",
    }


def card_form(name="Test Card"):
    return {
        "promotion": "UFC",
        "name": name,
        "event_date": "2026-08-15",
        "fight_count": "15",
    }


def create_card(client, form):
    response = client.post("/events/new", data=form)
    assert response.status_code == 302
    return int(response.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_whole_card_entry_allows_drafts_and_saves_atomically(tmp_path):
    app = make_app(tmp_path)
    form = card_form("UFC Test Card")
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    form.update(fight_only_fields(2, "Fighter C", "Fighter D"))

    event_id = create_card(app.test_client(), form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "draft"
        assert connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM wagers").fetchone()[0] == 1
        assert connection.execute("SELECT picked_fighter FROM predictions").fetchone()[0] == "Fighter A"


def test_real_form_uses_side_tokens_and_does_not_force_blank_stakes(tmp_path):
    client = make_app(tmp_path).test_client()

    response = client.get("/events/new")
    body = response.get_data(as_text=True)

    assert '<option value="fighter_a"' in body
    assert '<option value="fighter_b"' in body
    assert 'name="stake_1"' in body
    assert 'placeholder="0.50"' in body
    assert 'name="stake_1" value="0.50"' not in body


def test_fight_only_rows_are_saved_as_drafts_without_predictions_or_wagers(tmp_path):
    app = make_app(tmp_path)
    form = card_form("Fight Only")
    form.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(app.test_client(), form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "draft"
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM wagers").fetchone()[0] == 0


def test_prediction_without_wager_is_saved_as_a_draft(tmp_path):
    app = make_app(tmp_path)
    form = card_form("Prediction Only")
    form.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    form.update({"picked_fighter_1": "fighter_b", "confidence_1": "75"})
    event_id = create_card(app.test_client(), form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "draft"
        assert connection.execute("SELECT picked_fighter FROM predictions").fetchone()[0] == "Fighter B"
        assert connection.execute("SELECT COUNT(*) FROM wagers").fetchone()[0] == 0


def test_fully_populated_card_is_upcoming(tmp_path):
    app = make_app(tmp_path)
    form = card_form("Complete Card")
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(app.test_client(), form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "upcoming"


def test_wager_without_prediction_is_rejected(tmp_path):
    app = make_app(tmp_path)
    form = card_form("Invalid Wager")
    form.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    form.update({"moneyline_1": "-140", "sportsbook_1": "TestBook", "stake_1": "0.50"})

    response = app.test_client().post("/events/new", data=form)

    assert response.status_code == 200
    assert "complete prediction" in response.get_data(as_text=True)
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_editing_a_draft_can_make_it_upcoming(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = card_form("Draft Then Complete")
    form.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, form)

    completed_form = card_form("Draft Then Complete")
    completed_form.update(fight_fields(1, "Fighter A", "Fighter B"))
    response = client.post(f"/events/{event_id}/edit", data=completed_form)

    assert response.status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "upcoming"


def test_manual_tracker_pages_render(tmp_path):
    client = make_app(tmp_path).test_client()

    assert client.get("/").status_code == 200
    assert client.get("/events").status_code == 200
    assert client.get("/events/new").status_code == 200
    analytics = client.get("/analytics")
    assert analytics.status_code == 200
    assert "Analytics" in analytics.get_data(as_text=True)


def test_incomplete_fight_rolls_back_the_card_save(tmp_path):
    app = make_app(tmp_path)
    form = card_form("Broken Card")
    form.update({"fighter_a_1": "Fighter A"})

    response = app.test_client().post("/events/new", data=form)

    assert response.status_code == 200
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_edit_and_settle_card_is_identical_noop_then_corrects_atomically(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = card_form("Settlement Card")
    form.update(fight_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        fight_id = connection.execute("SELECT id FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0]

    settle_form = {f"winner_{fight_id}": "Fighter A"}
    assert client.post(f"/events/{event_id}/settle", data=settle_form).status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        before = {
            "event": tuple(connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()),
            "fight": tuple(connection.execute("SELECT status, winner FROM fights WHERE id = ?", (fight_id,)).fetchone()),
            "wager": tuple(connection.execute("SELECT status, profit_cents, settled_at FROM wagers").fetchone()),
        }

    assert client.post(f"/events/{event_id}/settle", data=settle_form).status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        after_noop = {
            "event": tuple(connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()),
            "fight": tuple(connection.execute("SELECT status, winner FROM fights WHERE id = ?", (fight_id,)).fetchone()),
            "wager": tuple(connection.execute("SELECT status, profit_cents, settled_at FROM wagers").fetchone()),
        }
    assert after_noop == before

    assert client.post(f"/events/{event_id}/settle", data={f"winner_{fight_id}": "Fighter B"}).status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert tuple(connection.execute("SELECT status, winner FROM fights WHERE id = ?", (fight_id,)).fetchone()) == ("completed", "Fighter B")
        assert tuple(connection.execute("SELECT status, profit_cents FROM wagers").fetchone()) == ("lost", -50)
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "completed"

    metrics = dashboard_metrics(app.config["DATABASE_PATH"])
    assert metrics["current_bankroll_cents"] == 700
    assert metrics["wins"] == 0
    assert metrics["losses"] == 1


def test_canceled_fight_is_void_and_excluded_from_bankroll(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = card_form("Canceled Card")
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
    form = card_form("Draw Card")
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


def test_completed_wagerless_event_cannot_be_edited(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    form = card_form("Wagerless Completed")
    form.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, form)

    with connect(app.config["DATABASE_PATH"]) as connection:
        fight_id = connection.execute("SELECT id FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0]
    client.post(f"/events/{event_id}/settle", data={f"winner_{fight_id}": "Fighter A"})

    edited = card_form("Should Not Save")
    edited.update(fight_only_fields(1, "Changed A", "Changed B"))
    response = client.post(f"/events/{event_id}/edit", data=edited)

    assert response.status_code == 200
    assert "completed cards cannot be edited" in response.get_data(as_text=True)
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "completed"
        assert tuple(connection.execute("SELECT fighter_a, fighter_b, status, winner FROM fights WHERE id = ?", (fight_id,)).fetchone()) == ("Fighter A", "Fighter B", "completed", "Fighter A")


def test_duplicate_bout_order_is_rejected_on_create_and_edit(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    duplicate = card_form("Duplicate Orders")
    duplicate.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    duplicate.update(fight_only_fields(2, "Fighter C", "Fighter D"))
    duplicate["bout_order_1"] = "4"
    duplicate["bout_order_2"] = "4"

    response = client.post("/events/new", data=duplicate)
    assert response.status_code == 200
    assert "bout order must be unique" in response.get_data(as_text=True)
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0

    valid = card_form("Editable Orders")
    valid.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    event_id = create_card(client, valid)
    duplicate_edit = card_form("Editable Orders")
    duplicate_edit.update(fight_only_fields(1, "Fighter A", "Fighter B"))
    duplicate_edit.update(fight_only_fields(2, "Fighter C", "Fighter D"))
    duplicate_edit["bout_order_1"] = "2"
    duplicate_edit["bout_order_2"] = "2"

    response = client.post(f"/events/{event_id}/edit", data=duplicate_edit)
    assert response.status_code == 200
    assert "bout order must be unique" in response.get_data(as_text=True)
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT bout_order FROM fights WHERE event_id = ?", (event_id,)).fetchone()[0] == 1
