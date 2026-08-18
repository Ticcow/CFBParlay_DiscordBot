def selection_options(market: str) -> tuple[str, str]:
    return ("over", "under") if market == "total" else ("home", "away")


def resolve_selection(snapshot, market: str, selection: str):
    """Returns (line_value, price_american) for a market+selection against a
    cached odds snapshot, or (None, None) if that combination isn't available."""
    if market == "spread":
        if selection == "home":
            return snapshot["spread_home"], snapshot["spread_price_home"]
        if selection == "away":
            home_spread = snapshot["spread_home"]
            away_spread = -home_spread if home_spread is not None else None
            return away_spread, snapshot["spread_price_away"]
    elif market == "moneyline":
        if selection == "home":
            return None, snapshot["moneyline_home"]
        if selection == "away":
            return None, snapshot["moneyline_away"]
    elif market == "total":
        if selection == "over":
            return snapshot["total_points"], snapshot["over_price"]
        if selection == "under":
            return snapshot["total_points"], snapshot["under_price"]
    return None, None
