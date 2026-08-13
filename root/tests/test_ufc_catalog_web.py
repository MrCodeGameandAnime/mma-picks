from pathlib import Path

from src.app.config import AppConfig
from src.app.db import connect
from src.app.providers.ufcstats_csv import load_source
from src.app.services.ufc_catalog_import import sync_catalog
from src.server import create_app


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ufcstats_minimal"


def _catalog_client(tmp_path):
    database_path = tmp_path / "tracker.db"
    app = create_app(AppConfig(database_path=database_path))
    summary = sync_catalog(database_path, load_source(FIXTURE_DIR))
    assert not summary.has_failures
    with connect(database_path) as connection:
        ids = {
            "card_one": connection.execute(
                "SELECT id FROM events WHERE external_id = '1111111111111111'"
            ).fetchone()["id"],
            "card_two": connection.execute(
                "SELECT id FROM events WHERE external_id = '2222222222222222'"
            ).fetchone()["id"],
            "fight_one": connection.execute(
                "SELECT id FROM fights WHERE external_id = 'aaaaaaaa11111111'"
            ).fetchone()["id"],
            "fight_other_card": connection.execute(
                "SELECT id FROM fights WHERE external_id = 'cccccccc33333333'"
            ).fetchone()["id"],
            "fighter": connection.execute(
                "SELECT id FROM fighters WHERE canonical_name = 'Alpha One'"
            ).fetchone()["id"],
        }
    return app.test_client(), database_path, ids


def test_catalog_hierarchy_and_ownership_checks(tmp_path):
    client, database_path, ids = _catalog_client(tmp_path)

    cards = client.get("/cards")
    assert cards.status_code == 200
    body = cards.get_data(as_text=True)
    assert "UFC Fixture One" in body
    assert body.index("UFC Fixture One") < body.index("UFC Fixture Two")
    assert f"/cards/{ids['card_one']}" in body

    card = client.get(f"/cards/{ids['card_one']}")
    assert card.status_code == 200
    card_body = card.get_data(as_text=True)
    assert "Alpha One" in card_body
    assert f"/cards/{ids['card_one']}/fights/{ids['fight_one']}" in card_body

    fight = client.get(f"/cards/{ids['card_one']}/fights/{ids['fight_one']}")
    assert fight.status_code == 200
    fight_body = fight.get_data(as_text=True)
    assert "Decision - Unanimous" in fight_body
    assert "3 of 10" in fight_body
    assert f"/fighters/{ids['fighter']}" in fight_body

    fighter = client.get(f"/fighters/{ids['fighter']}")
    assert fighter.status_code == 200
    assert "Alpha One" in fighter.get_data(as_text=True)

    assert client.get(
        f"/cards/{ids['card_one']}/fights/{ids['fight_other_card']}"
    ).status_code == 404
    assert client.get("/cards/999999").status_code == 404
    assert client.get("/fighters/999999").status_code == 404

    with connect(database_path) as connection:
        connection.execute(
            "INSERT INTO events(promotion, name, event_date) VALUES ('UFC', 'Manual Event', '2026-01-01')"
        )
        manual_id = connection.execute(
            "SELECT id FROM events WHERE name = 'Manual Event'"
        ).fetchone()["id"]
    assert client.get(f"/cards/{manual_id}").status_code == 404


def test_catalog_pagination_and_tracker_list_isolation(tmp_path):
    client, database_path, _ = _catalog_client(tmp_path)
    with connect(database_path) as connection:
        for index in range(51):
            connection.execute(
                """
                INSERT INTO events(
                    promotion, name, event_date, external_provider, external_id, status
                ) VALUES ('UFC', ?, '2020-01-01', 'ufcstats', ?, 'completed')
                """,
                (f"Pagination Card {index}", f"page-{index}"),
            )

    page_two = client.get("/cards?page=2")
    assert page_two.status_code == 200
    assert "Pagination Card 0" in page_two.get_data(as_text=True)
    assert client.get("/cards?page=0").status_code == 404
    assert client.get("/cards?page=99").status_code == 404
    assert "UFC Fixture One" not in client.get("/events").get_data(as_text=True)
