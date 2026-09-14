from bot.parlays import repository


def finalize_week(conn, week_id: int) -> list[int]:
    """Marks the weekly winner(s) once every submitted parlay for the week has
    finished grading. Clears anyone's unwagered bankroll first (see
    clear_unused_balance) so the winner is decided by actual betting results,
    not by who happened to leave the most money untouched. Returns the winning
    user_ids (a tie splits the win), or [] if grading isn't complete yet,
    nobody opted in, or the week was already finalized on a previous call.

    Runs exactly once per week: without the is_week_finalized guard, every
    later poll (poll_scores keeps running as long as any week is current,
    and grade_week_job's own Sunday fallback) would recompute and re-return
    the same winners, re-triggering the "week is final" announcement over
    and over instead of posting it once and going quiet until a new week
    opens."""
    if repository.is_week_finalized(conn, week_id):
        return []
    if repository.count_pending_parlays(conn, week_id) > 0:
        return []
    repository.clear_unused_balance(conn, week_id)
    winners = repository.mark_weekly_winners(conn, week_id)
    repository.mark_week_finalized(conn, week_id)
    return winners
