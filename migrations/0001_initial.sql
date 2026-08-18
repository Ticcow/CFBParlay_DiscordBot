CREATE TABLE IF NOT EXISTS weeks (
    id INTEGER PRIMARY KEY,
    season_year INTEGER NOT NULL,
    week_number INTEGER NOT NULL,
    season_type TEXT NOT NULL CHECK (season_type IN ('regular', 'postseason')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (season_year, week_number, season_type)
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    week_id INTEGER NOT NULL REFERENCES weeks (id),
    cfbd_game_id INTEGER NOT NULL UNIQUE,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    start_time_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'in_progress', 'final')),
    home_score INTEGER,
    away_score INTEGER,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_games_week_id ON games (week_id);

CREATE TABLE IF NOT EXISTS api_usage_log (
    id INTEGER PRIMARY KEY,
    service TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    called_at TEXT NOT NULL DEFAULT (datetime('now')),
    credits_used INTEGER NOT NULL DEFAULT 1
);
