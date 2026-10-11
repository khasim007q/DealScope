-- DealScope persistence schema (SQLite, WAL). Decimals are stored as TEXT strings.
-- Timestamps are ISO-8601 UTC strings. Executed idempotently on every Repository open.

CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    mode        TEXT NOT NULL,
    stage       TEXT NOT NULL,
    run_label   TEXT NOT NULL DEFAULT 'improved',
    state_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    seq         INTEGER NOT NULL,           -- per-case ordinal; 0 = initial checkpoint at case creation
    stage       TEXT NOT NULL,
    label       TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_case ON checkpoints(case_id, id);

CREATE TABLE IF NOT EXISTS tool_runs (
    tool_run_id         TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(case_id),
    tool                TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status              TEXT NOT NULL,
    attempt_count       INTEGER NOT NULL DEFAULT 1,
    error_code          TEXT,
    error_message       TEXT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    result_count        INTEGER,
    cost_estimate       TEXT,
    cost_actual         TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_runs_case ON tool_runs(case_id, started_at);
CREATE INDEX IF NOT EXISTS idx_tool_runs_idem ON tool_runs(case_id, idempotency_key);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    kind            TEXT NOT NULL,
    subject_domain  TEXT NOT NULL,
    dedup_key       TEXT NOT NULL,
    record_json     TEXT NOT NULL,
    synthetic       INTEGER NOT NULL,
    UNIQUE (case_id, dedup_key)
);
CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id);

CREATE TABLE IF NOT EXISTS report_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    markdown    TEXT NOT NULL,
    bundle_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_case ON report_versions(case_id, id);

CREATE TABLE IF NOT EXISTS claims (
    claim_id          TEXT NOT NULL,
    case_id           TEXT NOT NULL REFERENCES cases(case_id),
    report_version_id INTEGER NOT NULL REFERENCES report_versions(id),
    claim_json        TEXT NOT NULL,
    PRIMARY KEY (claim_id, report_version_id)
);
CREATE INDEX IF NOT EXISTS idx_claims_report ON claims(report_version_id);

-- Credit ledger. Deliberately has no FK to cases: budget accounting must never fail on a missing case row.
CREATE TABLE IF NOT EXISTS usage_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    pool        TEXT NOT NULL DEFAULT 'live',  -- live | synthetic (fixture runs never consume live budget)
    tool_run_id TEXT,
    operation   TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    estimate    TEXT NOT NULL,
    actual      TEXT,
    status      TEXT NOT NULL,   -- reserved | settled_actual | settled_estimate | released | unknown
    reason      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_case ON usage_ledger(case_id, status);
CREATE INDEX IF NOT EXISTS idx_ledger_status ON usage_ledger(status);

CREATE TABLE IF NOT EXISTS response_cache (
    cache_key     TEXT PRIMARY KEY,
    endpoint      TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    api_version   TEXT NOT NULL
);

-- Append-only timeline for the UI.
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL,
    type         TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id, id);
