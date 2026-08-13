import shutil
from pathlib import Path

from src.app.db import connect, initialize_database


def test_ufc_catalog_migration_applies_to_existing_gate7_database(tmp_path):
    database_path = tmp_path / "tracker.db"
    old_migrations = tmp_path / "old_migrations"
    old_migrations.mkdir()
    source_migrations = Path(__file__).resolve().parents[1] / "tools" / "migrations"
    for filename in ("001_initial.sql", "002_prediction_source_identifier.sql"):
        shutil.copyfile(source_migrations / filename, old_migrations / filename)

    initialize_database(database_path, old_migrations)
    with connect(database_path) as connection:
        assert [row["version"] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2]

    initialize_database(database_path)

    with connect(database_path) as connection:
        assert [row["version"] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2, 3]
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'fighters'"
        ).fetchone() is not None
        assert {
            row["name"] for row in connection.execute("PRAGMA table_info(events)")
        }.issuperset({"location", "source_url"})
