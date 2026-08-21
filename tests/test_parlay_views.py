from bot.commands.parlay_views import _format_ranked_list, _matchup_label, _team_label


def make_game(home_team="Georgia", away_team="Alabama", start_time_utc="2026-08-29T19:00:00Z"):
    return {"home_team": home_team, "away_team": away_team, "start_time_utc": start_time_utc}


def test_team_label_prefixes_rank_only_when_present():
    assert _team_label("Georgia", 1) == "#1 Georgia"
    assert _team_label("Marshall", None) == "Marshall"


def test_matchup_label_puts_home_first_and_attaches_rank_to_the_ranked_side():
    game = make_game(home_team="Georgia", away_team="Marshall")

    assert _matchup_label(1, None, game) == "#1 Georgia vs Marshall"


def test_matchup_label_attaches_rank_to_away_side_when_away_is_ranked():
    game = make_game(home_team="Purdue", away_team="Ohio State")

    assert _matchup_label(None, 2, game) == "Purdue vs #2 Ohio State"


def test_matchup_label_shows_both_ranks_when_both_teams_are_ranked():
    game = make_game(home_team="Georgia", away_team="Alabama")

    assert _matchup_label(1, 5, game) == "#1 Georgia vs #5 Alabama"


def test_format_ranked_list_returns_placeholder_when_empty():
    assert _format_ranked_list([]) == "No ranked teams have an available game this week."


def test_format_ranked_list_formats_each_matchup_home_first():
    ranked_games = [(1, 1, None, make_game(home_team="Georgia", away_team="Marshall"))]

    result = _format_ranked_list(ranked_games)

    assert result.startswith("**#1 Georgia vs Marshall**")
