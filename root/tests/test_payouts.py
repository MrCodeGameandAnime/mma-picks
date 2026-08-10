import pytest

from src.app.payouts import calculate_profit_cents


def test_positive_moneyline_profit():
    assert calculate_profit_cents(50, 115, "win") == 58


def test_negative_moneyline_profit():
    assert calculate_profit_cents(50, -140, "win") == 36


def test_loss_returns_negative_stake():
    assert calculate_profit_cents(50, 115, "loss") == -50


@pytest.mark.parametrize("outcome", ["push", "void"])
def test_push_and_void_have_no_profit(outcome):
    assert calculate_profit_cents(50, 115, outcome) == 0


def test_invalid_moneyline_is_rejected():
    with pytest.raises(ValueError):
        calculate_profit_cents(50, 0, "win")


def test_invalid_outcome_is_rejected():
    with pytest.raises(ValueError):
        calculate_profit_cents(50, 115, "pending")
