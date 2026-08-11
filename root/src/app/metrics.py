from __future__ import annotations

from pathlib import Path

from .db import connect


def dashboard_metrics(database_path: str | Path) -> dict:
    with connect(database_path) as connection:
        settings = {
            row["key"]: int(row["value"])
            for row in connection.execute("SELECT key, value FROM settings")
        }
        wagers = connection.execute(
            """
            SELECT id, stake_cents, profit_cents, status, settled_at
            FROM wagers
            WHERE status IN ('won', 'lost', 'push')
            ORDER BY settled_at IS NULL, settled_at, id
            """
        ).fetchall()
        predictions = connection.execute(
            """
            SELECT p.picked_fighter, f.status, f.winner
            FROM predictions p
            JOIN fights f ON f.id = p.fight_id
            WHERE f.status IN ('completed', 'draw', 'no_contest')
            """
        ).fetchall()
        cards_tracked = connection.execute(
            "SELECT COUNT(*) FROM events WHERE status = 'completed'"
        ).fetchone()[0]

    total_wagered = sum(row["stake_cents"] for row in wagers)
    gross_winnings = sum(max(row["profit_cents"] or 0, 0) for row in wagers)
    net_profit = sum(row["profit_cents"] or 0 for row in wagers)
    wins = sum(
        row["status"] == "completed" and row["picked_fighter"] == row["winner"]
        for row in predictions
    )
    losses = sum(
        row["status"] == "completed" and row["picked_fighter"] != row["winner"]
        for row in predictions
    )
    pushes = sum(row["status"] in {"draw", "no_contest"} for row in predictions)

    bankroll = settings["starting_bankroll_cents"]
    peak = bankroll
    max_drawdown = 0
    for wager in wagers:
        bankroll += wager["profit_cents"] or 0
        peak = max(peak, bankroll)
        max_drawdown = max(max_drawdown, peak - bankroll)

    return {
        "starting_bankroll_cents": settings["starting_bankroll_cents"],
        "default_stake_cents": settings["default_stake_cents"],
        "current_bankroll_cents": bankroll,
        "total_wagered_cents": total_wagered,
        "gross_winnings_cents": gross_winnings,
        "net_profit_cents": net_profit,
        "roi": net_profit / total_wagered if total_wagered else 0.0,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "accuracy": wins / (wins + losses) if wins + losses else 0.0,
        "cards_tracked": cards_tracked,
        "peak_bankroll_cents": peak,
        "maximum_drawdown_cents": max_drawdown,
    }
