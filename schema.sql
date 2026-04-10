-- Grocery Assistant SQLite Schema
-- Phase 1 MVP

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK (role IN ('owner', 'contributor')),
    channel     TEXT    NOT NULL CHECK (channel IN ('discord', 'sms', 'cli'))
);

CREATE TABLE IF NOT EXISTS intake_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text        TEXT    NOT NULL,
    source_channel  TEXT    NOT NULL,
    sender          TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS grocery_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    canonical   TEXT    NOT NULL,
    quantity    TEXT,
    unit        TEXT,
    notes       TEXT,
    category    TEXT    NOT NULL DEFAULT 'other',
    status      TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'reviewed', 'drafted', 'ordered', 'removed')),
    ambiguous   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS grocery_item_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES grocery_items(id),
    event_id    INTEGER NOT NULL REFERENCES intake_events(id)
);

CREATE TABLE IF NOT EXISTS cart_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    ordered_at  TEXT,
    status      TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'needs_clarification', 'awaiting_approval', 'approved', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS cart_session_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES cart_sessions(id),
    item_id     INTEGER NOT NULL REFERENCES grocery_items(id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES cart_sessions(id),
    approved_by     TEXT    NOT NULL,
    approval_phrase TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS clarification_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id             INTEGER NOT NULL REFERENCES grocery_items(id),
    original_name       TEXT    NOT NULL,
    original_canonical  TEXT    NOT NULL,
    resolved_name       TEXT    NOT NULL,
    resolved_canonical  TEXT    NOT NULL,
    resolved_by         TEXT    NOT NULL,
    timestamp           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS removal_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES grocery_items(id),
    item_name   TEXT    NOT NULL,
    removed_by  TEXT    NOT NULL DEFAULT 'operator',
    reason      TEXT,
    timestamp   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical       TEXT    NOT NULL UNIQUE,
    preferred_form  TEXT,
    substitutions_ok INTEGER NOT NULL DEFAULT 0,
    note            TEXT,
    updated_at      TEXT    NOT NULL
);
