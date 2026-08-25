-- AP poll rankings can genuinely tie two schools at the same rank (e.g. two
-- teams both at #14) - the original UNIQUE(week_id, rank) rejected that as a
-- constraint violation. rankings is a pure cache (replace_rankings fully
-- deletes and re-inserts on every sync), so it's safe to just rebuild it.
DROP TABLE IF EXISTS rankings;

CREATE TABLE rankings (
    id INTEGER PRIMARY KEY,
    week_id INTEGER NOT NULL REFERENCES weeks (id),
    rank INTEGER NOT NULL,
    school TEXT NOT NULL,
    UNIQUE (week_id, rank, school)
);

CREATE INDEX IF NOT EXISTS idx_rankings_week_id ON rankings (week_id);
