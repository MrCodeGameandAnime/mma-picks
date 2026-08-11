from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from ..db import connect, transaction, utc_now
from ..providers.odds import OddsEvent, OddsProvider, QuotaInfo


class OddsImportError(ValueError):
    """Raised when provider data cannot be imported safely."""


@dataclass(frozen=True)
class ImportResult:
    event_id: int
    fight_ids: tuple[int, ...]
    odds_snapshot_ids: tuple[int, ...]
    quota: QuotaInfo | None = None

    @property
    def snapshot_count(self) -> int:
        return len(self.odds_snapshot_ids)


def _provider_quota(provider: OddsProvider) -> QuotaInfo | None:
    return getattr(provider, "last_quota", None)


def _selected_ids(event_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip()))


def _validate_provider_event(provider_event: OddsEvent) -> None:
    if provider_event.home_team == provider_event.away_team:
        raise OddsImportError("provider event must contain two distinct fighters")


def _next_bout_order(connection, event_id: int) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(bout_order), 0) + 1 AS next_order FROM fights WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    return int(row["next_order"])


def _persist_snapshots(
    connection,
    fight_id: int,
    provider_event: OddsEvent,
    *,
    provider_name: str,
) -> tuple[int, ...]:
    fighters = {provider_event.home_team, provider_event.away_team}
    snapshot_ids: list[int] = []
    for bookmaker in provider_event.bookmakers:
        captured_at = bookmaker.last_update or utc_now()
        for outcome in bookmaker.outcomes:
            if outcome.fighter not in fighters:
                continue
            existing = connection.execute(
                """
                SELECT id
                FROM odds_snapshots
                WHERE fight_id = ? AND fighter = ? AND sportsbook = ?
                  AND moneyline = ? AND captured_at = ? AND external_provider = ?
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
            if existing is not None:
                snapshot_ids.append(int(existing["id"]))
                continue
            cursor = connection.execute(
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
            snapshot_ids.append(int(cursor.lastrowid))
    return tuple(snapshot_ids)


def _persist_selected_event(
    connection,
    card_id: int,
    provider_event: OddsEvent,
    *,
    provider_name: str,
) -> tuple[int, tuple[int, ...]]:
    _validate_provider_event(provider_event)
    provider_id = provider_event.provider_event_id
    fight = connection.execute(
        """
        SELECT id, event_id, status
        FROM fights
        WHERE external_provider = ? AND external_id = ?
        """,
        (provider_name, provider_id),
    ).fetchone()
    if fight is not None and int(fight["event_id"]) != card_id:
        raise OddsImportError("provider bout is already attached to another card")

    if fight is None:
        cursor = connection.execute(
            """
            INSERT INTO fights(
                event_id, fighter_a, fighter_b, bout_order, scheduled_at,
                status, external_provider, external_id
            ) VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)
            """,
            (
                card_id,
                provider_event.home_team,
                provider_event.away_team,
                _next_bout_order(connection, card_id),
                provider_event.commence_time,
                provider_name,
                provider_id,
            ),
        )
        fight_id = int(cursor.lastrowid)
    else:
        fight_id = int(fight["id"])
        if fight["status"] in {"completed", "canceled", "no_contest", "draw"}:
            raise OddsImportError("completed or canceled bouts cannot be refreshed")
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
    return fight_id, _persist_snapshots(
        connection,
        fight_id,
        provider_event,
        provider_name=provider_name,
    )


def import_selected_bouts(
    database_path: str | Path,
    card_id: int,
    provider: OddsProvider,
    provider_event_ids: Sequence[str],
    *,
    provider_name: str = "the_odds_api",
) -> ImportResult:
    """Import only selected provider bouts into an existing user-created card."""
    selected = _selected_ids(provider_event_ids)
    if not selected:
        raise OddsImportError("select at least one provider bout")

    discovered = provider.discover_events(selected)
    discovered_by_id = {event.provider_event_id: event for event in discovered}
    missing = [event_id for event_id in selected if event_id not in discovered_by_id]
    if missing:
        raise OddsImportError(f"provider bouts were not found: {', '.join(missing)}")

    odds_by_id = {event.provider_event_id: event for event in provider.fetch_odds(selected)}
    selected_events = [
        replace(discovered_by_id[event_id], bookmakers=odds_by_id.get(event_id, discovered_by_id[event_id]).bookmakers)
        for event_id in selected
    ]

    with connect(database_path) as connection:
        with transaction(connection):
            card = connection.execute(
                "SELECT id, status FROM events WHERE id = ?",
                (card_id,),
            ).fetchone()
            if card is None:
                raise OddsImportError("card not found")
            if card["status"] in {"completed", "canceled"}:
                raise OddsImportError("completed or canceled cards cannot be imported into")
            fight_ids: list[int] = []
            snapshot_ids: list[int] = []
            for provider_event in selected_events:
                fight_id, imported_snapshot_ids = _persist_selected_event(
                    connection,
                    card_id,
                    provider_event,
                    provider_name=provider_name,
                )
                fight_ids.append(fight_id)
                snapshot_ids.extend(imported_snapshot_ids)
    return ImportResult(
        event_id=card_id,
        fight_ids=tuple(fight_ids),
        odds_snapshot_ids=tuple(snapshot_ids),
        quota=_provider_quota(provider),
    )


def refresh_odds_for_card(
    database_path: str | Path,
    card_id: int,
    provider: OddsProvider,
    *,
    provider_name: str = "the_odds_api",
) -> ImportResult:
    """Refresh snapshots for provider-linked fights without changing card metadata."""
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, external_id
            FROM fights
            WHERE event_id = ? AND external_provider = ? AND external_id IS NOT NULL
            ORDER BY bout_order, id
            """,
            (card_id, provider_name),
        ).fetchall()
    event_ids = tuple(row["external_id"] for row in rows)
    if not event_ids:
        return ImportResult(card_id, (), (), _provider_quota(provider))

    odds_by_id = {event.provider_event_id: event for event in provider.fetch_odds(event_ids)}
    fight_by_external_id = {row["external_id"]: int(row["id"]) for row in rows}
    with connect(database_path) as connection:
        with transaction(connection):
            snapshot_ids: list[int] = []
            for external_id, provider_event in odds_by_id.items():
                fight_id = fight_by_external_id.get(external_id)
                if fight_id is None:
                    continue
                snapshot_ids.extend(
                    _persist_snapshots(
                        connection,
                        fight_id,
                        provider_event,
                        provider_name=provider_name,
                    )
                )
    return ImportResult(
        card_id,
        tuple(fight_by_external_id.values()),
        tuple(snapshot_ids),
        _provider_quota(provider),
    )


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
