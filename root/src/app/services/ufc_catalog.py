from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..db import connect


CATALOG_PROVIDER = "ufcstats"
TOTAL_FIELDS = (
    ("knockdowns", "Knockdowns"),
    ("sig_strikes", "Significant strikes"),
    ("total_strikes", "Total strikes"),
    ("takedowns", "Takedowns"),
    ("submission_attempts", "Submission attempts"),
    ("reversals", "Reversals"),
    ("control_seconds", "Control time"),
)
PAIR_FIELDS = (
    ("sig_strikes", "sig_strikes_landed", "sig_strikes_attempted"),
    ("total_strikes", "total_strikes_landed", "total_strikes_attempted"),
    ("takedowns", "takedowns_landed", "takedowns_attempted"),
)
LOCATION_FIELDS = (
    ("head", "Head"),
    ("body", "Body"),
    ("leg", "Leg"),
    ("distance", "Distance"),
    ("clinch", "Clinch"),
    ("ground", "Ground"),
)


def _sum_optional(rows: list[Mapping[str, object]], field: str) -> int | None:
    values = [row[field] for row in rows if row[field] is not None]
    return sum(int(value) for value in values) if values else None


def _aggregate_pair(rows: list[Mapping[str, object]], prefix: str) -> dict[str, int | float | None]:
    landed = _sum_optional(rows, f"{prefix}_landed")
    attempted = _sum_optional(rows, f"{prefix}_attempted")
    if landed is None or attempted is None:
        percentage = None
    elif attempted == 0:
        percentage = 0.0
    else:
        percentage = round(landed * 100 / attempted, 1)
    return {
        prefix: (f"{landed} of {attempted}" if landed is not None and attempted is not None else None),
        f"{prefix}_landed": landed,
        f"{prefix}_attempted": attempted,
        f"{prefix}_pct": percentage,
    }


def _totals(rows: list[dict]) -> dict[str, object]:
    totals: dict[str, object] = {}
    totals["knockdowns"] = _sum_optional(rows, "knockdowns")
    for prefix, _, _ in PAIR_FIELDS:
        totals.update(_aggregate_pair(rows, prefix))
    totals["submission_attempts"] = _sum_optional(rows, "submission_attempts")
    totals["reversals"] = _sum_optional(rows, "reversals")
    totals["control_seconds"] = _sum_optional(rows, "control_seconds")
    return totals


def _round_stats(rows) -> list[dict[str, object]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(int(row["round_number"]), []).append(dict(row))
    result: list[dict[str, object]] = []
    for round_number in sorted(grouped):
        fighter_rows = sorted(grouped[round_number], key=lambda row: row["fighter_id"])
        for row in fighter_rows:
            for prefix, _, _ in PAIR_FIELDS:
                pair = row.get(f"{prefix}_landed"), row.get(f"{prefix}_attempted")
                row[prefix] = (
                    f"{pair[0]} of {pair[1]}" if pair[0] is not None and pair[1] is not None else None
                )
            for prefix, label in LOCATION_FIELDS:
                row[prefix] = (
                    f"{row[f'{prefix}_landed']} of {row[f'{prefix}_attempted']}"
                    if row[f"{prefix}_landed"] is not None and row[f"{prefix}_attempted"] is not None
                    else None
                )
            result.append(row)
    return result


def list_cards(database_path: str | Path, page: int = 1, page_size: int = 50) -> dict[str, object]:
    offset = (page - 1) * page_size
    with connect(database_path) as connection:
        total = connection.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE promotion = 'UFC' AND external_provider = ?
            """,
            (CATALOG_PROVIDER,),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT e.id, e.name, e.event_date, e.location, e.source_url,
                   COUNT(f.id) AS fight_count
            FROM events e
            LEFT JOIN fights f ON f.event_id = e.id
            WHERE e.promotion = 'UFC' AND e.external_provider = ?
            GROUP BY e.id
            ORDER BY e.event_date DESC, e.id DESC
            LIMIT ? OFFSET ?
            """,
            (CATALOG_PROVIDER, page_size, offset),
        ).fetchall()
    return {
        "cards": [dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "page_count": (total + page_size - 1) // page_size,
    }


def get_card(database_path: str | Path, event_id: int) -> dict | None:
    with connect(database_path) as connection:
        event = connection.execute(
            """
            SELECT id, promotion, name, event_date, location, source_url
            FROM events
            WHERE id = ? AND promotion = 'UFC' AND external_provider = ?
            """,
            (event_id, CATALOG_PROVIDER),
        ).fetchone()
        if event is None:
            return None
        fights = connection.execute(
            """
            SELECT f.id, f.event_id, f.bout_order, f.fighter_a, f.fighter_b,
                   f.fighter_a_id, f.fighter_b_id, f.weight_class, f.status,
                   f.winner, f.result_method, f.external_id,
                   fa.canonical_name AS fighter_a_canonical,
                   fb.canonical_name AS fighter_b_canonical
            FROM fights f
            LEFT JOIN fighters fa ON fa.id = f.fighter_a_id
            LEFT JOIN fighters fb ON fb.id = f.fighter_b_id
            WHERE f.event_id = ?
            ORDER BY f.bout_order, f.id
            """,
            (event_id,),
        ).fetchall()
    result = dict(event)
    result["fights"] = [dict(row) for row in fights]
    return result


def get_fight(database_path: str | Path, event_id: int, fight_id: int) -> dict | None:
    card = get_card(database_path, event_id)
    if card is None:
        return None
    fight = next((fight for fight in card["fights"] if fight["id"] == fight_id), None)
    if fight is None:
        return None
    with connect(database_path) as connection:
        fighter_rows = connection.execute(
            """
            SELECT f.id, f.canonical_name, f.first_name, f.last_name, f.nickname,
                   f.date_of_birth, f.height_inches, f.weight_lbs, f.reach_inches,
                   f.stance, x.source_url
            FROM fighters f
            LEFT JOIN fighter_external_identities x
              ON x.fighter_id = f.id AND x.provider = ?
            WHERE f.id IN (?, ?)
            """,
            (CATALOG_PROVIDER, fight["fighter_a_id"], fight["fighter_b_id"]),
        ).fetchall()
        stats = connection.execute(
            """
            SELECT s.*, f.canonical_name AS fighter_name
            FROM fight_round_stats s
            JOIN fighters f ON f.id = s.fighter_id
            WHERE s.fight_id = ?
            ORDER BY s.round_number, s.fighter_id
            """,
            (fight_id,),
        ).fetchall()
    fighters = {row["id"]: dict(row) for row in fighter_rows}
    fight["fighter_a_profile"] = fighters.get(fight["fighter_a_id"])
    fight["fighter_b_profile"] = fighters.get(fight["fighter_b_id"])
    stats_rows = [dict(row) for row in stats]
    fight["totals"] = {
        fighter_id: _totals([row for row in stats_rows if row["fighter_id"] == fighter_id])
        for fighter_id in (fight["fighter_a_id"], fight["fighter_b_id"])
    }
    fight["round_stats"] = _round_stats(stats_rows)
    fight["card"] = {key: card[key] for key in ("id", "name", "event_date")}
    return fight


def get_fighter(database_path: str | Path, fighter_id: int) -> dict | None:
    with connect(database_path) as connection:
        fighter = connection.execute(
            """
            SELECT f.*, x.source_url
            FROM fighters f
            LEFT JOIN fighter_external_identities x
              ON x.fighter_id = f.id AND x.provider = ?
            WHERE f.id = ?
            """,
            (CATALOG_PROVIDER, fighter_id),
        ).fetchone()
        if fighter is None:
            return None
        history = connection.execute(
            """
            SELECT f.id AS fight_id, f.event_id, e.name AS event_name,
                   e.event_date, f.fighter_a, f.fighter_b, f.status,
                   f.winner, f.result_method, f.fighter_a_id, f.fighter_b_id,
                   CASE WHEN f.fighter_a_id = ? THEN f.fighter_b_id ELSE f.fighter_a_id END AS opponent_id,
                   CASE
                       WHEN f.status = 'draw' THEN 'Draw'
                       WHEN f.status = 'no_contest' THEN 'No contest'
                       WHEN f.winner_id = ? THEN 'Win'
                       WHEN f.status = 'completed' THEN 'Loss'
                       ELSE f.status
                   END AS result
            FROM fights f
            JOIN events e ON e.id = f.event_id
            WHERE e.external_provider = ? AND (f.fighter_a_id = ? OR f.fighter_b_id = ?)
            ORDER BY e.event_date DESC, f.bout_order, f.id
            """,
            (fighter_id, fighter_id, CATALOG_PROVIDER, fighter_id, fighter_id),
        ).fetchall()
    profile = dict(fighter)
    profile["history"] = [dict(row) for row in history]
    for row in profile["history"]:
        row["opponent"] = row["fighter_b"] if row["fighter_a_id"] == fighter_id else row["fighter_a"]
    return profile
