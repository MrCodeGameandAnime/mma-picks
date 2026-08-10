from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


VALID_OUTCOMES = frozenset({"win", "loss", "push", "void"})


def _rounded_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_profit_cents(
    stake_cents: int,
    moneyline: int,
    outcome: str,
) -> int:
    if stake_cents <= 0:
        raise ValueError("stake_cents must be greater than zero")
    if moneyline == 0 or (-100 < moneyline < 100):
        raise ValueError("moneyline must be at least +100 or at most -100")
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"unsupported outcome: {outcome}")

    if outcome in {"push", "void"}:
        return 0
    if outcome == "loss":
        return -stake_cents

    stake = Decimal(stake_cents)
    odds = Decimal(moneyline)
    if moneyline > 0:
        return _rounded_cents(stake * odds / Decimal(100))
    return _rounded_cents(stake * Decimal(100) / abs(odds))
