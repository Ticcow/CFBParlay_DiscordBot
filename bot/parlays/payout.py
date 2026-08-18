def american_to_decimal(price: int) -> float:
    if price > 0:
        return 1 + price / 100
    return 1 + 100 / abs(price)


def combined_decimal_odds(prices: list[int]) -> float:
    result = 1.0
    for price in prices:
        result *= american_to_decimal(price)
    return result


def potential_payout(wager_dollars: float, prices: list[int]) -> float:
    return round(wager_dollars * combined_decimal_odds(prices), 2)


def wager_presets(balance: float) -> list[tuple[str, float]]:
    """Quick-pick wager amounts for a given bankroll: fixed amounts under the
    balance, plus an "All In" option for the exact remaining balance."""
    fixed_amounts = [50.0, 100.0, 250.0, 500.0]
    presets = [(f"${amount:g}", amount) for amount in fixed_amounts if amount < balance]
    if balance > 0:
        presets.append(("All In", round(balance, 2)))
    return presets
