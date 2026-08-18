from bot.parlays import repository


def finalize_week(conn, week_id: int) -> list[int]:
    """Marks the weekly winner(s) once every submitted parlay for the week has
    finished grading. Clears anyone's unwagered bankroll first (see
    clear_unused_balance) so the winner is decided by actual betting results,
    not by who happened to leave the most money untouched. Returns the winning
    user_ids (a tie splits the win), or [] if grading isn't complete yet or
    nobody opted in."""
    if repository.count_pending_parlays(conn, week_id) > 0:
        return []
    repository.clear_unused_balance(conn, week_id)
    return repository.mark_weekly_winners(conn, week_id)
