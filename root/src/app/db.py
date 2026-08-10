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
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    migrations: dict[int, Path] = {}
    for path in migrations_dir.glob("*.sql"):
        match = _MIGRATION_PATTERN.match(path.name)
        if match:
            version = int(match.group("version"))
            if version in migrations:
                previous = migrations[version].name
                raise ValueError(
                    f"duplicate migration version {version}: {previous} and {path.name}"
                )
            migrations[version] = path
    return sorted(migrations.items())


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    statement_lines: list[str] = []
    for line in script.splitlines(keepends=True):
        statement_lines.append(line)
        statement = "".join(statement_lines)
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement_lines.clear()

    remainder = "".join(statement_lines).strip()
    if remainder:
        raise ValueError("migration contains an incomplete SQL statement")


def initialize_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    migrations_dir = Path(migrations_dir)
    migration_files = _migration_files(migrations_dir)
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

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

        for version, migration_path in migration_files:
            if version in applied:
                continue
            with transaction(connection):
                _execute_script(
                    connection,
                    migration_path.read_text(encoding="utf-8"),
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
            applied.add(version)
