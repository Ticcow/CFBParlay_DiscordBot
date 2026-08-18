import sqlite3

ODDS_API_SOURCE = "the-odds-api"


def resolve(conn: sqlite3.Connection, source: str, source_team: str) -> str | None:
    row = conn.execute(
        "SELECT canonical_team FROM team_aliases WHERE source = ? AND source_team = ?",
        (source, source_team),
    ).fetchone()
    return row["canonical_team"] if row else None


def add_alias(
    conn: sqlite3.Connection, source: str, source_team: str, canonical_team: str
) -> None:
    conn.execute(
        """
        INSERT INTO team_aliases (source, source_team, canonical_team)
        VALUES (?, ?, ?)
        ON CONFLICT (source, source_team) DO UPDATE SET canonical_team = excluded.canonical_team
        """,
        (source, source_team, canonical_team),
    )
    conn.commit()
