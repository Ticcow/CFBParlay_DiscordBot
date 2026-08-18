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
