from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping

from ..db import connect, transaction


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
            form.get(f"sportsbook_{index}"),
            form.get(f"moneyline_{index}"),
            form.get(f"stake_{index}"),
        ]
        has_prediction = any(_text(value) for value in prediction_values)
        analyst_id = None
        picked_fighter = None
        confidence = None
        sportsbook = None
        moneyline = None
        stake_cents = None

        if has_prediction:
            analyst_slug = _text(form.get(f"analyst_{index}")) or "theweasle"
            analyst_id = analyst_ids.get(analyst_slug)
            if analyst_id is None:
                raise ValidationError(f"fight {index} has an unknown analyst")
            picked_fighter = _text(form.get(f"picked_fighter_{index}"))
            if picked_fighter not in {fighter_a, fighter_b}:
                raise ValidationError(f"fight {index} pick must be one of its fighters")
            confidence = _parse_int(form.get(f"confidence_{index}"), "confidence")
            if not 0 <= confidence <= 100:
                raise ValidationError("confidence must be between 0 and 100")
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
            )
        )

    if len(fights) > max_card_fights:
        raise ValidationError(f"a card cannot contain more than {max_card_fights} fights")
    if not fights:
        raise ValidationError("add at least one fight to the card")
    if exposure_cents > int(settings["max_exposure_cents"]):
        raise ValidationError("card exposure exceeds the configured maximum")
    return fights


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

    with connect(database_path) as connection:
        with transaction(connection):
            if event_id is None:
                cursor = connection.execute(
                    "INSERT INTO events(promotion, name, event_date, status) VALUES (?, ?, ?, 'upcoming')",
                    (promotion, name, event_date),
                )
                event_id = cursor.lastrowid
            else:
                settled = connection.execute(
                    "SELECT COUNT(*) FROM wagers WHERE status <> 'pending' AND prediction_id IN "
                    "(SELECT id FROM predictions WHERE fight_id IN "
                    "(SELECT id FROM fights WHERE event_id = ?))",
                    (event_id,),
                ).fetchone()[0]
                if settled:
                    raise ValidationError("settled cards cannot be edited")
                exists = connection.execute(
                    "SELECT 1 FROM events WHERE id = ?", (event_id,)
                ).fetchone()
                if exists is None:
                    raise ValidationError("event not found")
                connection.execute(
                    "UPDATE events SET promotion = ?, name = ?, event_date = ? WHERE id = ?",
                    (promotion, name, event_date, event_id),
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
                connection.execute(
                    """
                    INSERT INTO wagers(
                        prediction_id, stake_cents, moneyline, sportsbook, status
                    ) VALUES (?, ?, ?, ?, 'pending')
                    """,
                    (
                        cursor.lastrowid,
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
                w.stake_cents,
                w.moneyline,
                w.sportsbook,
                w.status AS wager_status,
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
    result = dict(event)
    result["fights"] = [dict(row) for row in fights]
    for fight in result["fights"]:
        if fight["stake_cents"] is not None:
            fight["stake"] = f"{fight['stake_cents'] / 100:.2f}"
    return result
