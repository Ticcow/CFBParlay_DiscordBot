import sqlite3

from bot.integrations.cfbd_client import CfbdGame


def upsert_week(
    conn: sqlite3.Connection, season_year: int, week_number: int, season_type: str
) -> int:
    conn.execute(
        """
        INSERT INTO weeks (season_year, week_number, season_type)
        VALUES (?, ?, ?)
        ON CONFLICT (season_year, week_number, season_type) DO NOTHING
        """,
        (season_year, week_number, season_type),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM weeks WHERE season_year = ? AND week_number = ? AND season_type = ?",
        (season_year, week_number, season_type),
    ).fetchone()
    return row["id"]


def upsert_games(conn: sqlite3.Connection, week_id: int, games: list[CfbdGame]) -> None:
    for game in games:
        conn.execute(
            """
            INSERT INTO games (
                week_id, cfbd_game_id, home_team, away_team,
                start_time_utc, status, home_score, away_score, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (cfbd_game_id) DO UPDATE SET
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                start_time_utc = excluded.start_time_utc,
                status = excluded.status,
                home_score = excluded.home_score,
                away_score = excluded.away_score,
                updated_at = datetime('now')
            """,
            (
                week_id,
                game.cfbd_game_id,
                game.home_team,
                game.away_team,
                game.start_time_utc,
                game.status,
                game.home_score,
                game.away_score,
            ),
        )
    conn.commit()


def get_latest_week(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM weeks ORDER BY id DESC LIMIT 1").fetchone()


def list_games(conn: sqlite3.Connection, week_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM games WHERE week_id = ? ORDER BY start_time_utc", (week_id,)
    ).fetchall()


def log_api_usage(
    conn: sqlite3.Connection, service: str, endpoint: str, credits_used: int = 1
) -> None:
    conn.execute(
        "INSERT INTO api_usage_log (service, endpoint, credits_used) VALUES (?, ?, ?)",
        (service, endpoint, credits_used),
    )
    conn.commit()
