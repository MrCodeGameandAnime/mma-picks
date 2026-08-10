from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "tracker.db"
DEFAULT_MIGRATIONS_DIR = ROOT_DIR / "tools" / "migrations"
_MIGRATION_PATTERN = re.compile(r"^(?P<version>\d+)_.*\.sql$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    connection.execute("BEGIN")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def _migration_files(migrations_dir: Path) -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    for path in migrations_dir.glob("*.sql"):
        match = _MIGRATION_PATTERN.match(path.name)
        if match:
            migrations.append((int(match.group("version")), path))
    return sorted(migrations)


def initialize_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    migrations_dir = Path(migrations_dir)

    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

        applied = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }

        for version, migration_path in _migration_files(migrations_dir):
            if version in applied:
                continue
            with transaction(connection):
                connection.executescript(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
