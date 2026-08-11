from __future__ import annotations

from pathlib import Path

from ..db import connect, transaction, utc_now
from ..payouts import calculate_profit_cents
from .events import ValidationError


def settle_event(
    database_path: str | Path,
    event_id: int,
    results: dict[int, str],
) -> None:
    with connect(database_path) as connection:
        with transaction(connection):
            fights = connection.execute(
                "SELECT id, fighter_a, fighter_b FROM fights WHERE event_id = ? ORDER BY bout_order, id",
                (event_id,),
            ).fetchall()
            if not fights:
                raise ValidationError("an event needs at least one fight before settlement")

            submitted_ids = set(results)
            fight_ids = {row["id"] for row in fights}
            if submitted_ids != fight_ids:
                raise ValidationError("select a result for every fight")

            settled_at = utc_now()
            for fight in fights:
                result = results[fight["id"]]
                if result in {"canceled", "draw", "no_contest"}:
                    status = result
                    winner = None
                    wager_outcome = "void" if result == "canceled" else "push"
                elif result in {fight["fighter_a"], fight["fighter_b"]}:
                    status = "completed"
                    winner = result
                    wager_outcome = None
                else:
                    raise ValidationError(f"invalid result for {fight['fighter_a']} vs {fight['fighter_b']}")

                connection.execute(
                    "UPDATE fights SET status = ?, winner = ? WHERE id = ?",
                    (status, winner, fight["id"]),
                )
                wagers = connection.execute(
                    """
                    SELECT w.id, w.moneyline, w.stake_cents, p.picked_fighter
                    FROM wagers w
                    JOIN predictions p ON p.id = w.prediction_id
                    WHERE p.fight_id = ?
                    """,
                    (fight["id"],),
                ).fetchall()
                for wager in wagers:
                    payout_outcome = wager_outcome or (
                        "win" if wager["picked_fighter"] == winner else "loss"
                    )
                    wager_status = {
                        "win": "won",
                        "loss": "lost",
                        "push": "push",
                        "void": "void",
                    }[payout_outcome]
                    profit_cents = calculate_profit_cents(
                        wager["stake_cents"], wager["moneyline"], payout_outcome
                    )
                    connection.execute(
                        """
                        UPDATE wagers
                        SET status = ?, profit_cents = ?, settled_at = ?
                        WHERE id = ?
                        """,
                        (wager_status, profit_cents, settled_at, wager["id"]),
                    )

            connection.execute(
                "UPDATE events SET status = 'completed' WHERE id = ?", (event_id,)
            )
