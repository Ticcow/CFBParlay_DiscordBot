CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games (id),
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    spread_home REAL,
    spread_price_home INTEGER,
    spread_price_away INTEGER,
    moneyline_home INTEGER,
    moneyline_away INTEGER,
    total_points REAL,
    over_price INTEGER,
    under_price INTEGER,
    book TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_odds_snapshots_game_id ON odds_snapshots (game_id);

CREATE TABLE IF NOT EXISTS team_aliases (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_team TEXT NOT NULL,
    canonical_team TEXT NOT NULL,
    UNIQUE (source, source_team)
);
