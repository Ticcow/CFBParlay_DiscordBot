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


def test_get_knockout_zinger_embeds_the_mention_and_bet_verbatim():
    result = zingers.get_knockout_zinger(
        "<@123>", "Texas -6.5 (-110)", choice_fn=lambda options: options[0]
    )
    assert result == zingers._KNOCKOUT_ZINGERS[0].format(user="<@123>", bet="Texas -6.5 (-110)")
    assert "<@123>" in result
    assert "Texas -6.5 (-110)" in result


def test_get_knockout_zinger_has_multiple_distinct_lines():
    seen = {zingers.get_knockout_zinger("<@123>", "Texas -6.5 (-110)") for _ in range(30)}
    assert len(seen) > 1


def test_get_trash_talk_only_draws_from_categories_that_apply():
    seen = {
        zingers.get_trash_talk("<@1>", "$0", [], has_bets=True, is_last=False, is_leader=False)[0]
        for _ in range(40)
    }
    assert seen <= {line.format(user="<@1>", balance="$0", bet="") for line in zingers._TRASH_TALK_GENERIC}


def test_get_trash_talk_fills_in_the_bet_and_balance():
    busted, _ = zingers.get_trash_talk(
        "<@1>", "$0", ["UCF -41.5 (-110)"], has_bets=True, is_last=False, is_leader=False,
        choice_fn=lambda options: options[-1],
    )
    last, _ = zingers.get_trash_talk(
        "<@1>", "$12", [], has_bets=True, is_last=True, is_leader=False,
        choice_fn=lambda options: options[-1],
    )
    assert "UCF -41.5 (-110)" in busted
    assert "$12" in last


def test_get_trash_talk_skips_recently_used_lines():
    recent = zingers._TRASH_TALK_GENERIC[:-1]
    message, template = zingers.get_trash_talk(
        "<@1>", "$0", [], has_bets=True, is_last=False, is_leader=False, recent=recent
    )
    assert template == zingers._TRASH_TALK_GENERIC[-1]


def test_get_trash_talk_reuses_lines_once_a_category_is_exhausted():
    message, template = zingers.get_trash_talk(
        "<@1>", "$0", [], has_bets=True, is_last=False, is_leader=False,
        recent=zingers._TRASH_TALK_GENERIC,
    )
    assert template in zingers._TRASH_TALK_GENERIC


def test_roast_pools_are_big_and_have_no_duplicates():
    pools = [
        zingers._KNOCKOUT_ZINGERS, zingers._TRASH_TALK_BUSTED_BET, zingers._TRASH_TALK_LAST_PLACE,
        zingers._TRASH_TALK_LEADER, zingers._TRASH_TALK_NO_BETS, zingers._TRASH_TALK_GENERIC,
    ]
    for pool in pools:
        assert len(pool) >= 12
        assert len(set(pool)) == len(pool)


def test_validate_roast_template_accepts_good_lines():
    assert zingers.validate_roast_template("generic", "{user} sucks at this, {balance} proves it") is None
    assert zingers.validate_roast_template("knockout", "{user} lost on {bet} lol") is None


def test_validate_roast_template_rejects_lines_that_would_break_at_post_time():
    assert "{user}" in zingers.validate_roast_template("generic", "no mention here")
    assert "{bet}" in zingers.validate_roast_template("generic", "{user} lost on {bet}")
    assert "{balance}" in zingers.validate_roast_template("knockout", "{user} at {balance}")
    assert "{usr}" in zingers.validate_roast_template("generic", "{user} and {usr}")
    assert "Unbalanced" in zingers.validate_roast_template("generic", "{user} is {dumb")
    assert "300" in zingers.validate_roast_template("generic", "{user} " + "x" * 300)


def test_every_built_in_roast_passes_its_own_validation():
    for category, (pool, _, _) in zingers.ROAST_CATEGORIES.items():
        for line in pool:
            assert zingers.validate_roast_template(category, line) is None, line


def test_get_trash_talk_can_pick_a_custom_line():
    custom_line = "{user} custom roast"
    message, template = zingers.get_trash_talk(
        "<@1>", "$0", [], has_bets=True, is_last=False, is_leader=False,
        custom={"generic": [custom_line]}, choice_fn=lambda options: options[-1],
    )
    assert template == custom_line
    assert message == "<@1> custom roast"


def test_get_knockout_zinger_can_pick_a_custom_line():
    line = zingers.get_knockout_zinger(
        "<@1>", "UCF -41.5 (-110)", ["{user} ate shit on {bet}"], choice_fn=lambda options: options[-1]
    )
    assert line == "<@1> ate shit on UCF -41.5 (-110)"
