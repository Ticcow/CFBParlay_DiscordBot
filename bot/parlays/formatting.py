from bot.parlays import selections

LEG_RESULT_MARKERS = {"win": "✅", "loss": "❌", "push": "➖", "pending": "⏳"}


def format_price(price: int | None) -> str:
    if price is None:
        return "?"
    return f"+{price}" if price > 0 else str(price)


def format_leg(leg) -> str:
    marker = LEG_RESULT_MARKERS.get(leg["result"], "⏳")
    matchup = f"{leg['away_team']} vs {leg['home_team']}"
    if leg["market"] == "spread":
        team = leg["home_team"] if leg["selection"] == "home" else leg["away_team"]
        return (
            f"{marker} {leg['leg_number']}. {team} {leg['line_value']:+g} "
            f"({format_price(leg['price_american'])}) — {matchup}"
        )
    if leg["market"] == "moneyline":
        team = leg["home_team"] if leg["selection"] == "home" else leg["away_team"]
        return f"{marker} {leg['leg_number']}. {team} ML ({format_price(leg['price_american'])}) — {matchup}"
    side = "Over" if leg["selection"] == "over" else "Under"
    return (
        f"{marker} {leg['leg_number']}. {side} {leg['line_value']:g} "
        f"({format_price(leg['price_american'])}) — {matchup}"
    )


def format_selection_button_label(
    game, market: str, selection: str, line_value: float | None, price: int | None
) -> str:
    price_str = format_price(price)
    if market == "moneyline":
        team = game["home_team"] if selection == "home" else game["away_team"]
        return f"{team} ({price_str})"
    if market == "total":
        side = "Over" if selection == "over" else "Under"
        return f"{side} {line_value:g} ({price_str})"
    team = game["home_team"] if selection == "home" else game["away_team"]
    return f"{team} {line_value:+g} ({price_str})"


def format_market_lines(game, snapshot, market: str) -> str | None:
    """Both sides of a cached market, one per line - e.g. for 'spread':
    'Texas -6.5 (-110)\\nOhio State +6.5 (-105)'. None if that market isn't
    cached for this game, so a caller can skip showing it entirely."""
    if snapshot is None:
        return None
    lines = []
    for selection in selections.selection_options(market):
        line_value, price = selections.resolve_selection(snapshot, market, selection)
        if price is None:
            return None
        lines.append(format_selection_button_label(game, market, selection, line_value, price))
    return "\n".join(lines)
