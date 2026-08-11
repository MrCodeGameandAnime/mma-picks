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


def parse_fights(form: Mapping[str, str], database_path: str | Path) -> list[FightInput]:
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
        wager_values = [
            form.get(f"sportsbook_{index}"),
            form.get(f"moneyline_{index}"),
            form.get(f"stake_{index}"),
        ]
        has_prediction = any(_text(value) for value in prediction_values)
        has_wager = any(_text(value) for value in wager_values)
        if has_wager and not has_prediction:
            raise ValidationError(f"fight {index} needs a complete prediction before its wager")
        analyst_id = None
        picked_fighter = None
        confidence = None
        sportsbook = None
        moneyline = None
        stake_cents = None

        if has_prediction:
            analyst_slug = _text(form.get(f"analyst_{index}"))
            analyst_id = analyst_ids.get(analyst_slug)
            if analyst_id is None:
                raise ValidationError(f"fight {index} has an unknown analyst")
            picked_side = _text(form.get(f"picked_fighter_{index}"))
            picked_fighter = {
                "fighter_a": fighter_a,
                "fighter_b": fighter_b,
            }.get(picked_side)
            if picked_fighter is None:
                raise ValidationError(f"fight {index} pick must select fighter A or B")
            confidence = _parse_int(form.get(f"confidence_{index}"), "confidence")
            if not 0 <= confidence <= 100:
                raise ValidationError("confidence must be between 0 and 100")

        if has_wager:
            sportsbook = _text(form.get(f"sportsbook_{index}"))
            if not sportsbook:
                raise ValidationError(f"fight {index} needs a sportsbook")
            moneyline = _parse_int(form.get(f"moneyline_{index}"), "moneyline")
            if moneyline == 0 or -100 < moneyline < 100:
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
                odds_snapshot_id=_optional_int(
                    form.get(f"odds_snapshot_{index}"), "odds snapshot"
                ),
            )
        )

    if len(fights) > max_card_fights:
        raise ValidationError(f"a card cannot contain more than {max_card_fights} fights")
    if not fights:
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


def save_event(
    database_path: str | Path,
    *,
    promotion: str,
    name: str,
    event_date: str,
    fights: list[FightInput],
    event_id: int | None = None,
) -> int:
    promotion = _text(promotion) or "UFC"
    name = _text(name)
    event_date = _text(event_date)
    if not name or not event_date:
        raise ValidationError("event name and date are required")

    finalized = all(
        fight.analyst_id is not None
        and fight.picked_fighter is not None
        and fight.confidence is not None
        and fight.sportsbook is not None
        and fight.moneyline is not None
        and fight.stake_cents is not None
        for fight in fights
    )
    event_status = "upcoming" if finalized else "draft"

    with connect(database_path) as connection:
        with transaction(connection):
            preserved_snapshots: dict[int, list[dict]] = {}
            if event_id is None:
                cursor = connection.execute(
                    "INSERT INTO events(promotion, name, event_date, status) VALUES (?, ?, ?, ?)",
                    (promotion, name, event_date, event_status),
                )
                event_id = cursor.lastrowid
            else:
                snapshot_rows = connection.execute(
                    """
                    SELECT
                        os.id, os.fighter, os.sportsbook, os.moneyline,
                        os.captured_at, os.external_provider,
                        f.bout_order, f.fighter_a, f.fighter_b
                    FROM odds_snapshots os
                    JOIN fights f ON f.id = os.fight_id
                    WHERE f.event_id = ?
                    ORDER BY os.id
                    """,
                    (event_id,),
                ).fetchall()
                for row in snapshot_rows:
                    preserved_snapshots.setdefault(row["bout_order"], []).append(dict(row))
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
                cursor = connection.execute(
                    """
                    INSERT INTO fights(
                        event_id, fighter_a, fighter_b, weight_class, gender,
                        card_section, bout_order, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled')
                    """,
                    (
                        event_id,
                        fight.fighter_a,
                        fight.fighter_b,
                        fight.weight_class,
                        fight.gender,
                        fight.card_section,
                        fight.bout_order,
                    ),
                )
                fight_id = cursor.lastrowid
                snapshot_id_map: dict[int, int] = {}
                for snapshot in preserved_snapshots.get(fight.bout_order, []):
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
                    snapshot_id_map[snapshot["id"]] = snapshot_cursor.lastrowid
                if fight.analyst_id is None:
                    continue
                cursor = connection.execute(
                    """
                    INSERT INTO predictions(
                        fight_id, analyst_id, picked_fighter, confidence,
                        predicted_method
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        fight_id,
                        fight.analyst_id,
                        fight.picked_fighter,
                        fight.confidence,
                        fight.predicted_method,
                    ),
                )
                if (
                    fight.stake_cents is None
                    or fight.moneyline is None
                    or fight.sportsbook is None
                ):
                    continue
                odds_snapshot_id = snapshot_id_map.get(fight.odds_snapshot_id)
                if odds_snapshot_id is not None:
                    snapshot = connection.execute(
                        "SELECT fighter, sportsbook, moneyline FROM odds_snapshots WHERE id = ?",
                        (odds_snapshot_id,),
                    ).fetchone()
                    if snapshot is None or tuple(snapshot) != (
                        fight.picked_fighter,
                        fight.sportsbook,
                        fight.moneyline,
                    ):
                        odds_snapshot_id = None
                if odds_snapshot_id is None:
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
                            fight.sportsbook,
                            fight.moneyline,
                            utc_now(),
                        ),
                    )
                    odds_snapshot_id = snapshot_cursor.lastrowid
                connection.execute(
                    """
                    INSERT INTO wagers(
                        prediction_id, odds_snapshot_id, stake_cents,
                        moneyline, sportsbook, status
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        cursor.lastrowid,
                        odds_snapshot_id,
                        fight.stake_cents,
                        fight.moneyline,
                        fight.sportsbook,
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
        event = connection.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return None
        fights = connection.execute(
            """
            SELECT
                f.*,
                p.id AS prediction_id,
                p.analyst_id,
                a.slug AS analyst_slug,
                a.name AS analyst_name,
                p.picked_fighter,
                p.confidence,
                p.predicted_method,
                w.id AS wager_id,
                w.odds_snapshot_id,
                w.stake_cents,
                w.moneyline,
                w.sportsbook,
                w.status AS wager_status,
                w.profit_cents
                ,(
                    SELECT os.id
                    FROM odds_snapshots os
                    WHERE os.fight_id = f.id
                    ORDER BY os.captured_at DESC, os.id DESC
                    LIMIT 1
                ) AS latest_odds_snapshot_id
                ,(
                    SELECT os.moneyline
                    FROM odds_snapshots os
                    WHERE os.fight_id = f.id
                    ORDER BY os.captured_at DESC, os.id DESC
                    LIMIT 1
                ) AS latest_odds_moneyline
                ,(
                    SELECT os.sportsbook
                    FROM odds_snapshots os
                    WHERE os.fight_id = f.id
                    ORDER BY os.captured_at DESC, os.id DESC
                    LIMIT 1
                ) AS latest_odds_sportsbook
            FROM fights f
            LEFT JOIN predictions p ON p.fight_id = f.id
            LEFT JOIN analysts a ON a.id = p.analyst_id
            LEFT JOIN wagers w ON w.prediction_id = p.id
            WHERE f.event_id = ?
            ORDER BY f.bout_order, f.id
            """,
            (event_id,),
        ).fetchall()
    result = dict(event)
    result["fights"] = [dict(row) for row in fights]
    for fight in result["fights"]:
        if fight["picked_fighter"] == fight["fighter_a"]:
            fight["picked_side"] = "fighter_a"
        elif fight["picked_fighter"] == fight["fighter_b"]:
            fight["picked_side"] = "fighter_b"
        else:
            fight["picked_side"] = ""
        if fight["odds_snapshot_id"] is None:
            fight["odds_snapshot_id"] = fight["latest_odds_snapshot_id"]
        if fight["moneyline"] is None:
            fight["moneyline"] = fight["latest_odds_moneyline"]
        if fight["sportsbook"] is None:
            fight["sportsbook"] = fight["latest_odds_sportsbook"]
        if fight["stake_cents"] is not None:
            fight["stake"] = f"{fight['stake_cents'] / 100:.2f}"
    return result
