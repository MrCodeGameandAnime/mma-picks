import sqlite3
import re

import pytest

from src.app.db import connect, initialize_database, transaction, utc_now


CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 3"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 2"
        ).fetchone()[0] == 1


def test_migrations_use_canonical_utc_timestamps(tmp_path):
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        settings_timestamp = connection.execute(
            "SELECT updated_at FROM settings LIMIT 1"
        ).fetchone()["updated_at"]
        connection.execute(
            "INSERT INTO events(promotion, name, event_date) VALUES ('UFC', 'Timestamp Card', '2026-01-01')"
        )
        event_timestamp = connection.execute(
            "SELECT created_at FROM events LIMIT 1"
        ).fetchone()["created_at"]

    assert CANONICAL_UTC.fullmatch(utc_now())
    assert CANONICAL_UTC.fullmatch(settings_timestamp)
    assert CANONICAL_UTC.fullmatch(event_timestamp)


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


def test_failed_migration_is_atomic_and_retryable(tmp_path):
    database_path = tmp_path / "tracker.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration_path = migrations_dir / "001_broken.sql"
    migration_path.write_text(
        """
        CREATE TABLE temporary_object (id INTEGER PRIMARY KEY);
        INSERT INTO temporary_object(id) VALUES (1);
        INSERT INTO table_that_does_not_exist(id) VALUES (1);
        """,
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.OperationalError):
        initialize_database(database_path, migrations_dir)

    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'temporary_object'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 1"
        ).fetchone() is None

    migration_path.write_text(
        "CREATE TABLE temporary_object (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )
    initialize_database(database_path, migrations_dir)

    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'temporary_object'"
        ).fetchone() is not None
        assert connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 1"
        ).fetchone()["version"] == 1


def test_duplicate_migration_versions_fail_before_execution(tmp_path):
    database_path = tmp_path / "tracker.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE first_object (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )
    (migrations_dir / "001_other.sql").write_text(
        "CREATE TABLE second_object (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate migration version 1"):
        initialize_database(database_path, migrations_dir)

    assert not database_path.exists()


def test_all_successful_migrations_are_recorded_in_one_run(tmp_path):
    database_path = tmp_path / "tracker.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE first_object (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )
    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE second_object (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )

    initialize_database(database_path, migrations_dir)

    with connect(database_path) as connection:
        versions = [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions == [1, 2]
