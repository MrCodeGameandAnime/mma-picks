from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


PROVIDER = "ufcstats"
_IDENTITY_RE = re.compile(r"^/([^/]+)-details/([0-9a-fA-F]+?)/?$")
_BOUT_RE = re.compile(r"^(.+?)\s+vs\.\s+(.+?)$")
_ROUND_RE = re.compile(r"^Round\s+(\d+)$", re.IGNORECASE)
_PAIR_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s+of\s+(-?\d+(?:\.\d+)?)$")
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d")


class UFCStatsSourceError(ValueError):
    pass

@dataclass(frozen=True)
class SourceContentError:
    event_name: str | None
    message: str
    fighter_name: str | None = None


@dataclass(frozen=True)
class EventRecord:
    name: str
    source_url: str
    external_id: str
    event_date: str
    location: str | None


@dataclass(frozen=True)
class FighterRecord:
    external_id: str
    source_url: str
    canonical_name: str
    first_name: str | None
    last_name: str | None
    nickname: str | None
    date_of_birth: str | None
    height_inches: int | None
    weight_lbs: int | None
    reach_inches: float | None
    stance: str | None


@dataclass(frozen=True)
class FightRecord:
    event_name: str
    bout: str
    fighter_a: str
    fighter_b: str
    source_url: str
    external_id: str
    weight_class: str | None
    outcome: str
    method: str | None
    result_round: int | None
    result_time: str | None
    result_time_format: str | None
    referee: str | None
    result_details: str | None
    bout_order: int


@dataclass(frozen=True)
class RoundStatRecord:
    event_name: str
    bout: str
    round_number: int
    fighter: str
    knockdowns: int | None
    sig_strikes_landed: int | None
    sig_strikes_attempted: int | None
    sig_strike_pct: float | None
    total_strikes_landed: int | None
    total_strikes_attempted: int | None
    takedowns_landed: int | None
    takedowns_attempted: int | None
    takedown_pct: float | None
    submission_attempts: int | None
    reversals: int | None
    control_seconds: int | None
    head_landed: int | None
    head_attempted: int | None
    body_landed: int | None
    body_attempted: int | None
    leg_landed: int | None
    leg_attempted: int | None
    distance_landed: int | None
    distance_attempted: int | None
    clinch_landed: int | None
    clinch_attempted: int | None
    ground_landed: int | None
    ground_attempted: int | None


@dataclass(frozen=True)
class UFCStatsSource:
    events: tuple[EventRecord, ...]
    fighters: tuple[FighterRecord, ...]
    fights: tuple[FightRecord, ...]
    round_stats: tuple[RoundStatRecord, ...]
    content_errors: tuple[SourceContentError, ...] = ()


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.strip().split())
    return value or None


def _required(row: dict[str, str], field: str, line_number: int) -> str:
    value = _text(row.get(field))
    if value is None:
        raise UFCStatsSourceError(f"line {line_number}: missing {field}")
    return value


def _parse_identity(url: str, kind: str) -> tuple[str, str]:
    source_url = _required({"value": url}, "value", 0)
    parsed = urlparse(source_url)
    match = _IDENTITY_RE.fullmatch(parsed.path)
    if parsed.netloc.lower() != "ufcstats.com" or match is None:
        raise UFCStatsSourceError(f"invalid UFCStats {kind} URL: {source_url}")
    actual_kind, external_id = match.groups()
    if actual_kind != kind:
        raise UFCStatsSourceError(
            f"expected UFCStats {kind} URL, got {source_url}"
        )
    return external_id.lower(), source_url


def parse_ufcstats_id(url: str, kind: str) -> str:
    return _parse_identity(url, kind)[0]


def _parse_date(value: str | None) -> str:
    text = _text(value)
    if text is None:
        raise UFCStatsSourceError("missing date")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise UFCStatsSourceError(f"invalid date: {text}")


def parse_date(value: str) -> str:
    return _parse_date(value)


def _missing(value: str | None) -> bool:
    return _text(value) in {None, "--", "---"}


def _parse_number(value: str | None, *, integer: bool = True) -> int | float | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    try:
        number = float(text)
    except ValueError as exc:
        raise UFCStatsSourceError(f"invalid numeric value: {text}") from exc
    if integer and not number.is_integer():
        raise UFCStatsSourceError(f"expected integer value: {text}")
    return int(number) if integer else number


def parse_height(value: str | None) -> int | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    match = re.fullmatch(r"(\d+)['’]\s*(\d+)(?:\"|”)?", text)
    if match is None:
        raise UFCStatsSourceError(f"invalid height: {text}")
    feet, inches = (int(part) for part in match.groups())
    if inches >= 12:
        raise UFCStatsSourceError(f"invalid height: {text}")
    return feet * 12 + inches


def parse_reach(value: str | None) -> float | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    cleaned = text.removesuffix('"').strip()
    return float(_parse_number(cleaned, integer=False))


def parse_weight(value: str | None) -> int | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    cleaned = re.sub(r"\s+lbs?\.?$", "", text, flags=re.IGNORECASE).strip()
    return int(_parse_number(cleaned))


def parse_dob(value: str | None) -> str | None:
    if _missing(value):
        return None
    return _parse_date(value)


def parse_pair(value: str | None) -> tuple[int, int] | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    match = _PAIR_RE.fullmatch(text)
    if match is None:
        raise UFCStatsSourceError(f"invalid landed/attempted value: {text}")
    return int(float(match.group(1))), int(float(match.group(2)))


def parse_percentage(value: str | None) -> float | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    if not text.endswith("%"):
        raise UFCStatsSourceError(f"invalid percentage: {text}")
    return float(_parse_number(text[:-1], integer=False))


def parse_control_time(value: str | None) -> int | None:
    if _missing(value):
        return None
    text = _text(value)
    assert text is not None
    parts = text.split(":")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        raise UFCStatsSourceError(f"invalid control time: {text}")
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        if seconds >= 60:
            raise UFCStatsSourceError(f"invalid control time: {text}")
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        raise UFCStatsSourceError(f"invalid control time: {text}")
    return hours * 3600 + minutes * 60 + seconds


def _load_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UFCStatsSourceError(f"cannot read {path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or tuple(reader.fieldnames) != fields:
            raise UFCStatsSourceError(
                f"unexpected headers in {path.name}: {reader.fieldnames}"
            )
        return list(reader)


def _parse_events(
    source_dir: Path,
    issues: list[SourceContentError] | None = None,
) -> tuple[EventRecord, ...]:
    issues = issues if issues is not None else []
    fields = ("EVENT", "URL", "DATE", "LOCATION")
    records: list[EventRecord] = []
    seen: set[str] = set()
    for line_number, row in enumerate(_load_csv(source_dir / "ufc_event_details.csv", fields), 2):
        event_name = _text(row.get("EVENT"))
        try:
            name = _required(row, "EVENT", line_number)
            external_id, source_url = _parse_identity(_required(row, "URL", line_number), "event")
            if external_id in seen:
                raise UFCStatsSourceError(f"duplicate event identity: {external_id}")
            event_date = _parse_date(row.get("DATE"))
            seen.add(external_id)
            records.append(EventRecord(name, source_url, external_id, event_date, _text(row.get("LOCATION"))))
        except UFCStatsSourceError as exc:
            issues.append(SourceContentError(event_name, f"event line {line_number}: {exc}"))
    return tuple(records)


def _parse_fighters(
    source_dir: Path,
    issues: list[SourceContentError] | None = None,
) -> tuple[FighterRecord, ...]:
    issues = issues if issues is not None else []
    detail_fields = ("FIRST", "LAST", "NICKNAME", "URL")
    tott_fields = ("FIGHTER", "HEIGHT", "WEIGHT", "REACH", "STANCE", "DOB", "URL")
    details: dict[str, dict[str, str]] = {}
    urls: dict[str, str] = {}
    invalid_ids: set[str] = set()

    for line_number, row in enumerate(_load_csv(source_dir / "ufc_fighter_details.csv", detail_fields), 2):
        fighter_name = " ".join(part for part in (_text(row.get("FIRST")), _text(row.get("LAST"))) if part) or None
        try:
            external_id, source_url = _parse_identity(_required(row, "URL", line_number), "fighter")
            if external_id in details:
                raise UFCStatsSourceError(f"duplicate fighter identity: {external_id}")
            details[external_id] = dict(row)
            urls[external_id] = source_url
        except UFCStatsSourceError as exc:
            issues.append(SourceContentError(None, f"fighter detail line {line_number}: {exc}", fighter_name))

    tott: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(_load_csv(source_dir / "ufc_fighter_tott.csv", tott_fields), 2):
        fighter_name = _text(row.get("FIGHTER"))
        try:
            external_id, source_url = _parse_identity(_required(row, "URL", line_number), "fighter")
            if external_id in tott:
                raise UFCStatsSourceError(f"duplicate TOTT identity: {external_id}")
            tott[external_id] = dict(row)
            urls.setdefault(external_id, source_url)
        except UFCStatsSourceError as exc:
            issues.append(SourceContentError(None, f"fighter TOTT line {line_number}: {exc}", fighter_name))

    records: list[FighterRecord] = []
    for external_id in sorted(urls):
        detail = details.get(external_id, {})
        tape = tott.get(external_id, {})
        first = _text(detail.get("FIRST"))
        last = _text(detail.get("LAST"))
        fallback_name = _text(tape.get("FIGHTER"))
        fighter_name = " ".join(part for part in (first, last) if part) or fallback_name
        try:
            if fighter_name is None:
                raise UFCStatsSourceError(f"fighter {external_id} has no display name")
            record = FighterRecord(
                external_id=external_id,
                source_url=urls[external_id],
                canonical_name=fighter_name,
                first_name=first,
                last_name=last,
                nickname=_text(detail.get("NICKNAME")),
                date_of_birth=parse_dob(tape.get("DOB")),
                height_inches=parse_height(tape.get("HEIGHT")),
                weight_lbs=parse_weight(tape.get("WEIGHT")),
                reach_inches=parse_reach(tape.get("REACH")),
                stance=_text(tape.get("STANCE")),
            )
            records.append(record)
        except (UFCStatsSourceError, ValueError) as exc:
            invalid_ids.add(external_id)
            issues.append(SourceContentError(None, f"fighter {external_id}: {exc}", fighter_name))
    return tuple(record for record in records if record.external_id not in invalid_ids)


def _parse_fights(
    source_dir: Path,
    events: tuple[EventRecord, ...],
    issues: list[SourceContentError] | None = None,
) -> tuple[FightRecord, ...]:
    issues = issues if issues is not None else []
    detail_fields = ("EVENT", "BOUT", "URL")
    result_fields = ("EVENT", "BOUT", "OUTCOME", "WEIGHTCLASS", "METHOD", "ROUND", "TIME", "TIME FORMAT", "REFEREE", "DETAILS", "URL")
    event_names = {event.name for event in events}
    details_by_id: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(_load_csv(source_dir / "ufc_fight_details.csv", detail_fields), 2):
        event_name = _text(row.get("EVENT"))
        try:
            event_name = _required(row, "EVENT", line_number)
            bout = _required(row, "BOUT", line_number)
            if _BOUT_RE.fullmatch(bout) is None:
                raise UFCStatsSourceError(f"invalid bout: {bout}")
            external_id, source_url = _parse_identity(_required(row, "URL", line_number), "fight")
            if external_id in details_by_id:
                raise UFCStatsSourceError(f"duplicate fight identity: {external_id}")
            row = dict(row)
            row["URL"] = source_url
            if event_name in event_names:
                details_by_id[external_id] = row
            else:
                issues.append(SourceContentError(event_name, f"fight detail line {line_number}: unknown event"))
        except UFCStatsSourceError as exc:
            issues.append(SourceContentError(event_name, f"fight detail line {line_number}: {exc}"))

    results_by_id: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(_load_csv(source_dir / "ufc_fight_results.csv", result_fields), 2):
        event_name = _text(row.get("EVENT"))
        try:
            event_name = _required(row, "EVENT", line_number)
            outcome = _required(row, "OUTCOME", line_number)
            round_text = _text(row.get("ROUND"))
            if round_text and not round_text.isdigit():
                raise UFCStatsSourceError(f"invalid result round: {round_text}")
            external_id, source_url = _parse_identity(_required(row, "URL", line_number), "fight")
            row = dict(row)
            row["URL"] = source_url
            row["OUTCOME"] = outcome
            if external_id not in results_by_id or event_name in event_names:
                results_by_id[external_id] = row
        except UFCStatsSourceError as exc:
            issues.append(SourceContentError(event_name, f"fight result line {line_number}: {exc}"))

    event_orders: dict[str, dict[str, int]] = defaultdict(dict)
    for external_id, detail in details_by_id.items():
        event_name = detail["EVENT"]
        event_orders[event_name].setdefault(external_id, len(event_orders[event_name]) + 1)

    records: list[FightRecord] = []
    for external_id, detail in details_by_id.items():
        event_name = detail["EVENT"]
        result = results_by_id.get(external_id)
        try:
            if result is None:
                raise UFCStatsSourceError(f"missing result for fight {external_id}")
            round_text = _text(result.get("ROUND"))
            records.append(FightRecord(
                event_name=event_name,
                bout=detail["BOUT"],
                fighter_a=_BOUT_RE.fullmatch(detail["BOUT"]).group(1).strip(),
                fighter_b=_BOUT_RE.fullmatch(detail["BOUT"]).group(2).strip(),
                source_url=detail["URL"],
                external_id=external_id,
                weight_class=_text(result.get("WEIGHTCLASS")),
                outcome=_required(result, "OUTCOME", 0),
                method=_text(result.get("METHOD")),
                result_round=int(round_text) if round_text else None,
                result_time=_text(result.get("TIME")),
                result_time_format=_text(result.get("TIME FORMAT")),
                referee=_text(result.get("REFEREE")),
                result_details=_text(result.get("DETAILS")),
                bout_order=event_orders[event_name][external_id],
            ))
        except (UFCStatsSourceError, AttributeError, ValueError) as exc:
            issues.append(SourceContentError(event_name, f"fight {external_id}: {exc}"))
    return tuple(sorted(records, key=lambda record: (record.event_name, record.bout_order)))


def _stat_pair(row: dict[str, str], field: str) -> tuple[int | None, int | None]:
    pair = parse_pair(row.get(field))
    return pair if pair is not None else (None, None)


def _parse_stats(source_dir: Path, issues: list[SourceContentError] | None = None) -> tuple[RoundStatRecord, ...]:
    issues = issues if issues is not None else []
    fields = ("EVENT", "BOUT", "ROUND", "FIGHTER", "KD", "SIG.STR.", "SIG.STR. %", "TOTAL STR.", "TD", "TD %", "SUB.ATT", "REV.", "CTRL", "HEAD", "BODY", "LEG", "DISTANCE", "CLINCH", "GROUND")
    records: list[RoundStatRecord] = []
    for line_number, row in enumerate(_load_csv(source_dir / "ufc_fight_stats.csv", fields), 2):
        event_name = _text(row.get("EVENT"))
        try:
            if all(_missing(row.get(field)) for field in fields[2:]):
                continue
            event_name = _required(row, "EVENT", line_number)
            bout = _required(row, "BOUT", line_number)
            round_text = _required(row, "ROUND", line_number)
            match = _ROUND_RE.fullmatch(round_text)
            if match is None:
                raise UFCStatsSourceError(f"line {line_number}: invalid round {round_text}")
            fighter = _required(row, "FIGHTER", line_number)
            pairs = {field: _stat_pair(row, field) for field in ("SIG.STR.", "TOTAL STR.", "TD", "HEAD", "BODY", "LEG", "DISTANCE", "CLINCH", "GROUND")}
            records.append(RoundStatRecord(event_name, bout, int(match.group(1)), fighter, _parse_number(row.get("KD")), *pairs["SIG.STR."], parse_percentage(row.get("SIG.STR. %")), *pairs["TOTAL STR."], *pairs["TD"], parse_percentage(row.get("TD %")), _parse_number(row.get("SUB.ATT")), _parse_number(row.get("REV.")), parse_control_time(row.get("CTRL")), *pairs["HEAD"], *pairs["BODY"], *pairs["LEG"], *pairs["DISTANCE"], *pairs["CLINCH"], *pairs["GROUND"]))
        except UFCStatsSourceError as exc:
            issues.append(SourceContentError(event_name, f"stat line {line_number}: {exc}"))
    return tuple(records)

def load_source(source_dir: str | Path) -> UFCStatsSource:
    source_dir = Path(source_dir)
    issues: list[SourceContentError] = []
    events = _parse_events(source_dir, issues)
    fighters = _parse_fighters(source_dir, issues)
    fights = _parse_fights(source_dir, events, issues)
    round_stats = _parse_stats(source_dir, issues)
    return UFCStatsSource(events, fighters, fights, round_stats, tuple(issues))
