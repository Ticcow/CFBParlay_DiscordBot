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
