import shutil
from pathlib import Path

from src.app.db import connect
from src.app.services.settlement import settle_event
from src.app.services.events import ValidationError
from src.app.services.ufc_catalog_import import sync_catalog
from src.app.providers.ufcstats_csv import load_source

from test_ufc_catalog_web import FIXTURE_DIR, _catalog_client


def test_catalog_is_read_only_through_tracker_and_public_api(tmp_path, monkeypatch):
    client, database_path, ids = _catalog_client(tmp_path)
    with connect(database_path) as connection:
        before = dict(connection.execute("SELECT * FROM fights WHERE id = ?", (ids["fight_one"],)).fetchone())

    with connect(database_path) as connection:
        event_id = connection.execute("SELECT event_id FROM fights WHERE id = ?", (ids["fight_one"],)).fetchone()["event_id"]
    assert client.get(f"/events/{event_id}").status_code == 302
    assert client.get(f"/events/{event_id}/edit").status_code == 302
    assert client.post(f"/events/{event_id}/settle", data={f"winner_{ids['fight_one']}": "Alpha One"}).status_code == 302
    monkeypatch.setattr("src.app.web._odds_provider", lambda: (_ for _ in ()).throw(AssertionError("provider called")))
    assert client.get(f"/events/{event_id}/provider-bouts").status_code == 302
    assert client.post(f"/events/{event_id}/odds/refresh").status_code == 302
    with connect(database_path) as connection:
        after = dict(connection.execute("SELECT * FROM fights WHERE id = ?", (ids["fight_one"],)).fetchone())
    assert after == before
    assert client.get("/api/v1/events").get_json()["meta"]["total"] == 0
    assert client.get(f"/api/v1/events/{event_id}").status_code == 404
    with connect(database_path) as connection:
        event = connection.execute("SELECT external_provider FROM events WHERE id = ?", (event_id,)).fetchone()
    try:
        settle_event(database_path, event_id, {ids["fight_one"]: "Alpha One"})
    except ValidationError:
        pass
    else:
        raise AssertionError("catalog settlement unexpectedly succeeded")
    assert event["external_provider"] == "ufcstats"


def test_catalog_link_is_inside_main_navigation(tmp_path):
    client, _, _ = _catalog_client(tmp_path)
    html = client.get("/cards").get_data(as_text=True)
    nav = html[html.index("<nav"):html.index("</nav>")]
    assert 'href="/cards"' in nav
    assert html.rfind("</html>") > html.rfind('href="/cards"')


def test_directory_sync_isolates_malformed_event_and_committed_counters(tmp_path):
    source_dir = tmp_path / "source"
    shutil.copytree(FIXTURE_DIR, source_dir)
    results = source_dir / "ufc_fight_results.csv"
    text = results.read_text(encoding="utf-8")
    text = text.replace("http://ufcstats.com/fight-details/aaaaaaaa11111111", "not-a-ufcstats-url", 1)
    results.write_text(text, encoding="utf-8")

    summary = sync_catalog(tmp_path / "tracker.db", source_dir)
    assert summary.events_processed == 2
    assert summary.events_failed == 1
    assert summary.events_inserted == 1
    assert any("UFC Fixture One" in error for error in summary.errors)
    with connect(tmp_path / "tracker.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM events WHERE name = 'UFC Fixture One'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events WHERE name = 'UFC Fixture Two'").fetchone()[0] == 1


def test_mobile_tale_of_tape_keeps_three_semantic_columns():
    css = Path("root/src/app/static/style.css").read_text(encoding="utf-8")
    assert "grid-template-columns: 105px minmax(0, 1fr) minmax(0, 1fr)" in css
    assert ".tape-grid > div:first-child { display: block; }" in css
