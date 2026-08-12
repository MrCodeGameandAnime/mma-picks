from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from ..db import connect


@dataclass(frozen=True)
class AnalyticsFilters:
    analyst: str | None = None
    gender: str | None = None
    weight_class: str | None = None
    card_section: str | None = None
    confidence_band: str | None = None
    confidence_min: int | None = None
    confidence_max: int | None = None
    odds_min: int | None = None
    odds_max: int | None = None
    favorite: str | None = None
    result: str | None = None
    date_from: str | None = None
    date_to: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _optional_int(value: object) -> int | None:
    try:
        text = str(value).strip()
        return int(text) if text else None
    except (TypeError, ValueError):
        return None


def filters_from_mapping(values: Mapping[str, object]) -> AnalyticsFilters:
    favorite = str(values.get("favorite", "")).strip().lower() or None
    if favorite not in {None, "favorite", "underdog"}:
        favorite = None

    result = str(values.get("result", "")).strip().lower() or None
    result_aliases = {"win": "won", "loss": "lost"}
    result = result_aliases.get(result, result)
    if result not in {None, "won", "lost", "push", "pending"}:
        result = None

    confidence_band = str(values.get("confidence_band", "")).strip() or None
    if confidence_band not in {None, "0-49", "50-74", "75-100"}:
        confidence_band = None

    return AnalyticsFilters(
        analyst=str(values.get("analyst", "")).strip() or None,
        gender=str(values.get("gender", "")).strip() or None,
        weight_class=str(values.get("weight_class", "")).strip() or None,
        card_section=str(values.get("card_section", "")).strip() or None,
        confidence_band=confidence_band,
        confidence_min=_optional_int(values.get("confidence_min")),
        confidence_max=_optional_int(values.get("confidence_max")),
        odds_min=_optional_int(values.get("odds_min")),
        odds_max=_optional_int(values.get("odds_max")),
        favorite=favorite,
        result=result,
        date_from=str(values.get("date_from", "")).strip() or None,
        date_to=str(values.get("date_to", "")).strip() or None,
    )


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "prediction_id",
            "fight_id",
            "event_id",
            "event_name",
            "event_date",
            "analyst_id",
            "analyst_slug",
            "analyst_name",
            "fighter_a",
            "fighter_b",
            "weight_class",
            "gender",
            "card_section",
            "bout_order",
            "fight_status",
            "winner",
            "picked_fighter",
            "confidence",
            "wager_id",
            "stake_cents",
            "moneyline",
            "wager_status",
            "profit_cents",
            "placed_at",
            "settled_at",
            "prediction_result",
            "confidence_band",
            "favorite_status",
        ]
    )


def load_prediction_frame(database_path: str | Path) -> pd.DataFrame:
    """Load the normalized prediction/wager grain used by all Gate 4 analytics."""
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                p.id AS prediction_id,
                f.id AS fight_id,
                f.event_id,
                e.name AS event_name,
                e.event_date,
                p.analyst_id,
                a.slug AS analyst_slug,
                a.name AS analyst_name,
                f.fighter_a,
                f.fighter_b,
                f.weight_class,
                f.gender,
                f.card_section,
                f.bout_order,
                f.status AS fight_status,
                f.winner,
                p.picked_fighter,
                p.confidence,
                w.id AS wager_id,
                w.stake_cents,
                w.moneyline,
                w.status AS wager_status,
                w.profit_cents,
                w.placed_at,
                w.settled_at
            FROM predictions p
            JOIN fights f ON f.id = p.fight_id
            JOIN events e ON e.id = f.event_id
            JOIN analysts a ON a.id = p.analyst_id
            LEFT JOIN wagers w ON w.prediction_id = p.id
            ORDER BY e.event_date, f.bout_order, p.id
            """
        ).fetchall()

    if not rows:
        return _empty_frame()

    frame = pd.DataFrame([dict(row) for row in rows])
    frame["prediction_result"] = "pending"
    completed = frame["fight_status"].eq("completed")
    pushes = frame["fight_status"].isin(["draw", "no_contest"])
    canceled = frame["fight_status"].eq("canceled")
    frame.loc[completed & frame["picked_fighter"].eq(frame["winner"]), "prediction_result"] = "won"
    frame.loc[completed & ~frame["picked_fighter"].eq(frame["winner"]), "prediction_result"] = "lost"
    frame.loc[pushes, "prediction_result"] = "push"
    frame.loc[canceled, "prediction_result"] = "canceled"

    frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce")
    frame["moneyline"] = pd.to_numeric(frame["moneyline"], errors="coerce")
    frame["stake_cents"] = pd.to_numeric(frame["stake_cents"], errors="coerce")
    frame["profit_cents"] = pd.to_numeric(frame["profit_cents"], errors="coerce").fillna(0).astype(int)
    frame["confidence_band"] = pd.cut(
        frame["confidence"],
        bins=[-1, 49, 74, 100],
        labels=["0-49", "50-74", "75-100"],
    ).astype("string")
    frame["favorite_status"] = pd.NA
    frame.loc[frame["moneyline"] < 0, "favorite_status"] = "favorite"
    frame.loc[frame["moneyline"] > 0, "favorite_status"] = "underdog"
    return frame


def apply_filters(frame: pd.DataFrame, filters: AnalyticsFilters) -> pd.DataFrame:
    filtered = frame.copy()
    equality_filters = {
        "analyst_slug": filters.analyst,
        "gender": filters.gender,
        "weight_class": filters.weight_class,
        "card_section": filters.card_section,
        "confidence_band": filters.confidence_band,
        "favorite_status": filters.favorite,
    }
    for column, value in equality_filters.items():
        if value is not None and column in filtered:
            filtered = filtered[filtered[column].eq(value)]
    if filters.confidence_min is not None:
        filtered = filtered[filtered["confidence"].ge(filters.confidence_min)]
    if filters.confidence_max is not None:
        filtered = filtered[filtered["confidence"].le(filters.confidence_max)]
    if filters.odds_min is not None:
        filtered = filtered[filtered["moneyline"].ge(filters.odds_min)]
    if filters.odds_max is not None:
        filtered = filtered[filtered["moneyline"].le(filters.odds_max)]
    if filters.result is not None:
        filtered = filtered[filtered["prediction_result"].eq(filters.result)]
    if filters.date_from is not None:
        filtered = filtered[filtered["event_date"].ge(filters.date_from)]
    if filters.date_to is not None:
        filtered = filtered[filtered["event_date"].le(filters.date_to)]
    return filtered.reset_index(drop=True)


def _summary_for_frame(frame: pd.DataFrame) -> dict[str, object]:
    settled_predictions = frame[frame["prediction_result"].isin(["won", "lost", "push"])]
    wagers = frame[frame["wager_status"].isin(["won", "lost", "push"])]
    wins = int(settled_predictions["prediction_result"].eq("won").sum())
    losses = int(settled_predictions["prediction_result"].eq("lost").sum())
    pushes = int(settled_predictions["prediction_result"].eq("push").sum())
    total_wagered = int(wagers["stake_cents"].fillna(0).sum())
    net_profit = int(wagers["profit_cents"].fillna(0).sum())
    return {
        "sample_size": int(len(settled_predictions)),
        "wager_sample_size": int(len(wagers)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "accuracy": wins / (wins + losses) if wins + losses else 0.0,
        "total_wagered_cents": total_wagered,
        "net_profit_cents": net_profit,
        "gross_winnings_cents": int(wagers["profit_cents"].clip(lower=0).sum()),
        "roi": net_profit / total_wagered if total_wagered else 0.0,
    }


def summarize_performance(frame: pd.DataFrame) -> dict[str, object]:
    """Return accuracy, ROI, and sample sizes for a filtered frame."""
    return _summary_for_frame(frame)


def grouped_performance(frame: pd.DataFrame, dimension: str) -> list[dict[str, object]]:
    """Summarize a filtered frame by one supported analytics dimension."""
    supported = {
        "analyst_slug",
        "gender",
        "weight_class",
        "card_section",
        "confidence_band",
        "favorite_status",
    }
    if dimension not in supported:
        raise ValueError(f"unsupported analytics dimension: {dimension}")
    if frame.empty:
        return []

    results: list[dict[str, object]] = []
    for key, group in frame.groupby(dimension, dropna=False, observed=True):
        label = "Unknown" if pd.isna(key) or str(key).strip() == "" else str(key)
        result = {"group": label, **_summary_for_frame(group)}
        if dimension == "analyst_slug":
            result["analyst_name"] = group["analyst_name"].dropna().iloc[0] if group["analyst_name"].notna().any() else label
        results.append(result)
    return sorted(results, key=lambda item: str(item["group"]).lower())


def bankroll_history(
    frame: pd.DataFrame,
    starting_bankroll_cents: int,
) -> list[dict[str, object]]:
    """Build chronological bankroll observations from settled, non-void wagers."""
    wagers = frame[frame["wager_status"].isin(["won", "lost", "push"])].copy()
    if wagers.empty:
        return []
    wagers = wagers.sort_values(["settled_at", "wager_id"], na_position="last")
    bankroll = int(starting_bankroll_cents)
    peak = bankroll
    history: list[dict[str, object]] = []
    for row in wagers.itertuples(index=False):
        bankroll += int(row.profit_cents or 0)
        peak = max(peak, bankroll)
        history.append(
            {
                "wager_id": int(row.wager_id),
                "event_name": row.event_name,
                "event_date": row.event_date,
                "settled_at": row.settled_at,
                "profit_cents": int(row.profit_cents or 0),
                "bankroll_cents": bankroll,
                "peak_bankroll_cents": peak,
                "drawdown_cents": peak - bankroll,
            }
        )
    return history


def analytics_report(
    database_path: str | Path,
    filters: AnalyticsFilters | None = None,
) -> dict[str, object]:
    filters = filters or AnalyticsFilters()
    frame = load_prediction_frame(database_path)
    filtered = apply_filters(frame, filters)
    with connect(database_path) as connection:
        settings = {
            row["key"]: int(row["value"])
            for row in connection.execute("SELECT key, value FROM settings")
        }
    summary = _summary_for_frame(filtered)
    history = bankroll_history(filtered, settings["starting_bankroll_cents"])
    starting_bankroll = settings["starting_bankroll_cents"]
    peak = max(
        [starting_bankroll, *[item["peak_bankroll_cents"] for item in history]]
    )
    drawdown = max([0, *[item["drawdown_cents"] for item in history]])
    current_bankroll = history[-1]["bankroll_cents"] if history else starting_bankroll
    return {
        "filters": filters.as_dict(),
        "summary": {
            **summary,
            "starting_bankroll_cents": starting_bankroll,
            "current_bankroll_cents": current_bankroll,
            "peak_bankroll_cents": peak,
            "maximum_drawdown_cents": drawdown,
        },
        "by_analyst": grouped_performance(filtered, "analyst_slug"),
        "by_gender": grouped_performance(filtered, "gender"),
        "by_weight_class": grouped_performance(filtered, "weight_class"),
        "by_card_section": grouped_performance(filtered, "card_section"),
        "by_confidence_band": grouped_performance(filtered, "confidence_band"),
        "by_favorite_status": grouped_performance(filtered, "favorite_status"),
        "bankroll_history": history,
    }
