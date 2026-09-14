CREATE TABLE IF NOT EXISTS week_finalized (
    week_id INTEGER PRIMARY KEY REFERENCES weeks (id),
    finalized_at TEXT NOT NULL DEFAULT (datetime('now'))
);
