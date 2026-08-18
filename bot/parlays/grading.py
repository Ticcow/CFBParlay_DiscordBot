from bot.parlays import repository


def grade_leg(leg) -> str:
    home_score = leg["home_score"]
    away_score = leg["away_score"]
    market = leg["market"]
    selection = leg["selection"]
    line_value = leg["line_value"]

    if market == "spread":
        margin = (
            (home_score + line_value) - away_score
            if selection == "home"
            else (away_score + line_value) - home_score
        )
        if margin > 0:
            return "win"
        return "loss" if margin < 0 else "push"

    if market == "moneyline":
        if home_score == away_score:
            return "push"  # not possible under CFB's mandatory-overtime rules, but be safe
        home_won = home_score > away_score
        return "win" if (selection == "home") == home_won else "loss"

    # total
    total = home_score + away_score
    diff = (total - line_value) if selection == "over" else (line_value - total)
    if diff > 0:
        return "win"
    return "loss" if diff < 0 else "push"


def grade_parlay(leg_results: list[str]) -> str:
    if any(result == "loss" for result in leg_results):
        return "loss"
    if any(result == "push" for result in leg_results):
        return "push"
    return "win"


def grade_pending_legs(conn, week_id: int) -> int:
    """Grades any individual leg whose game just went final, even while other
    legs on the same parlay are still pending - so people can watch a parlay's
    legs resolve one at a time throughout the day instead of only finding out
    anything once the whole parlay's legs (and thus the parlay itself) are
    done. Never touches the parlay's own status/bankroll - that stays
    grade_week's job, once every leg on it is actually graded. Returns how
    many legs were graded."""
    graded_count = 0
    for parlay in repository.list_gradable_parlays(conn, week_id):
        for leg in repository.list_legs_with_games(conn, parlay["id"]):
            if leg["result"] != "pending" or leg["game_status"] != "final":
                continue
            repository.grade_leg_result(conn, leg["id"], grade_leg(leg))
            graded_count += 1
    conn.commit()
    return graded_count


def grade_week(conn, week_id: int) -> dict:
    graded = []
    skipped_incomplete = []

    for parlay in repository.list_gradable_parlays(conn, week_id):
        legs = repository.list_legs_with_games(conn, parlay["id"])
        if any(leg["game_status"] != "final" for leg in legs):
            skipped_incomplete.append(parlay["id"])
            continue

        leg_results = []
        for leg in legs:
            result = grade_leg(leg)
            repository.grade_leg_result(conn, leg["id"], result)
            leg_results.append(result)

        parlay_result = grade_parlay(leg_results)
        if parlay_result == "win":
            actual_payout = parlay["potential_payout_dollars"]
        elif parlay_result == "push":
            actual_payout = parlay["wager_dollars"]
        else:
            actual_payout = 0.0

        repository.grade_parlay_result(conn, parlay["id"], parlay_result, actual_payout)
        if actual_payout:
            participant = repository.get_participant(conn, parlay["user_id"], week_id)
            repository.credit_balance(conn, participant["id"], actual_payout)

        graded.append((parlay["id"], parlay_result))

    conn.commit()
    return {"graded": graded, "skipped_incomplete": skipped_incomplete}
