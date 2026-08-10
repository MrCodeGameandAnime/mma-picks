CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO settings(key, value, updated_at) VALUES
    ('starting_bankroll_cents', '750', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('default_stake_cents', '50', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('max_card_fights', '15', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('max_exposure_cents', '750', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

CREATE TABLE analysts (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    source_type TEXT,
    source_url TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT INTO analysts(slug, name, source_type, active)
VALUES ('theweasle', 'TheWeasle', 'manual', 1);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    promotion TEXT NOT NULL,
    name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    external_provider TEXT,
    external_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'upcoming', 'completed', 'canceled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE UNIQUE INDEX events_external_identity
    ON events(external_provider, external_id)
    WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE fights (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    fighter_a TEXT NOT NULL,
    fighter_b TEXT NOT NULL,
    weight_class TEXT,
    gender TEXT,
    card_section TEXT,
    bout_order INTEGER,
    scheduled_at TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'completed', 'canceled', 'no_contest', 'draw')),
    winner TEXT,
    external_provider TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(event_id, bout_order)
);

CREATE UNIQUE INDEX fights_external_identity
    ON fights(external_provider, external_id)
    WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE predictions (
    id INTEGER PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    analyst_id INTEGER NOT NULL REFERENCES analysts(id),
    picked_fighter TEXT NOT NULL,
    confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    predicted_method TEXT,
    source_url TEXT,
    source_published_at TEXT,
    captured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(fight_id, analyst_id)
);

CREATE TABLE odds_snapshots (
    id INTEGER PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    fighter TEXT NOT NULL,
    sportsbook TEXT NOT NULL,
    moneyline INTEGER NOT NULL CHECK (moneyline <= -100 OR moneyline >= 100),
    captured_at TEXT NOT NULL,
    external_provider TEXT NOT NULL
);

CREATE TABLE wagers (
    id INTEGER PRIMARY KEY,
    prediction_id INTEGER NOT NULL UNIQUE REFERENCES predictions(id) ON DELETE CASCADE,
    odds_snapshot_id INTEGER REFERENCES odds_snapshots(id),
    stake_cents INTEGER NOT NULL CHECK (stake_cents > 0),
    moneyline INTEGER NOT NULL CHECK (moneyline <= -100 OR moneyline >= 100),
    sportsbook TEXT NOT NULL,
    placed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'won', 'lost', 'push', 'void')),
    profit_cents INTEGER,
    settled_at TEXT
);

CREATE INDEX fights_event_order ON fights(event_id, bout_order);
CREATE INDEX predictions_analyst ON predictions(analyst_id);
CREATE INDEX odds_snapshots_fight ON odds_snapshots(fight_id, captured_at);
