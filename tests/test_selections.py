from bot.parlays import selections


def make_snapshot(**overrides):
    snapshot = {
        "spread_home": -6.5, "spread_price_home": -110, "spread_price_away": -105,
        "moneyline_home": -250, "moneyline_away": 200,
        "total_points": 54.5, "over_price": -110, "under_price": -105,
    }
    snapshot.update(overrides)
    return snapshot


def test_selection_options_total_is_over_under():
    assert selections.selection_options("total") == ("over", "under")


def test_selection_options_spread_and_moneyline_are_home_away():
    assert selections.selection_options("spread") == ("home", "away")
    assert selections.selection_options("moneyline") == ("home", "away")


def test_resolve_selection_spread_home():
    line, price = selections.resolve_selection(make_snapshot(), "spread", "home")
    assert line == -6.5
    assert price == -110


def test_resolve_selection_spread_away_is_negated_line_with_its_own_price():
    line, price = selections.resolve_selection(make_snapshot(), "spread", "away")
    assert line == 6.5
    assert price == -105


def test_resolve_selection_moneyline_away():
    line, price = selections.resolve_selection(make_snapshot(), "moneyline", "away")
    assert line is None
    assert price == 200


def test_resolve_selection_total_over():
    line, price = selections.resolve_selection(make_snapshot(), "total", "over")
    assert line == 54.5
    assert price == -110


def test_resolve_selection_unavailable_market_returns_none_price():
    snapshot = make_snapshot(spread_home=None, spread_price_home=None)
    line, price = selections.resolve_selection(snapshot, "spread", "home")
    assert price is None


def test_resolve_selection_unknown_market_returns_none_none():
    assert selections.resolve_selection(make_snapshot(), "bogus", "home") == (None, None)
