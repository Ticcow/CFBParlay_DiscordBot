import sqlite3

from bot.parlays import repository, timeutils


def _earliest_leg_start(conn: sqlite3.Connection, parlay_id: int):
    legs = repository.list_legs_with_games(conn, parlay_id)
    if not legs:
        return None
    return min(timeutils.parse_utc(leg["start_time_utc"]) for leg in legs)


def lock_check(conn: sqlite3.Connection) -> dict:
    now = timeutils.utc_now()

    locked_ids = []
    for parlay in repository.list_lockable_parlays(conn):
        earliest = _earliest_leg_start(conn, parlay["id"])
        if earliest is not None and earliest <= now:
            repository.lock_parlay(conn, parlay["id"])
            locked_ids.append(parlay["id"])

    expired_drafts = []
    for parlay in repository.list_draft_parlays(conn):
        earliest = _earliest_leg_start(conn, parlay["id"])
        if earliest is not None and earliest <= now:
            repository.cancel_parlay(conn, parlay["id"])
            expired_drafts.append((parlay["user_id"], parlay["id"]))

    return {"locked": locked_ids, "expired_drafts": expired_drafts}
