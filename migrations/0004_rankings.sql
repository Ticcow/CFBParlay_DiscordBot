CREATE TABLE IF NOT EXISTS rankings (
    id INTEGER PRIMARY KEY,
    week_id INTEGER NOT NULL REFERENCES weeks (id),
    rank INTEGER NOT NULL,
    school TEXT NOT NULL,
    UNIQUE (week_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_rankings_week_id ON rankings (week_id);

CREATE TABLE IF NOT EXISTS team_logos (
    school TEXT PRIMARY KEY,
    logo_url TEXT
);
