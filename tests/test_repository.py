import pytest

from bot.integrations import team_aliases
from bot.integrations.cfbd_client import CfbdGame, RankedTeam, TeamInfo
from bot.integrations.odds_client import OddsEvent
from bot.parlays import repository


def make_game(cfbd_game_id=1, status="scheduled"):
    return CfbdGame(
        cfbd_game_id=cfbd_game_id,
        home_team="Texas",
        away_team="Ohio State",
        start_time_utc="2026-08-29T19:00:00Z",
        status=status,
        home_score=None,
        away_score=None,
    )


def make_odds_event(home_team_raw="Texas", away_team_raw="Ohio State"):
    return OddsEvent(
        home_team_raw=home_team_raw,
        away_team_raw=away_team_raw,
        commence_time="2026-08-29T19:00:00Z",
        book="draftkings",
        spread_home=-6.5,
        spread_price_home=-110,
        spread_price_away=-110,
        moneyline_home=-250,
        moneyline_away=200,
        total_points=54.5,
        over_price=-110,
        under_price=-110,
    )


def test_upsert_week_is_idempotent(conn):
    first_id = repository.upsert_week(conn, 2026, 1, "regular")
    second_id = repository.upsert_week(conn, 2026, 1, "regular")
    assert first_id == second_id


def test_upsert_games_inserts_and_updates(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])

    games = repository.list_games(conn, week_id)
    assert len(games) == 1
    assert games[0]["status"] == "scheduled"

    repository.upsert_games(conn, week_id, [make_game(status="final")])
    games = repository.list_games(conn, week_id)
    assert len(games) == 1
    assert games[0]["status"] == "final"


def test_get_latest_week_returns_most_recently_created(conn):
    repository.upsert_week(conn, 2025, 15, "postseason")
    latest_id = repository.upsert_week(conn, 2026, 1, "regular")

    latest = repository.get_latest_week(conn)
    assert latest["id"] == latest_id


def test_log_api_usage_records_a_row(conn):
    repository.log_api_usage(conn, "cfbd", "/games")
    row = conn.execute("SELECT * FROM api_usage_log").fetchone()
    assert row["service"] == "cfbd"
    assert row["endpoint"] == "/games"
    assert row["credits_used"] == 1


def test_find_game_by_teams_matches_normal_orientation(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])

    game, flipped = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    assert game is not None
    assert flipped is False


def test_find_game_by_teams_matches_flipped_orientation(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])

    game, flipped = repository.find_game_by_teams(conn, week_id, "Ohio State", "Texas")
    assert game is not None
    assert flipped is True


def test_find_game_by_teams_returns_none_when_no_match(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])

    game, flipped = repository.find_game_by_teams(conn, week_id, "Alabama", "Georgia")
    assert game is None


def test_insert_odds_snapshot_normal_orientation(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")

    repository.insert_odds_snapshot(conn, game["id"], make_odds_event(), flipped=False)

    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    assert snapshot["spread_home"] == -6.5
    assert snapshot["moneyline_home"] == -250
    assert snapshot["moneyline_away"] == 200


def test_insert_odds_snapshot_flipped_orientation_swaps_and_negates(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")

    event = make_odds_event(home_team_raw="Ohio State", away_team_raw="Texas")
    repository.insert_odds_snapshot(conn, game["id"], event, flipped=True)

    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    # our home team (Texas) was event's *away* side, so its spread is the negation
    # and moneyline/spread prices are swapped
    assert snapshot["spread_home"] == 6.5
    assert snapshot["moneyline_home"] == 200
    assert snapshot["moneyline_away"] == -250


def test_sync_odds_for_week_resolves_aliases_and_matches(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    team_aliases.add_alias(conn, team_aliases.ODDS_API_SOURCE, "Texas Longhorns", "Texas")
    team_aliases.add_alias(
        conn, team_aliases.ODDS_API_SOURCE, "Ohio State Buckeyes", "Ohio State"
    )

    event = make_odds_event(
        home_team_raw="Texas Longhorns", away_team_raw="Ohio State Buckeyes"
    )
    result = repository.sync_odds_for_week(conn, week_id, [event])

    assert result.matched == 1
    assert result.unmatched == []


def test_sync_odds_for_week_reports_unmatched_events(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])

    event = make_odds_event(home_team_raw="Alabama", away_team_raw="Georgia")
    result = repository.sync_odds_for_week(conn, week_id, [event])

    assert result.matched == 0
    assert result.unmatched == [("Alabama", "Georgia")]


def test_get_latest_odds_snapshot_returns_most_recent(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")

    repository.insert_odds_snapshot(conn, game["id"], make_odds_event(), flipped=False)
    newer_event = make_odds_event()
    newer_event.spread_home = -3.0
    repository.insert_odds_snapshot(conn, game["id"], newer_event, flipped=False)

    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    assert snapshot["spread_home"] == -3.0


def setup_week_game_and_snapshot(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    repository.insert_odds_snapshot(conn, game["id"], make_odds_event(), flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    return week_id, game, snapshot


# --- bankroll ---


def test_opt_in_creates_participant_at_1000(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    assert participant["starting_balance"] == 1000
    assert participant["current_balance"] == 1000


def test_get_participant_returns_none_before_optin(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    assert repository.get_participant(conn, user_id=7, week_id=week_id) is None


# --- parlay lifecycle ---


def test_start_parlay_creates_draft(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    parlay_id = repository.start_parlay(conn, user_id=7, week_id=week_id)
    parlay = repository.get_parlay(conn, parlay_id)
    assert parlay["status"] == "draft"


def test_only_one_draft_per_user_week_is_enforced_at_db_level(conn):
    import sqlite3

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.start_parlay(conn, user_id=7, week_id=week_id)
    with pytest.raises(sqlite3.IntegrityError):
        repository.start_parlay(conn, user_id=7, week_id=week_id)


def test_add_leg_and_list_legs(conn):
    week_id, game, snapshot = setup_week_game_and_snapshot(conn)
    parlay_id = repository.start_parlay(conn, user_id=7, week_id=week_id)

    leg_number = repository.add_leg(
        conn, parlay_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110
    )
    assert leg_number == 1

    legs = repository.list_legs(conn, parlay_id)
    assert len(legs) == 1
    assert legs[0]["market"] == "spread"


def test_remove_leg_returns_false_when_not_found(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    parlay_id = repository.start_parlay(conn, user_id=7, week_id=week_id)
    assert repository.remove_leg(conn, parlay_id, 1) is False


def test_cancel_parlay_deletes_parlay_and_legs(conn):
    week_id, game, snapshot = setup_week_game_and_snapshot(conn)
    parlay_id = repository.start_parlay(conn, user_id=7, week_id=week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110)

    repository.cancel_parlay(conn, parlay_id)

    assert repository.get_parlay(conn, parlay_id) is None
    assert repository.list_legs(conn, parlay_id) == []


def test_submit_parlay_debits_balance_and_flips_status(conn):
    week_id, game, snapshot = setup_week_game_and_snapshot(conn)
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, user_id=7, week_id=week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110)

    ok = repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 190.91)

    assert ok is True
    assert repository.get_parlay(conn, parlay_id)["status"] == "submitted"
    updated = repository.get_participant(conn, user_id=7, week_id=week_id)
    assert updated["current_balance"] == pytest.approx(900.0)


def test_submit_parlay_rejects_wager_exceeding_balance(conn):
    week_id, game, snapshot = setup_week_game_and_snapshot(conn)
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, user_id=7, week_id=week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110)

    ok = repository.submit_parlay(conn, parlay_id, participant["id"], 1500.0, 2863.65)

    assert ok is False
    assert repository.get_parlay(conn, parlay_id)["status"] == "draft"
    unchanged = repository.get_participant(conn, user_id=7, week_id=week_id)
    assert unchanged["current_balance"] == 1000


def test_list_submitted_parlays_for_week_excludes_drafts(conn):
    week_id, game, snapshot = setup_week_game_and_snapshot(conn)
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    submitted_id = repository.start_parlay(conn, user_id=7, week_id=week_id)
    repository.add_leg(conn, submitted_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110)
    repository.submit_parlay(conn, submitted_id, participant["id"], 100.0, 190.91)

    other_participant = repository.opt_in(conn, user_id=8, week_id=week_id)
    repository.start_parlay(conn, user_id=8, week_id=week_id)  # still a draft

    parlays = repository.list_submitted_parlays_for_week(conn, week_id)
    assert [p["id"] for p in parlays] == [submitted_id]




# --- leaderboards / history ---


def test_season_wins_leaderboard_ranks_by_win_count(conn):
    week1 = repository.upsert_week(conn, 2026, 1, "regular")
    week2 = repository.upsert_week(conn, 2026, 2, "regular")
    repository.opt_in(conn, user_id=1, week_id=week1)
    repository.opt_in(conn, user_id=1, week_id=week2)
    repository.opt_in(conn, user_id=2, week_id=week1)
    conn.execute("UPDATE week_participants SET is_weekly_winner = 1 WHERE user_id = 1")
    conn.commit()

    rows = repository.season_wins_leaderboard(conn)
    assert rows[0]["user_id"] == 1
    assert rows[0]["wins"] == 2


def test_season_money_leaderboard_sums_net_across_weeks(conn):
    week1 = repository.upsert_week(conn, 2026, 1, "regular")
    week2 = repository.upsert_week(conn, 2026, 2, "regular")
    repository.opt_in(conn, user_id=1, week_id=week1)
    repository.opt_in(conn, user_id=1, week_id=week2)
    conn.execute(
        "UPDATE week_participants SET current_balance = 1200 WHERE user_id = 1 AND week_id = ?",
        (week1,),
    )
    conn.execute(
        "UPDATE week_participants SET current_balance = 900 WHERE user_id = 1 AND week_id = ?",
        (week2,),
    )
    conn.commit()

    rows = repository.season_money_leaderboard(conn)
    assert rows[0]["user_id"] == 1
    assert rows[0]["net"] == pytest.approx(100.0)  # +200 week1, -100 week2


def test_get_user_parlay_record_counts_by_result(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    repository.insert_odds_snapshot(conn, game["id"], make_odds_event(), flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)

    parlay_id = repository.start_parlay(conn, 7, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 190.91)
    repository.grade_parlay_result(conn, parlay_id, "win", 190.91)
    conn.commit()

    record = repository.get_user_parlay_record(conn, 7)
    assert record == {"win": 1}


def test_get_week_and_list_all_weeks(conn):
    week1 = repository.upsert_week(conn, 2026, 1, "regular")
    week2 = repository.upsert_week(conn, 2026, 2, "regular")

    assert repository.get_week(conn, week1)["week_number"] == 1
    weeks = repository.list_all_weeks(conn)
    assert [w["id"] for w in weeks] == [week2, week1]


# --- game picker (available games for a leg) ---


def test_list_available_games_for_leg_excludes_started_and_already_used(conn):
    import datetime

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    now = datetime.datetime(2026, 8, 28, tzinfo=datetime.timezone.utc)
    past = (now - datetime.timedelta(hours=1)).isoformat()
    future1 = (now + datetime.timedelta(hours=1)).isoformat()
    future2 = (now + datetime.timedelta(hours=2)).isoformat()
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(1, "Texas", "Ohio State", past, "scheduled", None, None),
            CfbdGame(2, "Alabama", "Georgia", future1, "scheduled", None, None),
            CfbdGame(3, "Michigan", "Notre Dame", future2, "scheduled", None, None),
        ],
    )
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)
    used_game, _ = repository.find_game_by_teams(conn, week_id, "Alabama", "Georgia")
    event = OddsEvent("Alabama", "Georgia", future1, "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, used_game["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, used_game["id"])
    repository.add_leg(conn, parlay_id, used_game["id"], snapshot["id"], "moneyline", "home", None, -150)

    games, total = repository.list_available_games_for_leg(conn, week_id, parlay_id, now)

    # Texas game already started, Alabama game is already a leg on this parlay -
    # only Michigan/Notre Dame is left
    assert total == 1
    assert [g["home_team"] for g in games] == ["Michigan"]


def test_list_available_games_for_leg_paginates(conn):
    import datetime

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    now = datetime.datetime(2026, 8, 28, tzinfo=datetime.timezone.utc)
    games_to_insert = [
        CfbdGame(i, f"Home{i}", f"Away{i}", (now + datetime.timedelta(hours=i)).isoformat(), "scheduled", None, None)
        for i in range(1, 31)  # 30 upcoming games
    ]
    repository.upsert_games(conn, week_id, games_to_insert)
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)

    page0, total = repository.list_available_games_for_leg(conn, week_id, parlay_id, now, page=0, page_size=25)
    page1, total_again = repository.list_available_games_for_leg(conn, week_id, parlay_id, now, page=1, page_size=25)

    assert total == 30
    assert total_again == 30
    assert len(page0) == 25
    assert len(page1) == 5


# --- rankings / team logos ---


def test_list_ranked_games_for_leg_orders_by_rank_and_skips_byes(conn):
    import datetime

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    now = datetime.datetime(2026, 8, 28, tzinfo=datetime.timezone.utc)
    future = (now + datetime.timedelta(hours=1)).isoformat()
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(1, "Georgia", "Marshall", future, "scheduled", None, None),
            CfbdGame(2, "Michigan", "Duke", future, "scheduled", None, None),
            # Ohio State (rank 2) has no game this week - a bye
        ],
    )
    repository.replace_rankings(
        conn,
        week_id,
        [
            RankedTeam(1, "Georgia"),
            RankedTeam(2, "Ohio State"),
            RankedTeam(3, "Michigan"),
        ],
    )
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)

    ranked = repository.list_ranked_games_for_leg(conn, week_id, parlay_id, now)

    assert [sort_rank for sort_rank, _, _, _ in ranked] == [1, 3]
    assert [game["home_team"] for _, _, _, game in ranked] == ["Georgia", "Michigan"]
    # Marshall and Duke aren't ranked, so only the home side carries a rank here
    assert [(home_rank, away_rank) for _, home_rank, away_rank, _ in ranked] == [(1, None), (3, None)]


def test_list_ranked_games_for_leg_dedupes_ranked_vs_ranked_matchup(conn):
    import datetime

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    now = datetime.datetime(2026, 8, 28, tzinfo=datetime.timezone.utc)
    future = (now + datetime.timedelta(hours=1)).isoformat()
    repository.upsert_games(conn, week_id, [CfbdGame(1, "Georgia", "Alabama", future, "scheduled", None, None)])
    repository.replace_rankings(conn, week_id, [RankedTeam(1, "Georgia"), RankedTeam(2, "Alabama")])
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)

    ranked = repository.list_ranked_games_for_leg(conn, week_id, parlay_id, now)

    assert len(ranked) == 1
    sort_rank, home_rank, away_rank, game = ranked[0]
    assert sort_rank == 1  # appears once, under the higher (lower-number) rank
    assert (home_rank, away_rank) == (1, 2)  # Georgia (home) and Alabama (away) both carry their own rank
    assert (game["home_team"], game["away_team"]) == ("Georgia", "Alabama")


def test_list_ranked_games_for_leg_excludes_started_and_already_used(conn):
    import datetime

    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    now = datetime.datetime(2026, 8, 28, tzinfo=datetime.timezone.utc)
    past = (now - datetime.timedelta(hours=1)).isoformat()
    future = (now + datetime.timedelta(hours=1)).isoformat()
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(1, "Georgia", "Marshall", past, "scheduled", None, None),
            CfbdGame(2, "Michigan", "Duke", future, "scheduled", None, None),
        ],
    )
    repository.replace_rankings(conn, week_id, [RankedTeam(1, "Georgia"), RankedTeam(2, "Michigan")])
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)
    michigan_game, _ = repository.find_game_by_teams(conn, week_id, "Michigan", "Duke")
    event = OddsEvent("Michigan", "Duke", future, "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, michigan_game["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, michigan_game["id"])
    repository.add_leg(conn, parlay_id, michigan_game["id"], snapshot["id"], "moneyline", "home", None, -150)

    ranked = repository.list_ranked_games_for_leg(conn, week_id, parlay_id, now)

    assert ranked == []  # Georgia's game started, Michigan's is already a leg


def test_replace_rankings_overwrites_previous_week_rankings(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.replace_rankings(conn, week_id, [RankedTeam(1, "Georgia")])
    repository.replace_rankings(conn, week_id, [RankedTeam(1, "Ohio State")])

    rows = conn.execute("SELECT school FROM rankings WHERE week_id = ?", (week_id,)).fetchall()
    assert [r["school"] for r in rows] == ["Ohio State"]


def test_team_logo_round_trip(conn):
    assert repository.get_team_logo(conn, "Notre Dame") is None

    repository.upsert_team_logos(conn, [TeamInfo("Notre Dame", "https://example.com/nd.png")])

    assert repository.get_team_logo(conn, "Notre Dame") == "https://example.com/nd.png"


def test_upsert_team_logos_updates_existing_url(conn):
    repository.upsert_team_logos(conn, [TeamInfo("Notre Dame", "https://example.com/old.png")])
    repository.upsert_team_logos(conn, [TeamInfo("Notre Dame", "https://example.com/new.png")])

    assert repository.get_team_logo(conn, "Notre Dame") == "https://example.com/new.png"


def test_upsert_team_logos_stores_color(conn):
    repository.upsert_team_logos(
        conn, [TeamInfo("Ohio State", "https://example.com/osu.png", "#BB0000")]
    )

    team = repository.get_team(conn, "Ohio State")
    assert team["color"] == "#BB0000"


def test_team_exists(conn):
    assert repository.team_exists(conn, "Purdue") is False

    repository.upsert_team_logos(conn, [TeamInfo("Purdue", None)])

    assert repository.team_exists(conn, "Purdue") is True


def test_search_team_schools_matches_substring_case_insensitively(conn):
    repository.upsert_team_logos(
        conn, [TeamInfo("Ohio State", None), TeamInfo("Boise State", None), TeamInfo("Purdue", None)]
    )

    assert repository.search_team_schools(conn, "state") == ["Boise State", "Ohio State"]
    assert repository.search_team_schools(conn, "purdue") == ["Purdue"]


def test_search_team_schools_respects_limit(conn):
    repository.upsert_team_logos(
        conn, [TeamInfo("Alabama", None), TeamInfo("Auburn", None), TeamInfo("Arizona", None)]
    )

    assert len(repository.search_team_schools(conn, "a", limit=2)) == 2


def test_list_conferences_returns_distinct_sorted_non_null_values(conn):
    repository.upsert_team_logos(
        conn,
        [
            TeamInfo("Ohio State", None, conference="Big Ten"),
            TeamInfo("Purdue", None, conference="Big Ten"),
            TeamInfo("Alabama", None, conference="SEC"),
            TeamInfo("Independent U", None, conference=None),
        ],
    )

    assert repository.list_conferences(conn) == ["Big Ten", "SEC"]


def test_list_teams_in_conference_returns_alphabetical_schools(conn):
    repository.upsert_team_logos(
        conn,
        [
            TeamInfo("Ohio State", None, conference="Big Ten"),
            TeamInfo("Purdue", None, conference="Big Ten"),
            TeamInfo("Alabama", None, conference="SEC"),
        ],
    )

    assert repository.list_teams_in_conference(conn, "Big Ten") == ["Ohio State", "Purdue"]
    assert repository.list_teams_in_conference(conn, "SEC") == ["Alabama"]
    assert repository.list_teams_in_conference(conn, "MAC") == []


def test_flair_role_round_trip(conn):
    assert repository.get_flair_role_id(conn, "Indiana") is None
    assert repository.list_flair_role_ids(conn) == []

    repository.upsert_team_logos(conn, [TeamInfo("Indiana", None)])
    repository.set_flair_role_id(conn, "Indiana", 111)

    assert repository.get_flair_role_id(conn, "Indiana") == 111
    assert repository.list_flair_role_ids(conn) == [111]

    repository.set_flair_role_id(conn, "Indiana", 222)

    assert repository.get_flair_role_id(conn, "Indiana") == 222
    assert repository.list_flair_role_ids(conn) == [222]


# --- admin test-fixture helpers ---


def test_set_game_final_score(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")

    repository.set_game_final_score(conn, game["id"], home_score=24, away_score=17)

    updated = repository.get_game(conn, game["id"])
    assert updated["status"] == "final"
    assert updated["home_score"] == 24
    assert updated["away_score"] == 17


def test_delete_week_cascade_removes_everything_under_the_week(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(conn, week_id, [make_game()])
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    repository.insert_odds_snapshot(conn, game["id"], make_odds_event(), flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    repository.replace_rankings(conn, week_id, [RankedTeam(1, "Texas")])
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 7, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "spread", "home", -6.5, -110)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 190.91)

    removed = repository.delete_week_cascade(conn, week_id)

    assert removed == 1
    assert repository.get_week(conn, week_id) is None
    assert repository.get_game(conn, game["id"]) is None
    assert repository.get_latest_odds_snapshot(conn, game["id"]) is None
    assert repository.get_parlay(conn, parlay_id) is None
    assert repository.get_participant(conn, 7, week_id) is None
    rankings = conn.execute("SELECT * FROM rankings WHERE week_id = ?", (week_id,)).fetchall()
    assert rankings == []


# --- bot_state key/value store ---


def test_get_state_returns_none_when_unset(conn):
    assert repository.get_state(conn, "some_key") is None


def test_set_state_then_get_state_round_trips(conn):
    repository.set_state(conn, "some_key", "some_value")
    assert repository.get_state(conn, "some_key") == "some_value"


def test_set_state_updates_existing_value(conn):
    repository.set_state(conn, "some_key", "first")
    repository.set_state(conn, "some_key", "second")
    assert repository.get_state(conn, "some_key") == "second"


# --- clear_unused_balance ---


def _final_game_and_snapshot(conn, week_id):
    repository.upsert_games(
        conn,
        week_id,
        [CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "final", 24, 17)],  # home wins
    )
    game, _ = repository.find_game_by_teams(conn, week_id, "Texas", "Ohio State")
    repository.insert_odds_snapshot(conn, game["id"], make_odds_event(), flipped=False)
    return game, repository.get_latest_odds_snapshot(conn, game["id"])


def test_clear_unused_balance_zeroes_a_participant_who_never_wagered(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)

    repository.clear_unused_balance(conn, week_id)

    assert repository.get_participant(conn, 1, week_id)["current_balance"] == 0


def test_clear_unused_balance_keeps_exactly_the_winning_payout(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    game, snapshot = _final_game_and_snapshot(conn, week_id)
    participant = repository.opt_in(conn, user_id=1, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 1, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)
    repository.grade_parlay_result(conn, parlay_id, "win", 166.67)
    repository.credit_balance(conn, participant["id"], 166.67)
    # balance is now 1000 - 100 (wagered) + 166.67 (won) = 1066.67, with $800 never touched

    repository.clear_unused_balance(conn, week_id)

    assert repository.get_participant(conn, 1, week_id)["current_balance"] == 166.67


def test_clear_unused_balance_leaves_a_lost_wager_at_zero_not_negative(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    game, snapshot = _final_game_and_snapshot(conn, week_id)
    participant = repository.opt_in(conn, user_id=1, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 1, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "away", None, 130)
    repository.submit_parlay(conn, parlay_id, participant["id"], 200.0, 460.0)
    repository.grade_parlay_result(conn, parlay_id, "loss", 0.0)
    # balance is 1000 - 200 (wagered and lost) = 800, all of it untouched-or-lost

    repository.clear_unused_balance(conn, week_id)

    assert repository.get_participant(conn, 1, week_id)["current_balance"] == 0


# --- pregame reminders ---


def test_list_user_ids_with_balance_excludes_zero_balance(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)
    repository.opt_in(conn, user_id=2, week_id=week_id)
    conn.execute(
        "UPDATE week_participants SET current_balance = 0 WHERE user_id = 2 AND week_id = ?",
        (week_id,),
    )
    conn.commit()

    assert repository.list_user_ids_with_balance(conn, week_id) == [1]


def test_get_earliest_kickoff_returns_min_start_time(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(1, "Texas", "Ohio State", "2026-08-29T19:00:00Z", "scheduled", None, None),
            CfbdGame(2, "Georgia", "Alabama", "2026-08-27T16:00:00Z", "scheduled", None, None),
        ],
    )

    assert repository.get_earliest_kickoff(conn, week_id) == "2026-08-27T16:00:00Z"


def test_get_earliest_kickoff_returns_none_with_no_games(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    assert repository.get_earliest_kickoff(conn, week_id) is None


def test_reminder_sent_tracking_is_per_week_and_threshold(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")

    assert repository.has_sent_reminder(conn, week_id, 24) is False

    repository.mark_reminder_sent(conn, week_id, 24)

    assert repository.has_sent_reminder(conn, week_id, 24) is True
    assert repository.has_sent_reminder(conn, week_id, 6) is False

    repository.mark_reminder_sent(conn, week_id, 24)  # marking twice doesn't error
