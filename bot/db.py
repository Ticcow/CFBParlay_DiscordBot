import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}

    for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration_file.name.split("_", 1)[0])
        if version in applied:
            continue
        conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()
