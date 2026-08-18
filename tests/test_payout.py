import pytest

from bot.parlays import payout


def test_american_to_decimal_positive_price():
    assert payout.american_to_decimal(200) == pytest.approx(3.0)


def test_american_to_decimal_negative_price():
    assert payout.american_to_decimal(-110) == pytest.approx(1.9090909, rel=1e-4)


def test_combined_decimal_odds_multiplies_across_legs():
    combined = payout.combined_decimal_odds([-110, -110, 200])
    expected = payout.american_to_decimal(-110) * payout.american_to_decimal(-110) * payout.american_to_decimal(200)
    assert combined == pytest.approx(expected)


def test_potential_payout_single_even_money_leg():
    # -100 is even money: decimal odds 2.0, so a $100 wager pays back $200 total
    assert payout.potential_payout(100, [-100]) == pytest.approx(200.0)


def test_potential_payout_three_leg_parlay():
    result = payout.potential_payout(50, [-110, -110, -110])
    expected = round(50 * payout.american_to_decimal(-110) ** 3, 2)
    assert result == pytest.approx(expected)


def test_potential_payout_rounds_to_cents():
    result = payout.potential_payout(33.33, [-110])
    assert result == round(result, 2)
