def format_price(price: int | None) -> str:
    if price is None:
        return "?"
    return f"+{price}" if price > 0 else str(price)


def format_leg(leg) -> str:
    matchup = f"{leg['away_team']} @ {leg['home_team']}"
    if leg["market"] == "spread":
        team = leg["home_team"] if leg["selection"] == "home" else leg["away_team"]
        return (
            f"{leg['leg_number']}. {team} {leg['line_value']:+g} "
            f"({format_price(leg['price_american'])}) — {matchup}"
        )
    if leg["market"] == "moneyline":
        team = leg["home_team"] if leg["selection"] == "home" else leg["away_team"]
        return f"{leg['leg_number']}. {team} ML ({format_price(leg['price_american'])}) — {matchup}"
    side = "Over" if leg["selection"] == "over" else "Under"
    return (
        f"{leg['leg_number']}. {side} {leg['line_value']:g} "
        f"({format_price(leg['price_american'])}) — {matchup}"
    )
