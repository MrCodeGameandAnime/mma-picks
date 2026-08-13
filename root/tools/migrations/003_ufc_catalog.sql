CREATE TABLE fighters (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    nickname TEXT,
    date_of_birth TEXT,
    height_inches INTEGER,
    weight_lbs INTEGER,
    reach_inches REAL,
    stance TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE fighter_external_identities (
    fighter_id INTEGER NOT NULL REFERENCES fighters(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT,
    UNIQUE(provider, external_id),
    UNIQUE(fighter_id, provider)
);

CREATE INDEX fighters_canonical_name ON fighters(canonical_name);

ALTER TABLE events ADD COLUMN location TEXT;
ALTER TABLE events ADD COLUMN source_url TEXT;

ALTER TABLE fights ADD COLUMN fighter_a_id INTEGER REFERENCES fighters(id);
ALTER TABLE fights ADD COLUMN fighter_b_id INTEGER REFERENCES fighters(id);
ALTER TABLE fights ADD COLUMN winner_id INTEGER REFERENCES fighters(id);
ALTER TABLE fights ADD COLUMN result_method TEXT;
ALTER TABLE fights ADD COLUMN result_round INTEGER;
ALTER TABLE fights ADD COLUMN result_time TEXT;
ALTER TABLE fights ADD COLUMN result_time_format TEXT;
ALTER TABLE fights ADD COLUMN referee TEXT;
ALTER TABLE fights ADD COLUMN result_details TEXT;

CREATE TABLE fight_round_stats (
    id INTEGER PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    fighter_id INTEGER NOT NULL REFERENCES fighters(id),
    round_number INTEGER NOT NULL CHECK (round_number > 0),
    knockdowns INTEGER,
    sig_strikes_landed INTEGER,
    sig_strikes_attempted INTEGER,
    sig_strike_pct REAL,
    total_strikes_landed INTEGER,
    total_strikes_attempted INTEGER,
    takedowns_landed INTEGER,
    takedowns_attempted INTEGER,
    takedown_pct REAL,
    submission_attempts INTEGER,
    reversals INTEGER,
    control_seconds INTEGER,
    head_landed INTEGER,
    head_attempted INTEGER,
    body_landed INTEGER,
    body_attempted INTEGER,
    leg_landed INTEGER,
    leg_attempted INTEGER,
    distance_landed INTEGER,
    distance_attempted INTEGER,
    clinch_landed INTEGER,
    clinch_attempted INTEGER,
    ground_landed INTEGER,
    ground_attempted INTEGER,
    UNIQUE(fight_id, fighter_id, round_number)
);

CREATE INDEX fighter_external_identities_fighter
    ON fighter_external_identities(fighter_id);
CREATE INDEX fight_round_stats_fight_round
    ON fight_round_stats(fight_id, round_number);
CREATE INDEX fight_round_stats_fighter
    ON fight_round_stats(fighter_id);
