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
            event = connection.execute(
                "SELECT status FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if event is None:
                raise ValidationError("event not found")
            fights = connection.execute(
                "SELECT id, fighter_a, fighter_b, status, winner FROM fights WHERE event_id = ? ORDER BY bout_order, id",
                (event_id,),
            ).fetchall()
            if not fights:
                raise ValidationError("an event needs at least one fight before settlement")

            submitted_ids = set(results)
            fight_ids = {row["id"] for row in fights}
            if submitted_ids != fight_ids:
                raise ValidationError("select a result for every fight")

            desired_fights: dict[int, tuple[str, str | None]] = {}
            desired_wagers: dict[int, tuple[str, int]] = {}
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

                desired_fights[fight["id"]] = (status, winner)
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
                    desired_wagers[wager["id"]] = (wager_status, profit_cents)

            current_wagers = connection.execute(
                """
                SELECT w.id, w.status, w.profit_cents, w.settled_at
                FROM wagers w
                JOIN predictions p ON p.id = w.prediction_id
                JOIN fights f ON f.id = p.fight_id
                WHERE f.event_id = ?
                """,
                (event_id,),
            ).fetchall()
            current_wagers_by_id = {wager["id"]: wager for wager in current_wagers}
            fights_match = all(
                fight["status"] == desired_fights[fight["id"]][0]
                and fight["winner"] == desired_fights[fight["id"]][1]
                for fight in fights
            )
            wagers_match = (
                {wager["id"] for wager in current_wagers} == set(desired_wagers)
                and all(
                    wager["status"] == desired_wagers[wager["id"]][0]
                    and wager["profit_cents"] == desired_wagers[wager["id"]][1]
                    and wager["settled_at"] is not None
                    for wager in current_wagers
                )
            )
            if event["status"] == "completed" and fights_match and wagers_match:
                return

            settled_at = utc_now()
            for fight_id, (status, winner) in desired_fights.items():
                fight = next(row for row in fights if row["id"] == fight_id)
                if fight["status"] != status or fight["winner"] != winner:
                    connection.execute(
                        "UPDATE fights SET status = ?, winner = ? WHERE id = ?",
                        (status, winner, fight_id),
                    )
            for wager_id, (wager_status, profit_cents) in desired_wagers.items():
                wager = current_wagers_by_id[wager_id]
                if (
                    wager["status"] == wager_status
                    and wager["profit_cents"] == profit_cents
                    and wager["settled_at"] is not None
                ):
                    continue
                wager_settled_at = (
                    settled_at
                    if wager["status"] == "pending"
                    else wager["settled_at"] or settled_at
                )
                connection.execute(
                    """
                    UPDATE wagers
                    SET status = ?, profit_cents = ?, settled_at = ?
                    WHERE id = ?
                    """,
                    (wager_status, profit_cents, wager_settled_at, wager_id),
                )

            connection.execute(
                "UPDATE events SET status = 'completed' WHERE id = ?", (event_id,)
            )
