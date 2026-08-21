CREATE TABLE IF NOT EXISTS week_reminders_sent (
    week_id INTEGER NOT NULL REFERENCES weeks (id),
    threshold_hours INTEGER NOT NULL,
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (week_id, threshold_hours)
);
