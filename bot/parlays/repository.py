import sqlite3
from dataclasses import dataclass, field

from bot.integrations import team_aliases
from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent


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


def find_game_by_teams(
    conn: sqlite3.Connection, week_id: int, team_a: str, team_b: str
) -> tuple[sqlite3.Row | None, bool]:
    """Match a game by its two teams, regardless of which side is "home" in the
    caller's data. Returns (game_row, flipped) where flipped=True means team_a is
    actually our away team (the caller's home/away disagreed with ours)."""
    row = conn.execute(
        "SELECT * FROM games WHERE week_id = ? AND home_team = ? AND away_team = ?",
        (week_id, team_a, team_b),
    ).fetchone()
    if row:
        return row, False
    row = conn.execute(
        "SELECT * FROM games WHERE week_id = ? AND home_team = ? AND away_team = ?",
        (week_id, team_b, team_a),
    ).fetchone()
    return (row, True) if row else (None, False)


def insert_odds_snapshot(
    conn: sqlite3.Connection, game_id: int, event: OddsEvent, flipped: bool
) -> None:
    if flipped:
        # event's fields are relative to event.home_team_raw, which is actually our
        # away team here - swap prices, and negate the spread (points are always
        # exact negatives between the two sides of a spread market).
        spread_home = -event.spread_home if event.spread_home is not None else None
        spread_price_home = event.spread_price_away
        spread_price_away = event.spread_price_home
        moneyline_home = event.moneyline_away
        moneyline_away = event.moneyline_home
    else:
        spread_home = event.spread_home
        spread_price_home = event.spread_price_home
        spread_price_away = event.spread_price_away
        moneyline_home = event.moneyline_home
        moneyline_away = event.moneyline_away

    conn.execute(
        """
        INSERT INTO odds_snapshots (
            game_id, spread_home, spread_price_home, spread_price_away,
            moneyline_home, moneyline_away, total_points, over_price, under_price, book
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            spread_home,
            spread_price_home,
            spread_price_away,
            moneyline_home,
            moneyline_away,
            event.total_points,
            event.over_price,
            event.under_price,
            event.book,
        ),
    )
    conn.commit()


@dataclass
class OddsSyncResult:
    matched: int = 0
    unmatched: list[tuple[str, str]] = field(default_factory=list)


def sync_odds_for_week(
    conn: sqlite3.Connection, week_id: int, events: list[OddsEvent]
) -> OddsSyncResult:
    result = OddsSyncResult()
    for event in events:
        home = (
            team_aliases.resolve(conn, team_aliases.ODDS_API_SOURCE, event.home_team_raw)
            or event.home_team_raw
        )
        away = (
            team_aliases.resolve(conn, team_aliases.ODDS_API_SOURCE, event.away_team_raw)
            or event.away_team_raw
        )
        game, flipped = find_game_by_teams(conn, week_id, home, away)
        if game is None:
            result.unmatched.append((event.home_team_raw, event.away_team_raw))
            continue
        insert_odds_snapshot(conn, game["id"], event, flipped)
        result.matched += 1
    return result


def get_latest_odds_snapshot(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM odds_snapshots WHERE game_id = ? ORDER BY fetched_at DESC, id DESC LIMIT 1",
        (game_id,),
    ).fetchone()
