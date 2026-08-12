from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from ..db import connect, transaction, utc_now
from ..providers.picks import NormalizedPick, PicksProvider
from .events import ValidationError


class PicksImportError(ValidationError):
    """Raised when an automated picks import cannot be applied safely."""


def _match_fight(connection, event_id: int, pick: NormalizedPick):
    if pick.external_provider and pick.external_fight_id:
        fight = connection.execute(
            """
            SELECT * FROM fights
            WHERE event_id = ? AND external_provider = ? AND external_id = ?
            """,
            (event_id, pick.external_provider, pick.external_fight_id),
        ).fetchone()
        if fight is not None:
            return fight

    return connection.execute(
        """
        SELECT * FROM fights
        WHERE event_id = ?
          AND ((fighter_a = ? AND fighter_b = ?) OR (fighter_a = ? AND fighter_b = ?))
        """,
        (event_id, pick.fighter_a, pick.fighter_b, pick.fighter_b, pick.fighter_a),
    ).fetchone()


def _canonical_published_at(value: str) -> str:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PicksImportError(
            "source publication timestamp must be ISO-8601 with a timezone"
        ) from exc
    if parsed.tzinfo is None:
        raise PicksImportError(
            "source publication timestamp must be ISO-8601 with a timezone"
        )
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_pick(pick: NormalizedPick) -> None:
    if not pick.fighter_a.strip() or not pick.fighter_b.strip():
        raise PicksImportError("source pick must contain both fighters")
    if pick.picked_fighter not in {pick.fighter_a, pick.fighter_b}:
        raise PicksImportError("source pick must select one of its fighters")
    if not 0 <= pick.confidence <= 100:
        raise PicksImportError("source confidence must be between 0 and 100")
    if not pick.source_identifier.strip():
        raise PicksImportError("source pick is missing its source identifier")
    if not pick.source_url.strip():
        raise PicksImportError("source pick is missing its source URL")
    if not pick.published_at.strip():
        raise PicksImportError("source pick is missing its publication timestamp")


def ingest_picks(
    database_path: str | Path,
    event_id: int,
    analyst_slug: str,
    picks: Iterable[NormalizedPick],
    *,
    provider_name: str,
) -> list[int]:
    """Persist a complete provider result atomically without replacing manual picks."""
    normalized = list(picks)
    if not normalized:
        raise PicksImportError(f"{provider_name} provider returned no picks")
    for pick in normalized:
        _validate_pick(pick)

    with connect(database_path) as connection:
        with transaction(connection):
            event = connection.execute(
                "SELECT id, status FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if event is None:
                raise PicksImportError("event not found")
            if event["status"] in {"completed", "canceled"}:
                raise PicksImportError("completed or canceled cards cannot import picks")
            analyst = connection.execute(
                "SELECT id FROM analysts WHERE slug = ? AND active = 1",
                (analyst_slug,),
            ).fetchone()
            if analyst is None:
                raise PicksImportError("analyst not found")

            matched_fights: list[tuple[NormalizedPick, object]] = []
            seen_fight_ids: set[int] = set()
            for pick in normalized:
                fight = _match_fight(connection, event_id, pick)
                if fight is None:
                    raise PicksImportError(
                        f"source pick does not match a fight on event {event_id}: "
                        f"{pick.fighter_a} vs {pick.fighter_b}"
                    )
                if int(fight["id"]) in seen_fight_ids:
                    raise PicksImportError("provider returned duplicate picks for one fight")
                seen_fight_ids.add(int(fight["id"]))
                matched_fights.append((pick, fight))

            prediction_ids: list[int] = []
            captured_at = utc_now()
            for pick, fight in matched_fights:
                published_at = _canonical_published_at(pick.published_at)
                existing = connection.execute(
                    """
                    SELECT id, source_identifier, source_url
                    FROM predictions
                    WHERE fight_id = ? AND analyst_id = ?
                    """,
                    (fight["id"], analyst["id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["source_identifier"] == pick.source_identifier
                        and existing["source_url"] == pick.source_url
                    ):
                        prediction_ids.append(int(existing["id"]))
                        continue
                    raise PicksImportError(
                        f"prediction already exists for fight {fight['id']}; "
                        "manual or prior source data was not replaced"
                    )

                cursor = connection.execute(
                    """
                    INSERT INTO predictions(
                        fight_id, analyst_id, picked_fighter, confidence,
                        predicted_method, source_url, source_published_at,
                        captured_at, source_identifier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fight["id"],
                        analyst["id"],
                        pick.picked_fighter,
                        pick.confidence,
                        pick.predicted_method,
                        pick.source_url,
                        published_at,
                        captured_at,
                        pick.source_identifier,
                    ),
                )
                prediction_ids.append(int(cursor.lastrowid))

            return prediction_ids


def ingest_from_provider(
    database_path: str | Path,
    event_id: int,
    analyst_slug: str,
    provider: PicksProvider,
    *,
    event_name: str | None = None,
    event_date: str | None = None,
) -> list[int]:
    picks = provider.fetch_picks(
        analyst_slug,
        event_name=event_name,
        event_date=event_date,
    )
    return ingest_picks(
        database_path,
        event_id,
        analyst_slug,
        picks,
        provider_name=provider.name,
    )
