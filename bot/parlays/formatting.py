from decimal import ROUND_HALF_UP, Decimal

from bot.parlays import selections

LEG_RESULT_MARKERS = {"win": "✅", "loss": "❌", "push": "➖", "pending": "⏳"}


def format_dollars(amount: float) -> str:
    """Whole dollars with thousands separators, e.g. $14,114 or -$150 - the
    bot tracks cents internally but never shows them. Rounds halves up
    ($2.50 -> $3) rather than Python's default round-half-to-even."""
    whole = int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"-${-whole:,}" if whole < 0 else f"${whole:,}"


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


def format_payout_and_status(parlay) -> tuple[str, str]:
    """Payout text and a status label for a parlay - actual payout + WIN/LOSS/PUSH
    once graded, potential payout + the raw status (submitted/locked) while
    still pending. Shared by the status panel and /parlays so both agree."""
    if parlay["status"] == "graded":
        return f"{format_dollars(parlay['actual_payout_dollars'])} payout", parlay["result"].upper()
    potential = (
        f"{format_dollars(parlay['potential_payout_dollars'])}"
        if parlay["potential_payout_dollars"] is not None
        else "-"
    )
    return f"{potential} potential", parlay["status"]


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
