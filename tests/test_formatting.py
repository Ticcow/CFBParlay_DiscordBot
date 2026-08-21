from bot.parlays import formatting


def test_format_price_positive_gets_plus_sign():
    assert formatting.format_price(200) == "+200"


def test_format_price_negative_unchanged():
    assert formatting.format_price(-110) == "-110"


def test_format_price_none_is_unknown():
    assert formatting.format_price(None) == "?"


def make_leg(**overrides):
    leg = {
        "leg_number": 1,
        "market": "spread",
        "selection": "home",
        "line_value": -6.5,
        "price_american": -110,
        "home_team": "Texas",
        "away_team": "Ohio State",
        "result": "pending",
    }
    leg.update(overrides)
    return leg


def test_format_leg_spread_home():
    text = formatting.format_leg(make_leg())
    assert "Texas -6.5" in text
    assert "(-110)" in text
    assert "Ohio State vs Texas" in text


def test_format_leg_shows_pending_marker_by_default():
    assert formatting.format_leg(make_leg()).startswith("⏳")


def test_format_leg_shows_win_marker():
    assert formatting.format_leg(make_leg(result="win")).startswith("✅")


def test_format_leg_shows_loss_marker():
    assert formatting.format_leg(make_leg(result="loss")).startswith("❌")


def test_format_leg_shows_push_marker():
    assert formatting.format_leg(make_leg(result="push")).startswith("➖")


def test_format_leg_spread_away():
    text = formatting.format_leg(make_leg(selection="away", line_value=6.5))
    assert "Ohio State +6.5" in text


def test_format_leg_moneyline():
    text = formatting.format_leg(
        make_leg(market="moneyline", selection="home", line_value=None, price_american=-250)
    )
    assert "Texas ML (-250)" in text


def test_format_leg_total_over():
    text = formatting.format_leg(
        make_leg(market="total", selection="over", line_value=54.5, price_american=-110)
    )
    assert "Over 54.5" in text


def test_format_leg_total_under():
    text = formatting.format_leg(
        make_leg(market="total", selection="under", line_value=54.5, price_american=-105)
    )
    assert "Under 54.5 (-105)" in text


def make_parlay(**overrides):
    parlay = {
        "status": "submitted",
        "result": None,
        "potential_payout_dollars": 277.78,
        "actual_payout_dollars": None,
    }
    parlay.update(overrides)
    return parlay


def test_format_payout_and_status_shows_potential_while_pending():
    payout_text, status_label = formatting.format_payout_and_status(make_parlay(status="locked"))
    assert payout_text == "$277.78 potential"
    assert status_label == "locked"


def test_format_payout_and_status_shows_actual_payout_and_result_once_graded():
    parlay = make_parlay(status="graded", result="win", actual_payout_dollars=277.78)
    payout_text, status_label = formatting.format_payout_and_status(parlay)
    assert payout_text == "$277.78 payout"
    assert status_label == "WIN"


def test_format_payout_and_status_handles_missing_potential_payout():
    payout_text, _ = formatting.format_payout_and_status(
        make_parlay(status="submitted", potential_payout_dollars=None)
    )
    assert payout_text == "- potential"


def make_game():
    return {"home_team": "Texas", "away_team": "Ohio State"}


def test_format_selection_button_label_spread():
    label = formatting.format_selection_button_label(make_game(), "spread", "home", -6.5, -110)
    assert label == "Texas -6.5 (-110)"


def test_format_selection_button_label_moneyline():
    label = formatting.format_selection_button_label(make_game(), "moneyline", "away", None, 200)
    assert label == "Ohio State (+200)"


def test_format_selection_button_label_total():
    label = formatting.format_selection_button_label(make_game(), "total", "under", 54.5, -105)
    assert label == "Under 54.5 (-105)"


def make_snapshot(**overrides):
    snapshot = {
        "spread_home": -6.5, "spread_price_home": -110, "spread_price_away": -105,
        "moneyline_home": -250, "moneyline_away": 200,
        "total_points": 54.5, "over_price": -110, "under_price": -105,
    }
    snapshot.update(overrides)
    return snapshot


def test_format_market_lines_spread_shows_both_sides():
    text = formatting.format_market_lines(make_game(), make_snapshot(), "spread")
    assert text == "Texas -6.5 (-110)\nOhio State +6.5 (-105)"


def test_format_market_lines_moneyline_shows_both_sides():
    text = formatting.format_market_lines(make_game(), make_snapshot(), "moneyline")
    assert text == "Texas (-250)\nOhio State (+200)"


def test_format_market_lines_total_shows_both_sides():
    text = formatting.format_market_lines(make_game(), make_snapshot(), "total")
    assert text == "Over 54.5 (-110)\nUnder 54.5 (-105)"


def test_format_market_lines_none_when_no_snapshot():
    assert formatting.format_market_lines(make_game(), None, "spread") is None


def test_format_market_lines_none_when_market_not_cached():
    snapshot = make_snapshot(spread_home=None, spread_price_home=None, spread_price_away=None)
    assert formatting.format_market_lines(make_game(), snapshot, "spread") is None
