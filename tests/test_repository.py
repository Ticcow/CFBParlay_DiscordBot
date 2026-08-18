from bot.integrations import team_aliases
from bot.integrations.cfbd_client import CfbdGame
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
