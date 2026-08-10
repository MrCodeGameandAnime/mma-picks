import sqlite3

import pytest

from src.app.db import connect, initialize_database, transaction


def test_database_initializes_and_seeds(tmp_path):
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"settings", "analysts", "events", "fights", "predictions", "odds_snapshots", "wagers"}.issubset(tables)
        assert connection.execute(
            "SELECT value FROM settings WHERE key = 'starting_bankroll_cents'"
        ).fetchone()["value"] == "750"
        assert connection.execute(
            "SELECT slug FROM analysts"
        ).fetchone()["slug"] == "theweasle"


def test_database_initialization_is_idempotent(tmp_path):
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)
    initialize_database(database_path)

    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_foreign_keys_are_enabled(tmp_path):
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO predictions(fight_id, analyst_id, picked_fighter, confidence) VALUES (1, 1, 'Fighter A', 60)"
            )


def test_transaction_rolls_back_on_failure(tmp_path):
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(connection):
                connection.execute(
                    "INSERT INTO events(promotion, name, event_date) VALUES ('UFC', 'Test Card', '2026-01-01')"
                )
                connection.execute(
                    "INSERT INTO events(promotion, name, event_date) VALUES (NULL, 'Broken Card', '2026-01-01')"
                )

        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
