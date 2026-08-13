from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..db import connect, initialize_database, transaction
from ..providers.ufcstats_csv import (
    FightRecord,
    RoundStatRecord,
    UFCStatsSource,
    load_source,
)


class CatalogImportError(ValueError):
    pass


@dataclass
class ImportSummary:
    source_directory: str
    events_processed: int = 0
    events_inserted: int = 0
    events_updated: int = 0
    events_failed: int = 0
    fighters_inserted: int = 0
    fighters_updated: int = 0
    fights_inserted: int = 0
    fights_updated: int = 0
    fights_failed: int = 0
    stat_rows_inserted: int = 0
    stat_rows_updated: int = 0
    stat_rows_removed: int = 0
    unresolved_fighter_identities: set[str] = field(default_factory=set)
    unsupported_outcomes: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return bool(
            self.events_failed
            or self.fights_failed
            or self.unresolved_fighter_identities
            or self.unsupported_outcomes
            or self.errors
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "source_directory": self.source_directory,
            "events_processed": self.events_processed,
            "events_inserted": self.events_inserted,
            "events_updated": self.events_updated,
            "events_failed": self.events_failed,
            "fighters_inserted": self.fighters_inserted,
            "fighters_updated": self.fighters_updated,
            "fights_inserted": self.fights_inserted,
            "fights_updated": self.fights_updated,
            "fights_failed": self.fights_failed,
            "stat_rows_inserted": self.stat_rows_inserted,
            "stat_rows_updated": self.stat_rows_updated,
            "stat_rows_removed": self.stat_rows_removed,
            "unresolved_fighter_identities": sorted(self.unresolved_fighter_identities),
            "unsupported_outcomes": sorted(self.unsupported_outcomes),
            "errors": sorted(self.errors),
        }


class _EventFailure(CatalogImportError):
    pass
_COMMITTED_COUNTERS = ("events_inserted", "events_updated", "fights_inserted", "fights_updated", "stat_rows_inserted", "stat_rows_updated", "stat_rows_removed")


def _merge_event_summary(target: ImportSummary, event_summary: ImportSummary) -> None:
    for name in _COMMITTED_COUNTERS:
        setattr(target, name, getattr(target, name) + getattr(event_summary, name))
    target.unresolved_fighter_identities.update(event_summary.unresolved_fighter_identities)
    target.unsupported_outcomes.update(event_summary.unsupported_outcomes)
    target.errors.extend(event_summary.errors)


def _record_event_failure(target: ImportSummary, event_summary: ImportSummary, event_name: str, error: str, fight_count: int) -> None:
    target.events_failed += 1
    target.fights_failed += fight_count
    target.unresolved_fighter_identities.update(event_summary.unresolved_fighter_identities)
    target.unsupported_outcomes.update(event_summary.unsupported_outcomes)
    target.errors.extend(event_summary.errors)
    target.errors.append(f"{event_name}: {error}")


def _name_key(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _outcome(outcome: str, fighter_a: str, fighter_b: str) -> tuple[str, str | None]:
    normalized = outcome.strip().upper()
    if normalized == "W/L":
        return "completed", fighter_a
    if normalized == "L/W":
        return "completed", fighter_b
    if normalized == "D/D":
        return "draw", None
    if normalized == "NC/NC":
        return "no_contest", None
    raise CatalogImportError(f"unsupported outcome: {outcome}")


def _upsert_fighters(connection: sqlite3.Connection, source: UFCStatsSource, summary: ImportSummary) -> dict[str, int]:
    fighter_ids: dict[str, int] = {}
    for fighter in source.fighters:
        existing = connection.execute(
            """
            SELECT f.*
            FROM fighters f
            JOIN fighter_external_identities x ON x.fighter_id = f.id
            WHERE x.provider = ? AND x.external_id = ?
            """,
            ("ufcstats", fighter.external_id),
        ).fetchone()
        values = (
            fighter.canonical_name,
            fighter.first_name,
            fighter.last_name,
            fighter.nickname,
            fighter.date_of_birth,
            fighter.height_inches,
            fighter.weight_lbs,
            fighter.reach_inches,
            fighter.stance,
        )
        if existing is None:
            fighter_id = connection.execute(
                """
                INSERT INTO fighters(
                    canonical_name, first_name, last_name, nickname,
                    date_of_birth, height_inches, weight_lbs, reach_inches, stance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                values,
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO fighter_external_identities(
                    fighter_id, provider, external_id, source_url
                ) VALUES (?, 'ufcstats', ?, ?)
                """,
                (fighter_id, fighter.external_id, fighter.source_url),
            )
            summary.fighters_inserted += 1
        else:
            fighter_id = existing["id"]
            if tuple(existing[field] for field in (
                "canonical_name", "first_name", "last_name", "nickname",
                "date_of_birth", "height_inches", "weight_lbs", "reach_inches", "stance",
            )) != values:
                connection.execute(
                    """
                    UPDATE fighters
                    SET canonical_name = ?, first_name = ?, last_name = ?, nickname = ?,
                        date_of_birth = ?, height_inches = ?, weight_lbs = ?,
                        reach_inches = ?, stance = ?
                    WHERE id = ?
                    """,
                    (*values, fighter_id),
                )
                summary.fighters_updated += 1
            connection.execute(
                """
                UPDATE fighter_external_identities
                SET source_url = ?
                WHERE provider = 'ufcstats' AND external_id = ?
                """,
                (fighter.source_url, fighter.external_id),
            )
        fighter_ids[fighter.external_id] = int(fighter_id)
    return fighter_ids


def _fighter_name_index(connection: sqlite3.Connection) -> dict[str, list[int]]:
    rows = connection.execute(
        """
        SELECT f.id, f.canonical_name
        FROM fighters f
        JOIN fighter_external_identities x ON x.fighter_id = f.id
        WHERE x.provider = 'ufcstats'
        """
    ).fetchall()
    index: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        index[_name_key(row["canonical_name"])].append(int(row["id"]))
    return dict(index)


def _resolve_fighter(
    name: str,
    names: dict[str, list[int]],
    summary: ImportSummary,
) -> int:
    matches = names.get(_name_key(name), [])
    if len(matches) != 1:
        summary.unresolved_fighter_identities.add(name)
        if not matches:
            raise _EventFailure(f"unresolved fighter identity: {name}")
        raise _EventFailure(f"ambiguous fighter identity: {name}")
    return matches[0]


def _stat_values(stat: RoundStatRecord, fighter_id: int, fight_id: int) -> tuple[object, ...]:
    return (
        fight_id,
        fighter_id,
        stat.round_number,
        stat.knockdowns,
        stat.sig_strikes_landed,
        stat.sig_strikes_attempted,
        stat.sig_strike_pct,
        stat.total_strikes_landed,
        stat.total_strikes_attempted,
        stat.takedowns_landed,
        stat.takedowns_attempted,
        stat.takedown_pct,
        stat.submission_attempts,
        stat.reversals,
        stat.control_seconds,
        stat.head_landed,
        stat.head_attempted,
        stat.body_landed,
        stat.body_attempted,
        stat.leg_landed,
        stat.leg_attempted,
        stat.distance_landed,
        stat.distance_attempted,
        stat.clinch_landed,
        stat.clinch_attempted,
        stat.ground_landed,
        stat.ground_attempted,
    )


def _sync_stats(
    connection: sqlite3.Connection,
    fight_id: int,
    fighter_a_id: int,
    fighter_b_id: int,
    fighter_a: str,
    fighter_b: str,
    stats: list[RoundStatRecord],
    summary: ImportSummary,
) -> None:
    expected: set[tuple[int, int]] = set()
    for stat in stats:
        key = _name_key(stat.fighter)
        if key == _name_key(fighter_a) and key != _name_key(fighter_b):
            fighter_id = fighter_a_id
        elif key == _name_key(fighter_b) and key != _name_key(fighter_a):
            fighter_id = fighter_b_id
        else:
            raise _EventFailure(f"stat fighter does not match bout: {stat.fighter}")
        stat_key = (fighter_id, stat.round_number)
        if stat_key in expected:
            raise _EventFailure(f"duplicate round stat: {stat.fighter} round {stat.round_number}")
        expected.add(stat_key)
        existing = connection.execute(
            """
            SELECT id FROM fight_round_stats
            WHERE fight_id = ? AND fighter_id = ? AND round_number = ?
            """,
            (fight_id, fighter_id, stat.round_number),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO fight_round_stats(
                fight_id, fighter_id, round_number, knockdowns,
                sig_strikes_landed, sig_strikes_attempted, sig_strike_pct,
                total_strikes_landed, total_strikes_attempted,
                takedowns_landed, takedowns_attempted, takedown_pct,
                submission_attempts, reversals, control_seconds,
                head_landed, head_attempted, body_landed, body_attempted,
                leg_landed, leg_attempted, distance_landed, distance_attempted,
                clinch_landed, clinch_attempted, ground_landed, ground_attempted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fight_id, fighter_id, round_number) DO UPDATE SET
                knockdowns = excluded.knockdowns,
                sig_strikes_landed = excluded.sig_strikes_landed,
                sig_strikes_attempted = excluded.sig_strikes_attempted,
                sig_strike_pct = excluded.sig_strike_pct,
                total_strikes_landed = excluded.total_strikes_landed,
                total_strikes_attempted = excluded.total_strikes_attempted,
                takedowns_landed = excluded.takedowns_landed,
                takedowns_attempted = excluded.takedowns_attempted,
                takedown_pct = excluded.takedown_pct,
                submission_attempts = excluded.submission_attempts,
                reversals = excluded.reversals,
                control_seconds = excluded.control_seconds,
                head_landed = excluded.head_landed,
                head_attempted = excluded.head_attempted,
                body_landed = excluded.body_landed,
                body_attempted = excluded.body_attempted,
                leg_landed = excluded.leg_landed,
                leg_attempted = excluded.leg_attempted,
                distance_landed = excluded.distance_landed,
                distance_attempted = excluded.distance_attempted,
                clinch_landed = excluded.clinch_landed,
                clinch_attempted = excluded.clinch_attempted,
                ground_landed = excluded.ground_landed,
                ground_attempted = excluded.ground_attempted
            """,
            _stat_values(stat, fighter_id, fight_id),
        )
        if existing is None:
            summary.stat_rows_inserted += 1
        else:
            summary.stat_rows_updated += 1

    rows = connection.execute(
        "SELECT fighter_id, round_number FROM fight_round_stats WHERE fight_id = ?",
        (fight_id,),
    ).fetchall()
    for row in rows:
        if (row["fighter_id"], row["round_number"]) not in expected:
            connection.execute(
                """
                DELETE FROM fight_round_stats
                WHERE fight_id = ? AND fighter_id = ? AND round_number = ?
                """,
                (fight_id, row["fighter_id"], row["round_number"]),
            )
            summary.stat_rows_removed += 1


def _sync_event(
    connection: sqlite3.Connection,
    event,
    fights: list[FightRecord],
    stats_by_bout: dict[str, list[RoundStatRecord]],
    names: dict[str, list[int]],
    summary: ImportSummary,
) -> bool:
    try:
        prepared: list[tuple[FightRecord, int, int, str, str | None, list[RoundStatRecord]]] = []
        for fight in fights:
            fighter_a_id = _resolve_fighter(fight.fighter_a, names, summary)
            fighter_b_id = _resolve_fighter(fight.fighter_b, names, summary)
            status, winner = _outcome(fight.outcome, fight.fighter_a, fight.fighter_b)
            if status == "completed":
                winner_id = fighter_a_id if winner == fight.fighter_a else fighter_b_id
            else:
                winner_id = None
            bout_stats = stats_by_bout.get(fight.bout, [])
            if len(fights) > 1 and sum(item.bout == fight.bout for item in fights) > 1 and bout_stats:
                raise _EventFailure(f"ambiguous statistics matchup: {fight.bout}")
            prepared.append((fight, fighter_a_id, fighter_b_id, status, winner, bout_stats))
        for bout, bout_stats in stats_by_bout.items():
            if not any(fight.bout == bout for fight in fights):
                raise _EventFailure(f"statistics have no matching fight: {bout}")

        existing_event = connection.execute(
            """
            SELECT id FROM events
            WHERE external_provider = 'ufcstats' AND external_id = ?
            """,
            (event.external_id,),
        ).fetchone()
        if existing_event is None:
            event_id = connection.execute(
                """
                INSERT INTO events(
                    promotion, name, event_date, external_provider, external_id,
                    location, source_url, status
                ) VALUES ('UFC', ?, ?, 'ufcstats', ?, ?, ?, 'completed')
                RETURNING id
                """,
                (event.name, event.event_date, event.external_id, event.location, event.source_url),
            ).fetchone()["id"]
            summary.events_inserted += 1
        else:
            event_id = existing_event["id"]
            connection.execute(
                """
                UPDATE events
                SET promotion = 'UFC', name = ?, event_date = ?, location = ?,
                    source_url = ?, status = 'completed'
                WHERE id = ?
                """,
                (event.name, event.event_date, event.location, event.source_url, event_id),
            )
            summary.events_updated += 1

        for fight, fighter_a_id, fighter_b_id, status, winner, bout_stats in prepared:
            existing_fight = connection.execute(
                """
                SELECT id, event_id FROM fights
                WHERE external_provider = 'ufcstats' AND external_id = ?
                """,
                (fight.external_id,),
            ).fetchone()
            order_conflict = connection.execute(
                "SELECT id FROM fights WHERE event_id = ? AND bout_order = ?",
                (event_id, fight.bout_order),
            ).fetchone()
            if existing_fight is not None and existing_fight["event_id"] != event_id:
                raise _EventFailure(f"fight identity belongs to another event: {fight.external_id}")
            if order_conflict is not None and (
                existing_fight is None or order_conflict["id"] != existing_fight["id"]
            ):
                raise _EventFailure(f"bout-order conflict at {fight.bout_order}")
            if existing_fight is None:
                fight_id = connection.execute(
                    """
                    INSERT INTO fights(
                        event_id, fighter_a, fighter_b, fighter_a_id, fighter_b_id,
                        weight_class, bout_order, status, winner, winner_id,
                        external_provider, external_id, result_method, result_round,
                        result_time, result_time_format, referee, result_details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ufcstats', ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        event_id, fight.fighter_a, fight.fighter_b, fighter_a_id, fighter_b_id,
                        fight.weight_class, fight.bout_order, status, winner,
                        fighter_a_id if winner == fight.fighter_a else (
                            fighter_b_id if winner == fight.fighter_b else None
                        ), fight.external_id, fight.method, fight.result_round,
                        fight.result_time, fight.result_time_format, fight.referee,
                        fight.result_details,
                    ),
                ).fetchone()["id"]
                summary.fights_inserted += 1
            else:
                fight_id = existing_fight["id"]
                connection.execute(
                    """
                    UPDATE fights
                    SET event_id = ?, fighter_a = ?, fighter_b = ?, fighter_a_id = ?,
                        fighter_b_id = ?, weight_class = ?, bout_order = ?, status = ?,
                        winner = ?, winner_id = ?, result_method = ?, result_round = ?,
                        result_time = ?, result_time_format = ?, referee = ?, result_details = ?
                    WHERE id = ?
                    """,
                    (
                        event_id, fight.fighter_a, fight.fighter_b, fighter_a_id, fighter_b_id,
                        fight.weight_class, fight.bout_order, status, winner,
                        fighter_a_id if winner == fight.fighter_a else (
                            fighter_b_id if winner == fight.fighter_b else None
                        ), fight.method, fight.result_round, fight.result_time,
                        fight.result_time_format, fight.referee, fight.result_details, fight_id,
                    ),
                )
                summary.fights_updated += 1
            _sync_stats(
                connection, fight_id, fighter_a_id, fighter_b_id,
                fight.fighter_a, fight.fighter_b, bout_stats, summary,
            )
        return True
    except CatalogImportError:
        raise
    except sqlite3.IntegrityError as exc:
        raise _EventFailure(str(exc)) from exc


def sync_catalog(
    database_path: str | Path,
    source: UFCStatsSource | str | Path,
) -> ImportSummary:
    if not isinstance(source, UFCStatsSource):
        source_path = Path(source)
        source = load_source(source_path)
    else:
        source_path = Path("<normalized source>")
    summary = ImportSummary(str(source_path))
    known_event_names = {event.name for event in source.events}
    fights_by_event: dict[str, list[FightRecord]] = defaultdict(list)
    for fight in source.fights:
        if fight.event_name in known_event_names:
            fights_by_event[fight.event_name].append(fight)
        else:
            summary.fights_failed += 1
            summary.errors.append(f"fight references unknown event: {fight.event_name}")
    stats_by_event: dict[str, dict[str, list[RoundStatRecord]]] = defaultdict(lambda: defaultdict(list))
    for stat in source.round_stats:
        if stat.event_name in known_event_names:
            stats_by_event[stat.event_name][stat.bout].append(stat)
        else:
            summary.errors.append(f"statistics reference unknown event: {stat.event_name}")

    database_path = Path(database_path)
    initialize_database(database_path)
    with connect(database_path) as connection:
        with transaction(connection):
            fighter_ids = _upsert_fighters(connection, source, summary)
            del fighter_ids
        names = _fighter_name_index(connection)
        issues_by_event: dict[str, list[str]] = defaultdict(list)
        invalid_fighter_names: set[str] = set()
        for issue in source.content_errors:
            if issue.event_name:
                issues_by_event[issue.event_name].append(issue.message)
            else:
                summary.errors.append(issue.message)
            if issue.fighter_name:
                invalid_fighter_names.add(_name_key(issue.fighter_name))

        known_event_names = {event.name for event in source.events}
        for event_name, errors in sorted(issues_by_event.items()):
            if event_name not in known_event_names:
                summary.events_processed += 1
                _record_event_failure(summary, ImportSummary(summary.source_directory), event_name, "; ".join(errors), 0)

        for event in source.events:
            summary.events_processed += 1
            event_fights = fights_by_event.get(event.name, [])
            event_summary = ImportSummary(summary.source_directory)
            event_errors = list(issues_by_event.get(event.name, []))
            for fight in event_fights:
                if (_name_key(fight.fighter_a) in invalid_fighter_names or
                        _name_key(fight.fighter_b) in invalid_fighter_names):
                    event_errors.append(f"fight depends on malformed fighter content: {fight.bout}")
            if event_errors:
                _record_event_failure(summary, event_summary, event.name, "; ".join(event_errors), len(event_fights))
                continue
            try:
                with transaction(connection):
                    _sync_event(connection, event, event_fights, stats_by_event.get(event.name, {}), names, event_summary)
                _merge_event_summary(summary, event_summary)
            except _EventFailure as exc:
                _record_event_failure(summary, event_summary, event.name, str(exc), len(event_fights))
            except CatalogImportError as exc:
                if str(exc).startswith("unsupported outcome:"):
                    event_summary.unsupported_outcomes.add(str(exc).split(": ", 1)[1])
                _record_event_failure(summary, event_summary, event.name, str(exc), len(event_fights))
    return summary
