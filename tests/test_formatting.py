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
    }
    leg.update(overrides)
    return leg


def test_format_leg_spread_home():
    text = formatting.format_leg(make_leg())
    assert "Texas -6.5" in text
    assert "(-110)" in text
    assert "Ohio State @ Texas" in text


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
