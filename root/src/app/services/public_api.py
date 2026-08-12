from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from ..analytics import AnalyticsFilters, analytics_report
from ..db import connect


class PublicApiError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PublicPickFilters:
    event: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    gender: str | None = None
    weight_class: str | None = None
    card_section: str | None = None
    confidence_min: int | None = None
    confidence_max: int | None = None
    favorite: str | None = None
    result: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "event": self.event,
                "date_from": self.date_from,
                "date_to": self.date_to,
                "gender": self.gender,
                "weight_class": self.weight_class,
                "card_section": self.card_section,
                "confidence_min": self.confidence_min,
                "confidence_max": self.confidence_max,
                "favorite": self.favorite,
                "result": self.result,
            }.items()
            if value is not None
        }

    def as_analytics_filters(self, *, analyst: str | None = None) -> AnalyticsFilters:
        return AnalyticsFilters(
            analyst=analyst,
            event=self.event,
            gender=self.gender,
            weight_class=self.weight_class,
            card_section=self.card_section,
            confidence_min=self.confidence_min,
            confidence_max=self.confidence_max,
            favorite=self.favorite,
            result=self.result,
            date_from=self.date_from,
            date_to=self.date_to,
        )


def _query_value(values: Mapping[str, object], name: str) -> str | None:
    value = values.get(name)
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_int(values: Mapping[str, object], name: str) -> int | None:
    value = _query_value(values, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise PublicApiError("invalid_parameter", f"{name} must be an integer") from exc


def _optional_date(values: Mapping[str, object], name: str) -> str | None:
    value = _query_value(values, name)
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PublicApiError(
            "invalid_parameter", f"{name} must be an ISO-8601 date"
        ) from exc
    return value


def parse_pick_filters(values: Mapping[str, object]) -> PublicPickFilters:
    date_from = _optional_date(values, "date_from")
    date_to = _optional_date(values, "date_to")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise PublicApiError("invalid_parameter", "date_from cannot exceed date_to")

    confidence_min = _optional_int(values, "confidence_min")
    confidence_max = _optional_int(values, "confidence_max")
    if confidence_min is not None and not 0 <= confidence_min <= 100:
        raise PublicApiError("invalid_parameter", "confidence_min must be between 0 and 100")
    if confidence_max is not None and not 0 <= confidence_max <= 100:
        raise PublicApiError("invalid_parameter", "confidence_max must be between 0 and 100")
    if (
        confidence_min is not None
        and confidence_max is not None
        and confidence_min > confidence_max
    ):
        raise PublicApiError("invalid_parameter", "confidence_min cannot exceed confidence_max")

    favorite = _query_value(values, "favorite")
    underdog = _query_value(values, "underdog")
    if favorite and underdog:
        raise PublicApiError(
            "invalid_parameter", "use favorite or underdog, not both"
        )
    if favorite is not None:
        if favorite not in {"true", "1", "yes", "favorite"}:
            raise PublicApiError("invalid_parameter", "favorite must be true")
        favorite = "favorite"
    elif underdog is not None:
        if underdog not in {"true", "1", "yes", "underdog"}:
            raise PublicApiError("invalid_parameter", "underdog must be true")
        favorite = "underdog"

    result = _query_value(values, "result")
    result = {"win": "won", "loss": "lost"}.get(result, result)
    if result not in {None, "won", "lost", "push", "pending", "canceled"}:
        raise PublicApiError(
            "invalid_parameter",
            "result must be one of won, lost, push, pending, or canceled",
        )

    return PublicPickFilters(
        event=_query_value(values, "event"),
        date_from=date_from,
        date_to=date_to,
        gender=_query_value(values, "gender"),
        weight_class=_query_value(values, "weight_class"),
        card_section=_query_value(values, "card_section"),
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        favorite=favorite,
        result=result,
    )


def parse_pagination(values: Mapping[str, object]) -> tuple[int, int]:
    parsed_limit = _optional_int(values, "limit")
    parsed_offset = _optional_int(values, "offset")
    limit = 50 if parsed_limit is None else parsed_limit
    offset = 0 if parsed_offset is None else parsed_offset
    if not 1 <= limit <= 200:
        raise PublicApiError("invalid_parameter", "limit must be between 1 and 200")
    if offset < 0:
        raise PublicApiError("invalid_parameter", "offset must not be negative")
    return limit, offset


def _prediction_result(status: str, picked_fighter: str, winner: str | None) -> str:
    if status == "completed":
        return "won" if picked_fighter == winner else "lost"
    if status in {"draw", "no_contest"}:
        return "push"
    if status == "canceled":
        return "canceled"
    return "pending"


def _matches_event(event_value: str | None, row: Mapping[str, object]) -> bool:
    if event_value is None:
        return True
    if event_value.isdigit():
        return int(row["event_id"]) == int(event_value)
    return event_value.casefold() in str(row["event_name"]).casefold()


def load_public_picks(
    database_path: str | Path,
    filters: PublicPickFilters | None = None,
    *,
    analyst_slug: str | None = None,
    event_id: int | None = None,
) -> list[dict]:
    filters = filters or PublicPickFilters()
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                p.id AS prediction_id,
                p.picked_fighter,
                p.confidence,
                p.predicted_method,
                p.source_url,
                p.source_published_at,
                p.captured_at,
                a.slug AS analyst_slug,
                a.name AS analyst_name,
                a.source_type AS analyst_source_type,
                a.source_url AS analyst_source_url,
                e.id AS event_id,
                e.promotion,
                e.name AS event_name,
                e.event_date,
                e.status AS event_status,
                f.id AS fight_id,
                f.fighter_a,
                f.fighter_b,
                f.weight_class,
                f.gender,
                f.card_section,
                f.bout_order,
                f.scheduled_at,
                f.status AS fight_status,
                f.winner,
                w.moneyline AS private_moneyline
            FROM predictions p
            JOIN analysts a ON a.id = p.analyst_id
            JOIN fights f ON f.id = p.fight_id
            JOIN events e ON e.id = f.event_id
            LEFT JOIN wagers w ON w.prediction_id = p.id
            WHERE (? IS NULL OR a.slug = ?)
              AND (? IS NULL OR e.id = ?)
            ORDER BY e.event_date DESC, e.id DESC, f.bout_order, f.id, p.id
            """,
            (analyst_slug, analyst_slug, event_id, event_id),
        ).fetchall()

    result: list[dict] = []
    for raw_row in rows:
        row = dict(raw_row)
        prediction_result = _prediction_result(
            row["fight_status"], row["picked_fighter"], row["winner"]
        )
        favorite_status = None
        if row["private_moneyline"] is not None:
            favorite_status = "favorite" if row["private_moneyline"] < 0 else "underdog"
        if not _matches_event(filters.event, row):
            continue
        if filters.date_from and row["event_date"] < filters.date_from:
            continue
        if filters.date_to and row["event_date"] > filters.date_to:
            continue
        if filters.gender and row["gender"] != filters.gender:
            continue
        if filters.weight_class and row["weight_class"] != filters.weight_class:
            continue
        if filters.card_section and row["card_section"] != filters.card_section:
            continue
        if filters.confidence_min is not None and row["confidence"] < filters.confidence_min:
            continue
        if filters.confidence_max is not None and row["confidence"] > filters.confidence_max:
            continue
        if filters.favorite and favorite_status != filters.favorite:
            continue
        if filters.result and prediction_result != filters.result:
            continue
        row["prediction_result"] = prediction_result
        row["favorite_status"] = favorite_status
        result.append(row)
    return result


def _public_event(row: Mapping[str, object]) -> dict:
    return {
        "id": int(row["id"]),
        "promotion": row["promotion"],
        "name": row["name"],
        "date": row["event_date"],
        "status": row["status"],
    }


def list_public_events(
    database_path: str | Path,
    filters: PublicPickFilters | None = None,
) -> list[dict]:
    filters = filters or PublicPickFilters()
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT e.*, COUNT(f.id) AS fight_count
            FROM events e
            LEFT JOIN fights f ON f.event_id = e.id
            WHERE (? IS NULL OR e.event_date >= ?)
              AND (? IS NULL OR e.event_date <= ?)
            GROUP BY e.id
            ORDER BY e.event_date DESC, e.id DESC
            """,
            (filters.date_from, filters.date_from, filters.date_to, filters.date_to),
        ).fetchall()
    result = []
    for row in rows:
        event = dict(row)
        if not _matches_event(filters.event, {"event_id": event["id"], "event_name": event["name"]}):
            continue
        public = _public_event(event)
        public["fight_count"] = int(event["fight_count"])
        result.append(public)
    return result


def get_public_event(database_path: str | Path, event_id: int) -> dict | None:
    with connect(database_path) as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            return None
        fights = connection.execute(
            """
            SELECT id, fighter_a, fighter_b, weight_class, gender, card_section,
                   bout_order, scheduled_at, status, winner
            FROM fights
            WHERE event_id = ?
            ORDER BY bout_order, id
            """,
            (event_id,),
        ).fetchall()
    public_event = _public_event(dict(event))
    public_event["fights"] = [
        {
            "id": int(fight["id"]),
            "fighter_a": fight["fighter_a"],
            "fighter_b": fight["fighter_b"],
            "weight_class": fight["weight_class"],
            "gender": fight["gender"],
            "card_section": fight["card_section"],
            "bout_order": fight["bout_order"],
            "scheduled_at": fight["scheduled_at"],
            "status": fight["status"],
            "winner": fight["winner"],
        }
        for fight in fights
    ]
    return public_event


def list_public_analysts(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT slug, name, source_type, source_url, active
            FROM analysts
            WHERE active = 1
            ORDER BY name, slug
            """
        ).fetchall()
    return [public_analyst(dict(row)) for row in rows]


def get_public_analyst(database_path: str | Path, slug: str) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT slug, name, source_type, source_url, active
            FROM analysts
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    return public_analyst(dict(row)) if row is not None else None


def public_analyst(row: Mapping[str, object]) -> dict:
    return {
        "slug": row["slug"],
        "name": row["name"],
        "source_type": row["source_type"],
        "source_url": row["source_url"],
        "active": bool(row["active"]),
    }


def public_pick(row: Mapping[str, object]) -> dict:
    return {
        "event": {
            "id": int(row["event_id"]),
            "promotion": row["promotion"],
            "name": row["event_name"],
            "date": row["event_date"],
            "status": row["event_status"],
        },
        "fight": {
            "id": int(row["fight_id"]),
            "fighter_a": row["fighter_a"],
            "fighter_b": row["fighter_b"],
            "weight_class": row["weight_class"],
            "gender": row["gender"],
            "card_section": row["card_section"],
            "bout_order": row["bout_order"],
            "scheduled_at": row["scheduled_at"],
            "status": row["fight_status"],
            "winner": row["winner"],
        },
        "analyst": {
            "slug": row["analyst_slug"],
            "name": row["analyst_name"],
        },
        "prediction": {
            "fighter": row["picked_fighter"],
            "confidence": int(row["confidence"]),
            "method": row["predicted_method"],
            "result": row["prediction_result"],
            "source_url": row["source_url"],
            "source_published_at": row["source_published_at"],
            "captured_at": row["captured_at"],
        },
    }


def public_stats(
    database_path: str | Path,
    analyst_slug: str,
    filters: PublicPickFilters,
) -> dict:
    report = analytics_report(
        database_path,
        filters.as_analytics_filters(analyst=analyst_slug),
    )
    summary = report["summary"]
    return {
        "analyst": get_public_analyst(database_path, analyst_slug),
        "filters": filters.as_dict(),
        "sample_size": summary["sample_size"],
        "wager_sample_size": summary["wager_sample_size"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "pushes": summary["pushes"],
        "accuracy": summary["accuracy"],
        "roi": summary["roi"],
    }
