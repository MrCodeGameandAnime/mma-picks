from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..db import connect, transaction, utc_now
from ..providers.odds import OddsEvent, OddsProvider


class OddsImportError(ValueError):
    """Raised when normalized provider data cannot be persisted safely."""


@dataclass(frozen=True)
class ImportedEvent:
    event_id: int
    fight_id: int
    odds_snapshot_ids: tuple[int, ...]


def _event_name(provider_event: OddsEvent) -> str:
    return f"{provider_event.home_team} vs {provider_event.away_team}"


def _persist_event(
    connection,
    provider_event: OddsEvent,
    *,
    provider_name: str,
) -> ImportedEvent:
    if provider_event.home_team == provider_event.away_team:
        raise OddsImportError("provider event must contain two distinct fighters")

    existing_event = connection.execute(
        """
        SELECT id, status
        FROM events
        WHERE external_provider = ? AND external_id = ?
        """,
        (provider_name, provider_event.provider_event_id),
    ).fetchone()
    if existing_event is not None and existing_event["status"] == "completed":
        raise OddsImportError("completed provider events cannot be re-imported")

    if existing_event is None:
        event_cursor = connection.execute(
            """
            INSERT INTO events(
                promotion, name, event_date, external_provider, external_id, status
            ) VALUES (?, ?, ?, ?, ?, 'draft')
            """,
            (
                provider_event.sport_title,
                _event_name(provider_event),
                provider_event.commence_time[:10],
                provider_name,
                provider_event.provider_event_id,
            ),
        )
        event_id = int(event_cursor.lastrowid)
    else:
        event_id = int(existing_event["id"])
        connection.execute(
            """
            UPDATE events
            SET promotion = ?, name = ?, event_date = ?
            WHERE id = ?
            """,
            (
                provider_event.sport_title,
                _event_name(provider_event),
                provider_event.commence_time[:10],
                event_id,
            ),
        )

    fight = connection.execute(
        """
        SELECT id, status
        FROM fights
        WHERE event_id = ? AND external_provider = ? AND external_id = ?
        """,
        (event_id, provider_name, provider_event.provider_event_id),
    ).fetchone()
    if fight is None:
        fight_cursor = connection.execute(
            """
            INSERT INTO fights(
                event_id, fighter_a, fighter_b, bout_order, scheduled_at,
                status, external_provider, external_id
            ) VALUES (?, ?, ?, 1, ?, 'scheduled', ?, ?)
            """,
            (
                event_id,
                provider_event.home_team,
                provider_event.away_team,
                provider_event.commence_time,
                provider_name,
                provider_event.provider_event_id,
            ),
        )
        fight_id = int(fight_cursor.lastrowid)
    else:
        fight_id = int(fight["id"])
        if fight["status"] == "scheduled":
            connection.execute(
                """
                UPDATE fights
                SET fighter_a = ?, fighter_b = ?, scheduled_at = ?
                WHERE id = ?
                """,
                (
                    provider_event.home_team,
                    provider_event.away_team,
                    provider_event.commence_time,
                    fight_id,
                ),
            )

    snapshot_ids: list[int] = []
    fighters = {provider_event.home_team, provider_event.away_team}
    for bookmaker in provider_event.bookmakers:
        captured_at = bookmaker.last_update or utc_now()
        for outcome in bookmaker.outcomes:
            if outcome.fighter not in fighters:
                continue
            existing_snapshot = connection.execute(
                """
                SELECT id
                FROM odds_snapshots
                WHERE fight_id = ?
                  AND fighter = ?
                  AND sportsbook = ?
                  AND moneyline = ?
                  AND captured_at = ?
                  AND external_provider = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    fight_id,
                    outcome.fighter,
                    bookmaker.title,
                    outcome.moneyline,
                    captured_at,
                    provider_name,
                ),
            ).fetchone()
            if existing_snapshot is not None:
                snapshot_ids.append(int(existing_snapshot["id"]))
                continue
            snapshot_cursor = connection.execute(
                """
                INSERT INTO odds_snapshots(
                    fight_id, fighter, sportsbook, moneyline,
                    captured_at, external_provider
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fight_id,
                    outcome.fighter,
                    bookmaker.title,
                    outcome.moneyline,
                    captured_at,
                    provider_name,
                ),
            )
            snapshot_ids.append(int(snapshot_cursor.lastrowid))
    return ImportedEvent(event_id, fight_id, tuple(snapshot_ids))


def import_provider_event(
    database_path: str | Path,
    provider_event: OddsEvent,
    *,
    provider_name: str = "the_odds_api",
) -> ImportedEvent:
    with connect(database_path) as connection:
        with transaction(connection):
            return _persist_event(
                connection, provider_event, provider_name=provider_name
            )


def import_upcoming_events(
    database_path: str | Path,
    provider: OddsProvider,
    *,
    provider_name: str = "the_odds_api",
) -> list[ImportedEvent]:
    provider_events = provider.upcoming_events()
    with connect(database_path) as connection:
        with transaction(connection):
            return [
                _persist_event(
                    connection, provider_event, provider_name=provider_name
                )
                for provider_event in provider_events
            ]


def place_wager_from_snapshot(
    database_path: str | Path,
    *,
    prediction_id: int,
    odds_snapshot_id: int,
    stake_cents: int,
) -> int:
    with connect(database_path) as connection:
        with transaction(connection):
            row = connection.execute(
                """
                SELECT
                    p.fight_id, p.picked_fighter,
                    os.fight_id AS snapshot_fight_id,
                    os.fighter, os.sportsbook, os.moneyline
                FROM predictions p
                JOIN odds_snapshots os ON os.id = ?
                WHERE p.id = ?
                """,
                (odds_snapshot_id, prediction_id),
            ).fetchone()
            if row is None or row["fight_id"] != row["snapshot_fight_id"]:
                raise OddsImportError("odds snapshot does not belong to the prediction fight")
            if row["fighter"] != row["picked_fighter"]:
                raise OddsImportError("odds snapshot does not price the picked fighter")
            if stake_cents <= 0:
                raise OddsImportError("stake must be greater than zero")
            cursor = connection.execute(
                """
                INSERT INTO wagers(
                    prediction_id, odds_snapshot_id, stake_cents,
                    moneyline, sportsbook, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    prediction_id,
                    odds_snapshot_id,
                    stake_cents,
                    row["moneyline"],
                    row["sportsbook"],
                ),
            )
            return int(cursor.lastrowid)
