from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping

from ..db import connect, transaction, utc_now


class ValidationError(ValueError):
    """Raised when a card submission is incomplete or invalid."""


@dataclass(frozen=True)
class FightInput:
    fighter_a: str
    fighter_b: str
    weight_class: str | None
    gender: str | None
    card_section: str | None
    bout_order: int
    analyst_id: int | None
    picked_fighter: str | None
    confidence: int | None
    predicted_method: str | None
    sportsbook: str | None
    moneyline: int | None
    stake_cents: int | None
    odds_snapshot_id: int | None = None
    fight_id: int | None = None


def _text(value: str | None) -> str:
    return (value or "").strip()


def _optional_text(value: str | None) -> str | None:
    value = _text(value)
    return value or None


def _parse_int(value: str | None, field_name: str) -> int:
    try:
        return int(_text(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a whole number") from exc


def _optional_int(value: str | None, field_name: str) -> int | None:
    value = _text(value)
    if not value:
        return None
    return _parse_int(value, field_name)


def _parse_stake_cents(value: str | None) -> int:
    try:
        amount = Decimal(_text(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("stake must be a dollar amount") from exc
    cents = int(amount * 100)
    if cents <= 0:
        raise ValidationError("stake must be greater than $0.00")
    return cents


def parse_fights(
    form: Mapping[str, str],
    database_path: str | Path,
    *,
    allow_empty: bool = False,
) -> list[FightInput]:
    with connect(database_path) as connection:
        analyst_ids = {
            row["slug"]: row["id"]
            for row in connection.execute("SELECT id, slug FROM analysts WHERE active = 1")
        }
        settings = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM settings")
        }

    try:
        row_count = int(form.get("fight_count", "15"))
    except ValueError as exc:
        raise ValidationError("invalid fight form") from exc

    max_card_fights = int(settings["max_card_fights"])
    if row_count > max_card_fights:
        raise ValidationError(f"a card cannot contain more than {max_card_fights} fights")

    fights: list[FightInput] = []
    exposure_cents = 0
    for index in range(1, row_count + 1):
        fighter_a = _text(form.get(f"fighter_a_{index}"))
        fighter_b = _text(form.get(f"fighter_b_{index}"))
        if not fighter_a and not fighter_b:
            continue
        if not fighter_a or not fighter_b:
            raise ValidationError(f"fight {index} needs both fighters")

        prediction_values = [
            form.get(f"picked_fighter_{index}"),
            form.get(f"confidence_{index}"),
            form.get(f"predicted_method_{index}"),
        ]
        snapshot_id = _optional_int(form.get(f"odds_snapshot_{index}"), "odds snapshot")
        wager_values = [
            form.get(f"sportsbook_{index}"),
            form.get(f"moneyline_{index}"),
            form.get(f"stake_{index}"),
        ]
        has_prediction = any(_text(value) for value in prediction_values)
        has_wager = snapshot_id is not None or any(_text(value) for value in wager_values)
        if has_wager and not has_prediction:
            raise ValidationError(f"fight {index} needs a complete prediction before its wager")

        analyst_id = None
        picked_fighter = None
        confidence = None
        if has_prediction:
            analyst_slug = _text(form.get(f"analyst_{index}"))
            analyst_id = analyst_ids.get(analyst_slug)
            if analyst_id is None:
                raise ValidationError(f"fight {index} has an unknown analyst")
            picked_side = _text(form.get(f"picked_fighter_{index}"))
            picked_fighter = {"fighter_a": fighter_a, "fighter_b": fighter_b}.get(picked_side)
            if picked_fighter is None:
                raise ValidationError(f"fight {index} pick must select fighter A or B")
            confidence = _parse_int(form.get(f"confidence_{index}"), "confidence")
            if not 0 <= confidence <= 100:
                raise ValidationError("confidence must be between 0 and 100")

        sportsbook = _optional_text(form.get(f"sportsbook_{index}"))
        moneyline = _optional_int(form.get(f"moneyline_{index}"), "moneyline")
        stake_cents = None
        if has_wager:
            if snapshot_id is None:
                if not sportsbook:
                    raise ValidationError(f"fight {index} needs a sportsbook")
                if moneyline is None or moneyline == 0 or -100 < moneyline < 100:
                    raise ValidationError("moneyline must be at least +100 or at most -100")
            stake_cents = _parse_stake_cents(form.get(f"stake_{index}"))
            exposure_cents += stake_cents

        try:
            bout_order = int(_text(form.get(f"bout_order_{index}")) or index)
        except ValueError as exc:
            raise ValidationError(f"fight {index} bout order must be a whole number") from exc

        fights.append(
            FightInput(
                fighter_a=fighter_a,
                fighter_b=fighter_b,
                weight_class=_optional_text(form.get(f"weight_class_{index}")),
                gender=_optional_text(form.get(f"gender_{index}")),
                card_section=_optional_text(form.get(f"card_section_{index}")),
                bout_order=bout_order,
                analyst_id=analyst_id,
                picked_fighter=picked_fighter,
                confidence=confidence,
                predicted_method=_optional_text(form.get(f"predicted_method_{index}")),
                sportsbook=sportsbook,
                moneyline=moneyline,
                stake_cents=stake_cents,
                odds_snapshot_id=snapshot_id,
                fight_id=_optional_int(form.get(f"fight_id_{index}"), "fight id"),
            )
        )

    if len(fights) > max_card_fights:
        raise ValidationError(f"a card cannot contain more than {max_card_fights} fights")
    if not fights and not allow_empty:
        raise ValidationError("add at least one fight to the card")
    bout_orders = [fight.bout_order for fight in fights]
    if any(order <= 0 for order in bout_orders):
        raise ValidationError("bout order must be a positive whole number")
    if len(bout_orders) != len(set(bout_orders)):
        raise ValidationError("bout order must be unique within the card")
    if exposure_cents > int(settings["max_exposure_cents"]):
        raise ValidationError("card exposure exceeds the configured maximum")
    return fights


def get_tracker_settings(database_path: str | Path) -> dict[str, int]:
    with connect(database_path) as connection:
        return {
            row["key"]: int(row["value"])
            for row in connection.execute("SELECT key, value FROM settings")
        }


def _is_complete_wager(fight: FightInput) -> bool:
    return (
        fight.stake_cents is not None
        and fight.odds_snapshot_id is not None
    ) or (
        fight.stake_cents is not None
        and fight.sportsbook is not None
        and fight.moneyline is not None
    )


def save_event(
    database_path: str | Path,
    *,
    promotion: str,
    name: str,
    event_date: str,
    fights: list[FightInput],
    event_id: int | None = None,
    allow_empty: bool = False,
) -> int:
    promotion = _text(promotion) or "UFC"
    name = _text(name)
    event_date = _text(event_date)
    if not name or not event_date:
        raise ValidationError("event name and date are required")

    if not fights and not (event_id is None and allow_empty):
        raise ValidationError("add at least one fight to the card")
    supplied_fight_ids = [fight.fight_id for fight in fights if fight.fight_id is not None]
    if len(supplied_fight_ids) != len(set(supplied_fight_ids)):
        raise ValidationError("a fight ID cannot be reused in one submission")
    if event_id is None and supplied_fight_ids:
        raise ValidationError("existing fight IDs are only valid when editing a card")

    finalized = bool(fights) and all(
        fight.analyst_id is not None
        and fight.picked_fighter is not None
        and fight.confidence is not None
        and _is_complete_wager(fight)
        for fight in fights
    )
    event_status = "upcoming" if finalized else "draft"

    with connect(database_path) as connection:
        with transaction(connection):
            old_fights: dict[int, dict] = {}
            preserved_snapshots: dict[int, list[dict]] = {}
            preserved_predictions: dict[int, list[dict]] = {}
            if event_id is None:
                cursor = connection.execute(
                    "INSERT INTO events(promotion, name, event_date, status) VALUES (?, ?, ?, ?)",
                    (promotion, name, event_date, event_status),
                )
                event_id = int(cursor.lastrowid)
            else:
                existing_fights = connection.execute(
                    "SELECT * FROM fights WHERE event_id = ? ORDER BY bout_order, id",
                    (event_id,),
                ).fetchall()
                old_fights = {int(row["id"]): dict(row) for row in existing_fights}
                snapshot_rows = connection.execute(
                    """
                    SELECT os.id, os.fight_id, os.fighter, os.sportsbook, os.moneyline,
                           os.captured_at, os.external_provider
                    FROM odds_snapshots os
                    JOIN fights f ON f.id = os.fight_id
                    WHERE f.event_id = ?
                    ORDER BY os.id
                    """,
                    (event_id,),
                ).fetchall()
                for row in snapshot_rows:
                    preserved_snapshots.setdefault(int(row["fight_id"]), []).append(dict(row))
                prediction_rows = connection.execute(
                    """
                    SELECT p.fight_id, p.analyst_id, p.picked_fighter,
                           p.confidence, p.predicted_method,
                           p.source_url, p.source_published_at, p.captured_at,
                           p.source_identifier
                    FROM predictions p
                    JOIN fights f ON f.id = p.fight_id
                    WHERE f.event_id = ?
                    """,
                    (event_id,),
                ).fetchall()
                for row in prediction_rows:
                    preserved_predictions.setdefault(int(row["fight_id"]), []).append(dict(row))
                event = connection.execute(
                    "SELECT status FROM events WHERE id = ?", (event_id,)
                ).fetchone()
                if event is None:
                    raise ValidationError("event not found")
                if event["status"] == "completed":
                    raise ValidationError("completed cards cannot be edited")
                connection.execute(
                    "UPDATE events SET promotion = ?, name = ?, event_date = ?, status = ? WHERE id = ?",
                    (promotion, name, event_date, event_status, event_id),
                )
                connection.execute("DELETE FROM fights WHERE event_id = ?", (event_id,))

            for fight in fights:
                if fight.fight_id is not None:
                    if event_id is None:
                        raise ValidationError("existing fight IDs are only valid when editing a card")
                    old = old_fights.get(fight.fight_id)
                    if old is None:
                        raise ValidationError("fight does not belong to this card")
                else:
                    old = {}
                cursor = connection.execute(
                    """
                    INSERT INTO fights(
                        event_id, fighter_a, fighter_b, weight_class, gender,
                        card_section, bout_order, scheduled_at, status,
                        external_provider, external_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)
                    """,
                    (
                        event_id,
                        fight.fighter_a,
                        fight.fighter_b,
                        fight.weight_class,
                        fight.gender,
                        fight.card_section,
                        fight.bout_order,
                        old.get("scheduled_at"),
                        old.get("external_provider"),
                        old.get("external_id"),
                    ),
                )
                fight_id = int(cursor.lastrowid)
                snapshot_id_map: dict[int, int] = {}
                for snapshot in preserved_snapshots.get(fight.fight_id or -1, []):
                    if snapshot["fighter"] not in {fight.fighter_a, fight.fighter_b}:
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
                            snapshot["fighter"],
                            snapshot["sportsbook"],
                            snapshot["moneyline"],
                            snapshot["captured_at"],
                            snapshot["external_provider"],
                        ),
                    )
                    snapshot_id_map[int(snapshot["id"])] = int(snapshot_cursor.lastrowid)

                if fight.analyst_id is None:
                    continue
                source = next(
                    (
                        prediction
                        for prediction in preserved_predictions.get(fight.fight_id or -1, [])
                        if prediction["analyst_id"] == fight.analyst_id
                        and tuple(sorted((old.get("fighter_a"), old.get("fighter_b"))))
                        == tuple(sorted((fight.fighter_a, fight.fighter_b)))
                        and prediction["picked_fighter"] == fight.picked_fighter
                        and prediction["confidence"] == fight.confidence
                        and prediction["predicted_method"] == fight.predicted_method
                    ),
                    None,
                )
                prediction_cursor = connection.execute(
                    """
                    INSERT INTO predictions(
                        fight_id, analyst_id, picked_fighter, confidence,
                        predicted_method, source_url, source_published_at,
                        captured_at, source_identifier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fight_id,
                        fight.analyst_id,
                        fight.picked_fighter,
                        fight.confidence,
                        fight.predicted_method,
                        source["source_url"] if source else None,
                        source["source_published_at"] if source else None,
                        source["captured_at"] if source else utc_now(),
                        source["source_identifier"] if source else None,
                    ),
                )
                if fight.stake_cents is None:
                    continue

                odds_snapshot_id = None
                wager_moneyline = fight.moneyline
                wager_sportsbook = fight.sportsbook
                if fight.odds_snapshot_id is not None:
                    odds_snapshot_id = snapshot_id_map.get(fight.odds_snapshot_id)
                    if odds_snapshot_id is None:
                        raise ValidationError("selected odds snapshot is not available for this fight")
                    snapshot = connection.execute(
                        "SELECT fight_id, fighter, sportsbook, moneyline FROM odds_snapshots WHERE id = ?",
                        (odds_snapshot_id,),
                    ).fetchone()
                    if snapshot is None or snapshot["fight_id"] != fight_id:
                        raise ValidationError("selected odds snapshot does not belong to this fight")
                    if snapshot["fighter"] != fight.picked_fighter:
                        raise ValidationError("selected odds snapshot does not price the picked fighter")
                    wager_moneyline = int(snapshot["moneyline"])
                    wager_sportsbook = snapshot["sportsbook"]
                else:
                    if wager_sportsbook is None or wager_moneyline is None:
                        raise ValidationError("manual sportsbook and moneyline are required")
                    snapshot_cursor = connection.execute(
                        """
                        INSERT INTO odds_snapshots(
                            fight_id, fighter, sportsbook, moneyline,
                            captured_at, external_provider
                        ) VALUES (?, ?, ?, ?, ?, 'manual')
                        """,
                        (
                            fight_id,
                            fight.picked_fighter,
                            wager_sportsbook,
                            wager_moneyline,
                            utc_now(),
                        ),
                    )
                    odds_snapshot_id = int(snapshot_cursor.lastrowid)

                if wager_moneyline is None or wager_sportsbook is None:
                    raise ValidationError("wager line is incomplete")
                connection.execute(
                    """
                    INSERT INTO wagers(
                        prediction_id, odds_snapshot_id, stake_cents,
                        moneyline, sportsbook, status
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        prediction_cursor.lastrowid,
                        odds_snapshot_id,
                        fight.stake_cents,
                        wager_moneyline,
                        wager_sportsbook,
                    ),
                )

    return int(event_id)


def list_events(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT e.*, COUNT(f.id) AS fight_count
            FROM events e
            LEFT JOIN fights f ON f.event_id = e.id
            GROUP BY e.id
            ORDER BY e.event_date DESC, e.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_analysts(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT id, slug, name FROM analysts WHERE active = 1 ORDER BY name"
        ).fetchall()
    return [dict(row) for row in rows]


def get_event(database_path: str | Path, event_id: int) -> dict | None:
    with connect(database_path) as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            return None
        fights = connection.execute(
            """
            SELECT
                f.*, p.id AS prediction_id, p.analyst_id,
                a.slug AS analyst_slug, a.name AS analyst_name,
                p.picked_fighter, p.confidence, p.predicted_method,
                w.id AS wager_id, w.odds_snapshot_id, w.stake_cents,
                w.moneyline, w.sportsbook, w.status AS wager_status,
                w.profit_cents
            FROM fights f
            LEFT JOIN predictions p ON p.fight_id = f.id
            LEFT JOIN analysts a ON a.id = p.analyst_id
            LEFT JOIN wagers w ON w.prediction_id = p.id
            WHERE f.event_id = ?
            ORDER BY f.bout_order, f.id
            """,
            (event_id,),
        ).fetchall()
        result_fights: list[dict] = []
        for row in fights:
            fight = dict(row)
            snapshots = connection.execute(
                """
                SELECT id, fighter, sportsbook, moneyline, captured_at, external_provider
                FROM odds_snapshots
                WHERE fight_id = ?
                ORDER BY captured_at DESC, id DESC
                """,
                (fight["id"],),
            ).fetchall()
            fight["odds_snapshots"] = [dict(snapshot) for snapshot in snapshots]
            if fight["picked_fighter"] == fight["fighter_a"]:
                fight["picked_side"] = "fighter_a"
            elif fight["picked_fighter"] == fight["fighter_b"]:
                fight["picked_side"] = "fighter_b"
            else:
                fight["picked_side"] = ""
            if fight["stake_cents"] is not None:
                fight["stake"] = f"{fight['stake_cents'] / 100:.2f}"
            result_fights.append(fight)
    result = dict(event)
    result["fights"] = result_fights
    return result
