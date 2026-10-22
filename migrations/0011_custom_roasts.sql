CREATE TABLE IF NOT EXISTS custom_roasts (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL CHECK (
        category IN ('generic', 'busted_bet', 'no_bets', 'last_place', 'leader', 'knockout')
    ),
    template TEXT NOT NULL,
    added_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (category, template)
);
