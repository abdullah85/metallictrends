CREATE TABLE IF NOT EXISTS metal_prices (
    date    TEXT NOT NULL,
    metal   TEXT NOT NULL,
    price_usd REAL NOT NULL,
    UNIQUE(date, metal)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    date        TEXT NOT NULL,
    currency    TEXT NOT NULL,
    rate_to_usd REAL NOT NULL,
    UNIQUE(date, currency)
);
CREATE TABLE IF NOT EXISTS backfill_windows (
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK(status IN ('pending', 'fetched', 'failed')),
    fetched_at TEXT,
    UNIQUE(start_date, end_date)
);
CREATE TABLE IF NOT EXISTS backfill_attempts (
    attempt_date TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    status       TEXT NOT NULL CHECK(status IN ('success', 'failed'))
);
CREATE TABLE IF NOT EXISTS github_sync_log (
    attempted_at TEXT NOT NULL,
    status       TEXT NOT NULL CHECK(status IN ('success', 'failed')),
    error_detail TEXT
);
CREATE TABLE IF NOT EXISTS admin_login_codes (
    email      TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    ip         TEXT
);
