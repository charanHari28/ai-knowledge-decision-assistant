-- SQLite schema for the AI Knowledge & Decision Assistant.
-- Every tenant-owned table carries org_id, and every query in the code filters on it.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS organizations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,          -- pbkdf2_sha256$iterations$salt$hash
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Admin dashboard sessions. Only the SHA-256 of the session token is stored.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,
    org_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    expires_at TEXT    NOT NULL
);

-- One assistant per organization. The token is a random public identifier (like a
-- publishable key): it can only call /api/ask for its own org, never admin APIs.
CREATE TABLE IF NOT EXISTS assistants (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id     INTEGER NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    token      TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    rotated_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id       INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    filename     TEXT    NOT NULL,           -- original name shown in references
    stored_path  TEXT    NOT NULL,           -- private path under data/uploads/<org_id>/
    size_bytes   INTEGER NOT NULL,
    page_count   INTEGER NOT NULL,
    chunk_count  INTEGER NOT NULL DEFAULT 0,
    rule_count   INTEGER NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL DEFAULT 'processing',   -- processing | ready | failed
    error        TEXT,
    uploaded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(org_id);

-- Page-aware text chunks used for retrieval.
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    ordinal     INTEGER NOT NULL,
    text        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_org ON chunks(org_id);

-- Structured decision rules compiled from the documents at ingest time.
-- These are what the System-1 Boolean/Choice/Score models evaluate at question time.
CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    policy      TEXT    NOT NULL,            -- e.g. "Merit Scholarship"
    attribute   TEXT    NOT NULL,            -- canonical key, e.g. "gpa"
    label       TEXT    NOT NULL,            -- human label, e.g. "Cumulative GPA"
    value_type  TEXT    NOT NULL,            -- number | boolean | choice
    operator    TEXT    NOT NULL,            -- >= > <= < == != in not_in
    value       TEXT    NOT NULL,            -- JSON-encoded
    aliases     TEXT    NOT NULL DEFAULT '[]',  -- JSON list of words that refer to the attribute
    weight      REAL    NOT NULL DEFAULT 1.0,
    source_text TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rules_org ON rules(org_id);

-- Usage log for dashboard counters and auditing.
CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id        INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    question      TEXT    NOT NULL,
    question_type TEXT,
    outcome       TEXT    NOT NULL,          -- answered | not_found | needs_review | error
    decision      TEXT,                      -- e.g. ELIGIBLE / NOT_ELIGIBLE / NEEDS_INFO
    latency_ms    INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_questions_org ON questions(org_id);
