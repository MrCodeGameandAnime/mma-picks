from dataclasses import replace
from pathlib import Path

from src.app.db import connect
from src.app.providers.ufcstats_csv import load_source
from src.app.services.ufc_catalog_import import sync_catalog


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ufcstats_minimal"


def test_ufcstats_parser_normalizes_fixture_values():
    source = load_source(FIXTURE_DIR)

    assert len(source.events) == 2
    assert len(source.fighters) == 4
    assert len(source.fights) == 3
    assert len(source.round_stats) == 6
    assert source.events[0].event_date == "2026-08-10"
    assert source.fighters[0].height_inches == 71
    assert source.fighters[0].reach_inches == 66
    assert source.fighters[0].weight_lbs == 155
    assert source.fighters[0].date_of_birth == "1990-01-02"
    assert source.round_stats[0].sig_strikes_landed == 3
    assert source.round_stats[0].sig_strikes_attempted == 10
    assert source.round_stats[0].control_seconds == 122
    assert source.round_stats[1].control_seconds is None


def test_ufcstats_import_is_idempotent_and_preserves_attached_tracker_rows(tmp_path):
    database_path = tmp_path / "tracker.db"
    source = load_source(FIXTURE_DIR)

    first = sync_catalog(database_path, source)
    assert not first.has_failures
    with connect(database_path) as connection:
        event_ids = {
            row["external_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, external_id FROM events WHERE external_provider = 'ufcstats'"
            )
        }
        fight_ids = {
            row["external_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, external_id FROM fights WHERE external_provider = 'ufcstats'"
            )
        }
        stats_count = connection.execute(
            "SELECT COUNT(*) FROM fight_round_stats"
        ).fetchone()[0]
        fight_id = fight_ids["aaaaaaaa11111111"]
        connection.execute(
            """
            INSERT INTO predictions(fight_id, analyst_id, picked_fighter, confidence)
            VALUES (?, 1, 'Alpha One', 80)
            """,
            (fight_id,),
        )
        prediction_id = connection.execute(
            "SELECT id FROM predictions WHERE fight_id = ?", (fight_id,)
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO wagers(
                prediction_id, stake_cents, moneyline, sportsbook
            ) VALUES (?, 50, -110, 'Fixture Book')
            """,
            (prediction_id,),
        )

    second = sync_catalog(database_path, source)
    assert not second.has_failures
    assert second.events_updated == 2
    assert second.fights_updated == 3
    with connect(database_path) as connection:
        assert {
            row["external_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, external_id FROM events WHERE external_provider = 'ufcstats'"
            )
        } == event_ids
        assert {
            row["external_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, external_id FROM fights WHERE external_provider = 'ufcstats'"
            )
        } == fight_ids
        assert connection.execute(
            "SELECT COUNT(*) FROM fight_round_stats"
        ).fetchone()[0] == stats_count
        assert connection.execute(
            "SELECT COUNT(*) FROM predictions WHERE fight_id = ?", (fight_ids["aaaaaaaa11111111"],)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM wagers WHERE prediction_id = ?", (prediction_id,)
        ).fetchone()[0] == 1

    changed_fighter = replace(source.fighters[0], nickname="Updated Alpha")
    changed_event = replace(source.events[0], location="Updated Location")
    changed_source = replace(
        source,
        fighters=(changed_fighter, *source.fighters[1:]),
        events=(changed_event, source.events[1]),
    )
    third = sync_catalog(database_path, changed_source)
    assert not third.has_failures
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT e.location, f.id, f.result_method, p.id AS prediction_id,
                   w.id AS wager_id
            FROM events e
            JOIN fights f ON f.event_id = e.id
            LEFT JOIN predictions p ON p.fight_id = f.id
            LEFT JOIN wagers w ON w.prediction_id = p.id
            WHERE e.external_id = '1111111111111111'
              AND f.external_id = 'aaaaaaaa11111111'
            """
        ).fetchone()
        assert row["location"] == "Updated Location"
        assert row["id"] == fight_ids["aaaaaaaa11111111"]
        assert row["prediction_id"] == prediction_id
        assert row["wager_id"] is not None


def test_ufcstats_event_failure_rolls_back_only_that_event(tmp_path):
    database_path = tmp_path / "tracker.db"
    source = load_source(FIXTURE_DIR)
    bad_fight = replace(source.fights[0], fighter_a="Unknown Fighter")
    bad_source = replace(source, fights=(bad_fight, *source.fights[1:]))

    summary = sync_catalog(database_path, bad_source)

    assert summary.events_failed == 1
    assert summary.unresolved_fighter_identities == {"Unknown Fighter"}
    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE external_id = '1111111111111111'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE external_id = '2222222222222222'"
        ).fetchone()[0] == 1


def test_unsupported_outcome_is_reported_and_event_is_rolled_back(tmp_path):
    database_path = tmp_path / "tracker.db"
    source = load_source(FIXTURE_DIR)
    bad_fight = replace(source.fights[2], outcome="X/X")
    bad_source = replace(source, fights=(*source.fights[:2], bad_fight))

    summary = sync_catalog(database_path, bad_source)

    assert summary.unsupported_outcomes == {"X/X"}
    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE external_id = '2222222222222222'"
        ).fetchone()[0] == 0
