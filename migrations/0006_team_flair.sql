ALTER TABLE team_logos ADD COLUMN color TEXT;

CREATE TABLE IF NOT EXISTS team_flair_roles (
    school TEXT PRIMARY KEY REFERENCES team_logos (school),
    role_id INTEGER NOT NULL UNIQUE
);
