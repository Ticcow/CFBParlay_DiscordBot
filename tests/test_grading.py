from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent
from bot.parlays import grading, repository


def make_leg(market, selection, line_value, home_score, away_score):
    return {
        "market": market,
        "selection": selection,
        "line_value": line_value,
        "home_score": home_score,
        "away_score": away_score,
    }


# --- spread ---


def test_grade_leg_spread_home_covers():
    leg = make_leg("spread", "home", -6.5, home_score=24, away_score=17)  # wins by 7, covers 6.5
    assert grading.grade_leg(leg) == "win"


def test_grade_leg_spread_home_fails_to_cover():
    leg = make_leg("spread", "home", -6.5, home_score=20, away_score=17)  # wins by 3
    assert grading.grade_leg(leg) == "loss"


def test_grade_leg_spread_push_on_exact_number():
    leg = make_leg("spread", "home", -7.0, home_score=24, away_score=17)  # wins by exactly 7
    assert grading.grade_leg(leg) == "push"


def test_grade_leg_spread_away_covers_as_underdog():
    leg = make_leg("spread", "away", 6.5, home_score=24, away_score=20)  # loses by 4, covers 6.5
    assert grading.grade_leg(leg) == "win"


def test_grade_leg_spread_away_fails_to_cover():
    leg = make_leg("spread", "away", 6.5, home_score=31, away_score=17)  # loses by 14
    assert grading.grade_leg(leg) == "loss"


# --- moneyline ---


def test_grade_leg_moneyline_home_wins():
    leg = make_leg("moneyline", "home", None, home_score=24, away_score=17)
    assert grading.grade_leg(leg) == "win"


def test_grade_leg_moneyline_away_loses():
    leg = make_leg("moneyline", "away", None, home_score=24, away_score=17)
    assert grading.grade_leg(leg) == "loss"


def test_grade_leg_moneyline_tie_is_push():
    leg = make_leg("moneyline", "home", None, home_score=17, away_score=17)
    assert grading.grade_leg(leg) == "push"


# --- total ---


def test_grade_leg_total_over_hits():
    leg = make_leg("total", "over", 54.5, home_score=31, away_score=27)  # total 58
    assert grading.grade_leg(leg) == "win"


def test_grade_leg_total_under_hits():
    leg = make_leg("total", "under", 54.5, home_score=17, away_score=14)  # total 31
    assert grading.grade_leg(leg) == "win"


def test_grade_leg_total_push_on_exact_number():
    leg = make_leg("total", "over", 45.0, home_score=24, away_score=21)  # total 45
    assert grading.grade_leg(leg) == "push"


# --- parlay-level combination ---


def test_grade_parlay_all_wins_is_win():
    assert grading.grade_parlay(["win", "win", "win"]) == "win"


def test_grade_parlay_any_loss_dominates():
    assert grading.grade_parlay(["win", "loss", "push"]) == "loss"


def test_grade_parlay_push_without_loss_is_push():
    assert grading.grade_parlay(["win", "push", "win"]) == "push"


def test_grade_parlay_all_push_is_push():
    assert grading.grade_parlay(["push", "push"]) == "push"


# --- grade_week integration ---


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


def test_grade_week_credits_winner_and_skips_incomplete_game(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    final_game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "final", 24, 17)
    pending_game = _sync_game(conn, week_id, 2, "Alabama", "Georgia", "scheduled")

    participant = repository.opt_in(conn, user_id=7, week_id=week_id)

    won_parlay_id = repository.start_parlay(conn, 7, week_id)
    snapshot = repository.get_latest_odds_snapshot(conn, final_game["id"])
    repository.add_leg(conn, won_parlay_id, final_game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, won_parlay_id, participant["id"], 100.0, 166.67)

    pending_parlay_id = repository.start_parlay(conn, 7, week_id)
    pending_snapshot = repository.get_latest_odds_snapshot(conn, pending_game["id"])
    repository.add_leg(
        conn, pending_parlay_id, pending_game["id"], pending_snapshot["id"], "moneyline", "home", None, -150
    )
    repository.submit_parlay(conn, pending_parlay_id, participant["id"], 50.0, 83.33)

    result = grading.grade_week(conn, week_id)

    assert result["graded"] == [(won_parlay_id, "win")]
    assert result["skipped_incomplete"] == [pending_parlay_id]

    graded_parlay = repository.get_parlay(conn, won_parlay_id)
    assert graded_parlay["status"] == "graded"
    assert graded_parlay["actual_payout_dollars"] == 166.67

    updated_participant = repository.get_participant(conn, 7, week_id)
    # started at 1000, -100 -50 for the two wagers, +166.67 credited back for the win
    assert updated_participant["current_balance"] == 1000 - 100 - 50 + 166.67


def test_grade_week_debits_stay_put_on_loss(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    final_game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "final", 10, 24)

    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 7, week_id)
    snapshot = repository.get_latest_odds_snapshot(conn, final_game["id"])
    repository.add_leg(conn, parlay_id, final_game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)

    result = grading.grade_week(conn, week_id)

    assert result["graded"] == [(parlay_id, "loss")]
    updated_participant = repository.get_participant(conn, 7, week_id)
    assert updated_participant["current_balance"] == 900.0


# --- grade_pending_legs (live, per-leg grading) ---


def test_grade_pending_legs_grades_only_the_finished_leg(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    final_game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "final", 24, 17)
    pending_game = _sync_game(conn, week_id, 2, "Alabama", "Georgia", "scheduled")

    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 7, week_id)
    final_snapshot = repository.get_latest_odds_snapshot(conn, final_game["id"])
    pending_snapshot = repository.get_latest_odds_snapshot(conn, pending_game["id"])
    repository.add_leg(conn, parlay_id, final_game["id"], final_snapshot["id"], "moneyline", "home", None, -150)
    repository.add_leg(conn, parlay_id, pending_game["id"], pending_snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 277.78)

    graded_count = grading.grade_pending_legs(conn, week_id)

    assert graded_count == 1
    legs = repository.list_legs_with_games(conn, parlay_id)
    results_by_game = {leg["game_id"]: leg["result"] for leg in legs}
    assert results_by_game[final_game["id"]] == "win"
    assert results_by_game[pending_game["id"]] == "pending"

    # the parlay itself is untouched - that's grade_week's job, once every leg is done
    parlay = repository.get_parlay(conn, parlay_id)
    assert parlay["status"] == "submitted"
    participant_after = repository.get_participant(conn, 7, week_id)
    assert participant_after["current_balance"] == 900.0  # no credit yet


def test_grade_pending_legs_does_not_regrade_already_graded_legs(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    final_game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "final", 24, 17)
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 7, week_id)
    snapshot = repository.get_latest_odds_snapshot(conn, final_game["id"])
    repository.add_leg(conn, parlay_id, final_game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)

    first_pass = grading.grade_pending_legs(conn, week_id)
    second_pass = grading.grade_pending_legs(conn, week_id)

    assert first_pass == 1
    assert second_pass == 0


def test_grade_pending_legs_returns_zero_when_nothing_is_final(conn):
    week_id = repository.upsert_week(conn, 2026, 1, "regular")
    pending_game = _sync_game(conn, week_id, 1, "Texas", "Ohio State", "scheduled")
    participant = repository.opt_in(conn, user_id=7, week_id=week_id)
    parlay_id = repository.start_parlay(conn, 7, week_id)
    snapshot = repository.get_latest_odds_snapshot(conn, pending_game["id"])
    repository.add_leg(conn, parlay_id, pending_game["id"], snapshot["id"], "moneyline", "home", None, -150)
    repository.submit_parlay(conn, parlay_id, participant["id"], 100.0, 166.67)

    assert grading.grade_pending_legs(conn, week_id) == 0
