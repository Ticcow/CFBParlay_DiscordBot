from bot.parlays import repository


def finalize_week(conn, week_id: int) -> list[int]:
    """Marks the weekly winner(s) once every submitted parlay for the week has
    finished grading. Returns the winning user_ids (a tie splits the win), or []
    if grading isn't complete yet or nobody opted in."""
    if repository.count_pending_parlays(conn, week_id) > 0:
        return []
    return repository.mark_weekly_winners(conn, week_id)
