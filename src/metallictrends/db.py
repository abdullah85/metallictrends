import sqlite3
from datetime import datetime, timezone


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
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
            status       TEXT NOT NULL CHECK(status IN ('success', 'failed')),
            error_detail TEXT
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
    """)
    # CREATE TABLE IF NOT EXISTS is a no-op against a DB that already has
    # backfill_attempts without this column (e.g. the live deployed DB) — this
    # fills the gap on both fresh and pre-existing databases alike.
    _ensure_column(conn, "backfill_attempts", "error_detail", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()


def save_metal_prices(conn: sqlite3.Connection, date: str, metals: dict) -> None:
    conn.executemany(
        "INSERT INTO metal_prices (date, metal, price_usd) VALUES (?, ?, ?)",
        [(date, metal, price) for metal, price in metals.items()],
    )
    conn.commit()


def save_fx_rates(conn: sqlite3.Connection, date: str, currencies: dict) -> None:
    conn.executemany(
        "INSERT INTO fx_rates (date, currency, rate_to_usd) VALUES (?, ?, ?)",
        [(date, currency, rate) for currency, rate in currencies.items()],
    )
    conn.commit()


def update_window_status(
    conn: sqlite3.Connection, start_date: str, end_date: str, status: str
) -> None:
    fetched_at = datetime.now(timezone.utc).isoformat() if status == "fetched" else None
    conn.execute(
        """UPDATE backfill_windows
           SET status = ?, fetched_at = ?
           WHERE start_date = ? AND end_date = ?""",
        (status, fetched_at, start_date, end_date),
    )
    conn.commit()


def record_backfill_attempt(
    conn: sqlite3.Connection, attempt_date: str, status: str, attempted_at: str | None = None,
    error_detail: str | None = None,
) -> None:
    """`attempted_at` defaults to the real current time, but callers that already
    have a reference "now" (e.g. run.maybe_backfill) should pass it explicitly —
    otherwise this row's timestamp silently drifts from whatever clock the
    caller used to decide *whether* to attempt, which breaks time-based spacing
    checks that compare against it. `error_detail` is the failure reason (e.g.
    the exception message from fetch_timeseries) — None for a successful attempt."""
    attempted_at = attempted_at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO backfill_attempts (attempt_date, attempted_at, status, error_detail)
           VALUES (?, ?, ?, ?)""",
        (attempt_date, attempted_at, status, error_detail),
    )
    conn.commit()


def count_backfill_attempts(
    conn: sqlite3.Connection, attempt_date: str, status: str
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM backfill_attempts WHERE attempt_date = ? AND status = ?",
        (attempt_date, status),
    ).fetchone()
    return row[0]


def last_backfill_attempt_at(conn: sqlite3.Connection, status: str) -> str | None:
    """Timestamp of the most recent attempt with the given status, across all
    days — used to space out retries, independent of the per-day attempt count."""
    row = conn.execute(
        "SELECT MAX(attempted_at) FROM backfill_attempts WHERE status = ?",
        (status,),
    ).fetchone()
    return row[0]


def record_github_sync(
    conn: sqlite3.Connection, status: str, attempted_at: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Records the outcome of a push_db_to_github() attempt. Kept separate from
    backfill_attempts since a sync can be triggered any time new rows are
    written, not only from the homepage catch-up path."""
    attempted_at = attempted_at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO github_sync_log (attempted_at, status, error_detail)
           VALUES (?, ?, ?)""",
        (attempted_at, status, error_detail),
    )
    conn.commit()


def create_login_code(
    conn: sqlite3.Connection, email: str, code_hash: str, created_at: str,
    expires_at: str, ip: str | None = None,
) -> int:
    """Stores a hashed one-time login code. Also doubles as the access log —
    every request, successful or not, leaves a row here with the requesting
    email and IP."""
    cur = conn.execute(
        """INSERT INTO admin_login_codes (email, code_hash, created_at, expires_at, ip)
           VALUES (?, ?, ?, ?, ?)""",
        (email, code_hash, created_at, expires_at, ip),
    )
    conn.commit()
    return cur.lastrowid


def count_recent_login_codes(
    conn: sqlite3.Connection, *, email: str | None = None, ip: str | None = None, since: str,
) -> int:
    """Counts codes requested at or after `since`, filtered by email and/or IP —
    the basis for rate-limiting how often a given email or network can request
    a new code."""
    query = "SELECT COUNT(*) FROM admin_login_codes WHERE created_at >= ?"
    params: list[str] = [since]
    if email is not None:
        query += " AND email = ?"
        params.append(email)
    if ip is not None:
        query += " AND ip = ?"
        params.append(ip)
    return conn.execute(query, params).fetchone()[0]


def get_active_login_code(conn: sqlite3.Connection, email: str, now: str):
    """The most recent unused, unexpired code for this email, if any. Columns
    are returned in a fixed positional order (not by name) since callers may
    or may not have sqlite3.Row set as the connection's row_factory."""
    return conn.execute(
        """SELECT rowid, email, code_hash, created_at, expires_at, used_at, attempts, ip
           FROM admin_login_codes
           WHERE email = ? AND used_at IS NULL AND expires_at > ?
           ORDER BY created_at DESC LIMIT 1""",
        (email, now),
    ).fetchone()


def increment_login_code_attempts(conn: sqlite3.Connection, row_id: int) -> int:
    """Records one more failed verification attempt against a code and returns
    the new attempt count, so the caller can invalidate it once a cap is hit —
    bounding how many guesses a brute-force attempt gets against a single
    emailed code."""
    conn.execute(
        "UPDATE admin_login_codes SET attempts = attempts + 1 WHERE rowid = ?", (row_id,)
    )
    conn.commit()
    return conn.execute(
        "SELECT attempts FROM admin_login_codes WHERE rowid = ?", (row_id,)
    ).fetchone()[0]


def mark_login_code_used(conn: sqlite3.Connection, row_id: int, used_at: str) -> None:
    """Closes out a code so it can't be verified again — on a successful login,
    or to shut down further guesses once the attempt cap is hit."""
    conn.execute(
        "UPDATE admin_login_codes SET used_at = ? WHERE rowid = ?", (used_at, row_id)
    )
    conn.commit()
