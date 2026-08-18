CREATE TABLE IF NOT EXISTS week_participants (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    week_id INTEGER NOT NULL REFERENCES weeks (id),
    opted_in_at TEXT NOT NULL DEFAULT (datetime('now')),
    starting_balance REAL NOT NULL DEFAULT 1000,
    current_balance REAL NOT NULL DEFAULT 1000,
    is_weekly_winner INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, week_id)
);

CREATE TABLE IF NOT EXISTS parlays (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    week_id INTEGER NOT NULL REFERENCES weeks (id),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'locked', 'graded')),
    wager_dollars REAL,
    potential_payout_dollars REAL,
    actual_payout_dollars REAL,
    submitted_at TEXT,
    locked_at TEXT,
    result TEXT NOT NULL DEFAULT 'pending' CHECK (result IN ('pending', 'win', 'loss', 'push')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- at most one draft parlay per user per week; submitted parlays are unbounded
-- (spending the same weekly bankroll across several bets is the whole point)
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_draft_per_user_week
    ON parlays (user_id, week_id) WHERE status = 'draft';
CREATE INDEX IF NOT EXISTS idx_parlays_week_id ON parlays (week_id);
CREATE INDEX IF NOT EXISTS idx_parlays_user_id ON parlays (user_id);

CREATE TABLE IF NOT EXISTS parlay_legs (
    id INTEGER PRIMARY KEY,
    parlay_id INTEGER NOT NULL REFERENCES parlays (id),
    leg_number INTEGER NOT NULL,
    game_id INTEGER NOT NULL REFERENCES games (id),
    odds_snapshot_id INTEGER NOT NULL REFERENCES odds_snapshots (id),
    market TEXT NOT NULL CHECK (market IN ('spread', 'moneyline', 'total')),
    selection TEXT NOT NULL CHECK (selection IN ('home', 'away', 'over', 'under')),
    line_value REAL,
    price_american INTEGER NOT NULL,
    result TEXT NOT NULL DEFAULT 'pending' CHECK (result IN ('pending', 'win', 'loss', 'push')),
    graded_at TEXT,
    UNIQUE (parlay_id, leg_number),
    UNIQUE (parlay_id, game_id)
);
