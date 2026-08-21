from bot.parlays import zingers


def test_get_zinger_returns_none_for_unknown_team():
    assert zingers.get_zinger("Rice", "Alice") is None


def test_get_zinger_returns_none_for_none_team():
    assert zingers.get_zinger(None, "Alice") is None


def test_get_zinger_formats_username_into_the_line():
    result = zingers.get_zinger("Purdue", "Alice", choice_fn=lambda options: options[0])
    assert result == "That's a bold strategy, Alice — betting on Purdue."


def test_get_zinger_is_case_insensitive():
    result = zingers.get_zinger("purdue", "Alice", choice_fn=lambda options: options[0])
    assert result is not None
    assert "Alice" in result


def test_get_zinger_ucf_and_central_florida_share_the_same_jokes():
    ucf = zingers.get_zinger("UCF", "Bob", choice_fn=lambda options: options[0])
    central_florida = zingers.get_zinger("Central Florida", "Bob", choice_fn=lambda options: options[0])
    assert ucf == central_florida


def test_get_zinger_covers_every_advertised_team_with_multiple_lines():
    for team in ("Purdue", "Ohio State", "Indiana", "UCF", "Oklahoma State"):
        seen = {zingers.get_zinger(team, "Alice") for _ in range(30)}
        assert len(seen) > 1, f"expected multiple distinct zingers for {team}"


def test_spell_in_emoji_joins_regional_indicators_with_spaces():
    assert zingers._spell_in_emoji("LOL") == "\U0001F1F1 \U0001F1F4 \U0001F1F1"


def test_get_flair_reaction_never_returns_none():
    assert zingers.get_flair_reaction(None, "Alice") is not None
    assert zingers.get_flair_reaction("Rice", "Alice") is not None
    assert zingers.get_flair_reaction("Purdue", "Alice") is not None


def test_get_flair_reaction_formats_username_from_generic_pool():
    result = zingers.get_flair_reaction(
        None, "Alice", choice_fn=lambda options: options[0]
    )
    assert result == "Alice has picked a side. Bold. Very bold."


def test_get_flair_reaction_can_pick_a_team_specific_roast():
    result = zingers.get_flair_reaction(
        "Purdue", "Alice", choice_fn=lambda options: options[-1]
    )
    assert result == zingers._ZINGERS["purdue"][-1].format(user="Alice")


def test_get_flair_reaction_has_variety_across_categories():
    seen = {zingers.get_flair_reaction("Purdue", "Alice") for _ in range(60)}
    assert len(seen) > 5, "expected a mix of generic, emoji, and team-specific reactions"
