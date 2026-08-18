from bot.integrations.cfbd_client import CfbdGame
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
