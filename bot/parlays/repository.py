import sqlite3
from dataclasses import dataclass, field

from bot.integrations import team_aliases
from bot.integrations.cfbd_client import CfbdGame
from bot.integrations.odds_client import OddsEvent
from bot.parlays import timeutils


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


def get_game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()


def search_games(
    conn: sqlite3.Connection, week_id: int, query: str, limit: int = 25
) -> list[sqlite3.Row]:
    like = f"%{query}%"
    return conn.execute(
        """
        SELECT * FROM games WHERE week_id = ? AND (home_team LIKE ? OR away_team LIKE ?)
        ORDER BY start_time_utc LIMIT ?
        """,
        (week_id, like, like, limit),
    ).fetchall()


# --- weekly bankroll ---


def get_participant(
    conn: sqlite3.Connection, user_id: int, week_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM week_participants WHERE user_id = ? AND week_id = ?",
        (user_id, week_id),
    ).fetchone()


def opt_in(conn: sqlite3.Connection, user_id: int, week_id: int) -> sqlite3.Row:
    conn.execute(
        "INSERT INTO week_participants (user_id, week_id) VALUES (?, ?)", (user_id, week_id)
    )
    conn.commit()
    return get_participant(conn, user_id, week_id)


# --- parlays ---


def get_draft_parlay(
    conn: sqlite3.Connection, user_id: int, week_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM parlays WHERE user_id = ? AND week_id = ? AND status = 'draft'",
        (user_id, week_id),
    ).fetchone()


def start_parlay(conn: sqlite3.Connection, user_id: int, week_id: int) -> int:
    cursor = conn.execute(
        "INSERT INTO parlays (user_id, week_id, status) VALUES (?, ?, 'draft')",
        (user_id, week_id),
    )
    conn.commit()
    return cursor.lastrowid


def cancel_parlay(conn: sqlite3.Connection, parlay_id: int) -> None:
    conn.execute("DELETE FROM parlay_legs WHERE parlay_id = ?", (parlay_id,))
    conn.execute("DELETE FROM parlays WHERE id = ?", (parlay_id,))
    conn.commit()


def get_parlay(conn: sqlite3.Connection, parlay_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM parlays WHERE id = ?", (parlay_id,)).fetchone()


def list_legs(conn: sqlite3.Connection, parlay_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parlay_legs WHERE parlay_id = ? ORDER BY leg_number", (parlay_id,)
    ).fetchall()


def list_legs_with_games(conn: sqlite3.Connection, parlay_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT parlay_legs.*, games.home_team, games.away_team, games.start_time_utc,
               games.status AS game_status, games.home_score, games.away_score
        FROM parlay_legs
        JOIN games ON games.id = parlay_legs.game_id
        WHERE parlay_legs.parlay_id = ?
        ORDER BY parlay_legs.leg_number
        """,
        (parlay_id,),
    ).fetchall()


def add_leg(
    conn: sqlite3.Connection,
    parlay_id: int,
    game_id: int,
    odds_snapshot_id: int,
    market: str,
    selection: str,
    line_value: float | None,
    price_american: int,
) -> int:
    leg_number = conn.execute(
        "SELECT COALESCE(MAX(leg_number), 0) + 1 FROM parlay_legs WHERE parlay_id = ?",
        (parlay_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO parlay_legs (
            parlay_id, leg_number, game_id, odds_snapshot_id,
            market, selection, line_value, price_american
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (parlay_id, leg_number, game_id, odds_snapshot_id, market, selection, line_value, price_american),
    )
    conn.commit()
    return leg_number


def remove_leg(conn: sqlite3.Connection, parlay_id: int, leg_number: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM parlay_legs WHERE parlay_id = ? AND leg_number = ?",
        (parlay_id, leg_number),
    )
    conn.commit()
    return cursor.rowcount > 0


def submit_parlay(
    conn: sqlite3.Connection,
    parlay_id: int,
    participant_id: int,
    wager_dollars: float,
    potential_payout_dollars: float,
) -> bool:
    """Atomically debits the bankroll and flips the parlay to 'submitted'. Returns
    False (no changes made) if the wager exceeds the participant's current balance -
    the balance check and the debit happen in the same guarded UPDATE so two
    near-simultaneous submits can't overdraw the bankroll."""
    cursor = conn.execute(
        "UPDATE week_participants SET current_balance = current_balance - ? "
        "WHERE id = ? AND current_balance >= ?",
        (wager_dollars, participant_id, wager_dollars),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        return False
    conn.execute(
        "UPDATE parlays SET status = 'submitted', wager_dollars = ?, "
        "potential_payout_dollars = ?, submitted_at = datetime('now') WHERE id = ?",
        (wager_dollars, potential_payout_dollars, parlay_id),
    )
    conn.commit()
    return True


def list_parlays_for_user_week(
    conn: sqlite3.Connection, user_id: int, week_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parlays WHERE user_id = ? AND week_id = ? ORDER BY created_at",
        (user_id, week_id),
    ).fetchall()


def list_submitted_parlays_for_week(
    conn: sqlite3.Connection, week_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parlays WHERE week_id = ? AND status IN ('submitted', 'locked', 'graded') "
        "ORDER BY user_id, created_at",
        (week_id,),
    ).fetchall()


def week_is_visible(conn: sqlite3.Connection, week_id: int) -> bool:
    """True once the earliest-kickoff leg across any submitted parlay this week has
    started - that's when other members' parlays stop being hidden."""
    row = conn.execute(
        """
        SELECT MIN(games.start_time_utc) AS earliest
        FROM parlay_legs
        JOIN parlays ON parlays.id = parlay_legs.parlay_id
        JOIN games ON games.id = parlay_legs.game_id
        WHERE parlays.week_id = ? AND parlays.status IN ('submitted', 'locked', 'graded')
        """,
        (week_id,),
    ).fetchone()
    if row["earliest"] is None:
        return False
    return timeutils.parse_utc(row["earliest"]) <= timeutils.utc_now()


# --- locking ---


def list_lockable_parlays(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM parlays WHERE status = 'submitted'").fetchall()


def list_draft_parlays(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM parlays WHERE status = 'draft'").fetchall()


def lock_parlay(conn: sqlite3.Connection, parlay_id: int) -> None:
    conn.execute(
        "UPDATE parlays SET status = 'locked', locked_at = datetime('now') WHERE id = ?",
        (parlay_id,),
    )
    conn.commit()


# --- grading ---


def list_gradable_parlays(conn: sqlite3.Connection, week_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parlays WHERE week_id = ? AND status IN ('submitted', 'locked')",
        (week_id,),
    ).fetchall()


def grade_leg_result(conn: sqlite3.Connection, leg_id: int, result: str) -> None:
    conn.execute(
        "UPDATE parlay_legs SET result = ?, graded_at = datetime('now') WHERE id = ?",
        (result, leg_id),
    )


def grade_parlay_result(
    conn: sqlite3.Connection, parlay_id: int, result: str, actual_payout_dollars: float
) -> None:
    conn.execute(
        "UPDATE parlays SET status = 'graded', result = ?, actual_payout_dollars = ? WHERE id = ?",
        (result, actual_payout_dollars, parlay_id),
    )


def credit_balance(conn: sqlite3.Connection, participant_id: int, amount: float) -> None:
    conn.execute(
        "UPDATE week_participants SET current_balance = current_balance + ? WHERE id = ?",
        (amount, participant_id),
    )


# --- weekly winner + leaderboards ---


def count_pending_parlays(conn: sqlite3.Connection, week_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM parlays WHERE week_id = ? AND status IN ('submitted', 'locked')",
        (week_id,),
    ).fetchone()
    return row[0]


def mark_weekly_winners(conn: sqlite3.Connection, week_id: int) -> list[int]:
    row = conn.execute(
        "SELECT MAX(current_balance) AS max_balance FROM week_participants WHERE week_id = ?",
        (week_id,),
    ).fetchone()
    max_balance = row["max_balance"]
    if max_balance is None:
        return []

    winners = conn.execute(
        "SELECT user_id FROM week_participants WHERE week_id = ? AND current_balance = ?",
        (week_id, max_balance),
    ).fetchall()
    conn.execute(
        "UPDATE week_participants SET is_weekly_winner = 1 WHERE week_id = ? AND current_balance = ?",
        (week_id, max_balance),
    )
    conn.commit()
    return [winner["user_id"] for winner in winners]


def list_week_standings(conn: sqlite3.Connection, week_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM week_participants WHERE week_id = ? ORDER BY current_balance DESC",
        (week_id,),
    ).fetchall()


def season_wins_leaderboard(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT user_id, COUNT(*) AS wins FROM week_participants WHERE is_weekly_winner = 1 "
        "GROUP BY user_id ORDER BY wins DESC"
    ).fetchall()


def season_money_leaderboard(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT user_id, SUM(current_balance - starting_balance) AS net FROM week_participants "
        "GROUP BY user_id ORDER BY net DESC"
    ).fetchall()


def get_user_weekly_win_count(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM week_participants WHERE user_id = ? AND is_weekly_winner = 1",
        (user_id,),
    ).fetchone()
    return row[0]


def get_user_season_net(conn: sqlite3.Connection, user_id: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(current_balance - starting_balance), 0) FROM week_participants "
        "WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row[0]


def get_user_parlay_record(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT result, COUNT(*) AS n FROM parlays WHERE user_id = ? AND status = 'graded' "
        "GROUP BY result",
        (user_id,),
    ).fetchall()
    return {row["result"]: row["n"] for row in rows}


def get_week(conn: sqlite3.Connection, week_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM weeks WHERE id = ?", (week_id,)).fetchone()


def list_all_weeks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM weeks ORDER BY id DESC").fetchall()
