from datetime import timedelta

from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent
from bot.parlays import locking, repository, timeutils

PAST = (timeutils.utc_now() - timedelta(hours=1)).isoformat()
FUTURE = (timeutils.utc_now() + timedelta(days=1)).isoformat()


def make_game(cfbd_game_id, start_time_utc, home="Texas", away="Ohio State"):
    return CfbdGame(
        cfbd_game_id=cfbd_game_id,
        home_team=home,
        away_team=away,
        start_time_utc=start_time_utc,
        status="scheduled",
        home_score=None,
        away_score=None,
    )


def add_snapshot_and_leg(conn, parlay_id, game_row, leg_number=1):
    event = OddsEvent(
        home_team_raw=game_row["home_team"],
        away_team_raw=game_row["away_team"],
        commence_time=game_row["start_time_utc"],
        book="draftkings",
        moneyline_home=-150,
        moneyline_away=130,
    )
    repository.insert_odds_snapshot(conn, game_row["id"], event, flipped=False)
    snapshot = repository.get_latest_odds_snapshot(conn, game_row["id"])
    repository.add_leg(
        conn, parlay_id, game_row["id"], snapshot["id"], "moneyline", "home", None, -150
    )


def setup_week_with_games(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.upsert_games(
        conn,
        week_id,
        [
            make_game(1, PAST, "Texas", "Ohio State"),
            make_game(2, FUTURE, "Alabama", "Georgia"),
        ],
    )
    games = repository.list_games(conn, week_id)
    past_game = next(g for g in games if g["home_team"] == "Texas")
    future_game = next(g for g in games if g["home_team"] == "Alabama")
    return week_id, past_game, future_game


def test_lock_check_locks_submitted_parlay_past_kickoff(conn):
    week_id, past_game, _ = setup_week_with_games(conn)
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)
    add_snapshot_and_leg(conn, parlay_id, past_game)
    conn.execute("UPDATE parlays SET status = 'submitted' WHERE id = ?", (parlay_id,))
    conn.commit()

    result = locking.lock_check(conn)

    assert result["locked"] == [parlay_id]
    assert repository.get_parlay(conn, parlay_id)["status"] == "locked"


def test_lock_check_leaves_future_submitted_parlay_alone(conn):
    week_id, _, future_game = setup_week_with_games(conn)
    parlay_id = repository.start_parlay(conn, user_id=1, week_id=week_id)
    add_snapshot_and_leg(conn, parlay_id, future_game)
    conn.execute("UPDATE parlays SET status = 'submitted' WHERE id = ?", (parlay_id,))
    conn.commit()

    result = locking.lock_check(conn)

    assert result["locked"] == []
    assert repository.get_parlay(conn, parlay_id)["status"] == "submitted"


def test_lock_check_expires_stale_draft(conn):
    week_id, past_game, _ = setup_week_with_games(conn)
    parlay_id = repository.start_parlay(conn, user_id=42, week_id=week_id)
    add_snapshot_and_leg(conn, parlay_id, past_game)

    result = locking.lock_check(conn)

    assert result["expired_drafts"] == [(42, parlay_id)]
    assert repository.get_parlay(conn, parlay_id) is None


def test_lock_check_leaves_future_draft_alone(conn):
    week_id, _, future_game = setup_week_with_games(conn)
    parlay_id = repository.start_parlay(conn, user_id=42, week_id=week_id)
    add_snapshot_and_leg(conn, parlay_id, future_game)

    result = locking.lock_check(conn)

    assert result["expired_drafts"] == []
    assert repository.get_parlay(conn, parlay_id) is not None


def test_lock_check_ignores_draft_with_no_legs(conn):
    week_id, _, _ = setup_week_with_games(conn)
    parlay_id = repository.start_parlay(conn, user_id=42, week_id=week_id)

    result = locking.lock_check(conn)

    assert result["expired_drafts"] == []
    assert repository.get_parlay(conn, parlay_id) is not None
