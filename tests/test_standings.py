from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent
from bot.parlays import grading, repository, standings


def _sync_game(conn, week_id, cfbd_game_id, home, away, status, home_score=None, away_score=None):
    repository.upsert_games(
        conn,
        week_id,
        [
            CfbdGame(
                cfbd_game_id=cfbd_game_id,
                home_team=home,
                away_team=away,
                start_time_utc="2026-08-29T19:00:00Z",
                status=status,
                home_score=home_score,
                away_score=away_score,
            )
        ],
    )
    game, _ = repository.find_game_by_teams(conn, week_id, home, away)
    event = OddsEvent(home, away, "2026-08-29T19:00:00Z", "draftkings", moneyline_home=-150, moneyline_away=130)
    repository.insert_odds_snapshot(conn, game["id"], event, flipped=False)
    return repository.get_game(conn, game["id"])


def test_finalize_week_returns_empty_while_parlays_still_pending(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "scheduled")
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 7, week_id)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)

    assert standings.finalize_week(conn, week_id) == []


def test_finalize_week_marks_the_highest_balance_as_winner(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "final", 24, 17)
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])

    participant1 = repository.opt_in(conn, user_id=1, week_id=week_id)
    parlay1 = repository.start_parlay(conn, 1, week_id)
    repository.add_leg(conn, parlay1, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay1, participant1["id"], 500.0, 833.33)

    participant2 = repository.opt_in(conn, user_id=2, week_id=week_id)
    parlay2 = repository.start_parlay(conn, 2, week_id)
    repository.add_leg(conn, parlay2, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay2, participant2["id"], 100.0, 166.67)

    grading.grade_week(conn, week_id)
    winners = standings.finalize_week(conn, week_id)

    assert winners == [1]
    p1 = repository.get_participant(conn, 1, week_id)
    p2 = repository.get_participant(conn, 2, week_id)
    assert p1["is_weekly_winner"] == 1
    assert p2["is_weekly_winner"] == 0


def test_finalize_week_clears_unwagered_balance_so_sitting_out_cannot_win(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "final", 24, 17)  # home wins
    snapshot = repository.get_latest_odds_snapshot(conn, game["id"])

    # user 1 opts in but never wagers a dime - still shows the full untouched $1,000
    repository.opt_in(conn, user_id=1, week_id=week_id)

    # user 2 wagers $100 on the winning side and actually turns it into real profit
    participant2 = repository.opt_in(conn, user_id=2, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 2, week_id)
    repository.add_leg(conn, parlay_id, game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant2["id"], 100.0, 166.67)

    grading.grade_week(conn, week_id)
    winners = standings.finalize_week(conn, week_id)

    assert winners == [2]
    p1 = repository.get_participant(conn, 1, week_id)
    p2 = repository.get_participant(conn, 2, week_id)
    assert p1["current_balance"] == 0  # untouched $1,000 gets cleared entirely
    assert p2["current_balance"] == 166.67  # exactly what the winning parlay paid back


def test_finalize_week_splits_a_tie(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    repository.opt_in(conn, user_id=1, week_id=week_id)
    repository.opt_in(conn, user_id=2, week_id=week_id)
    # neither wagered anything, so both get cleared down to $0 - still a tie

    winners = standings.finalize_week(conn, week_id)

    assert sorted(winners) == [1, 2]


def test_finalize_week_no_participants_returns_empty(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    assert standings.finalize_week(conn, week_id) == []
