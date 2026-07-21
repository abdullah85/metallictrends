import importlib.util
import os
import sqlite3
from datetime import datetime, timezone

MIGRATIONS_DIR = "migrations"


def apply_pending_migrations(conn: sqlite3.Connection, migrations_dir: str = MIGRATIONS_DIR) -> list[str]:
    """Applies any migration in `migrations_dir` not yet recorded in
    schema_migrations, in filename order, and returns the filenames actually
    applied. Idempotent by filename (not by re-inspecting the schema each
    time), so it's safe to call repeatedly against the same database.

    Migrations are .sql (run verbatim as a script) or .py (must define
    migrate(conn)) — .py is for changes SQLite can't express safely as plain
    SQL, e.g. adding a column only if it isn't already there, since SQLite
    has no "ADD COLUMN IF NOT EXISTS"."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}
    pending = sorted(
        f for f in os.listdir(migrations_dir)
        if f.endswith((".sql", ".py")) and f not in applied
    )

    newly_applied = []
    for filename in pending:
        path = os.path.join(migrations_dir, filename)
        if filename.endswith(".sql"):
            with open(path) as f:
                conn.executescript(f.read())
        else:
            spec = importlib.util.spec_from_file_location(filename[:-3], path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.migrate(conn)
        conn.execute(
            "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
            (filename, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        newly_applied.append(filename)
    return newly_applied


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def generate_backfill_migration_sql(conn: sqlite3.Connection, since: str) -> str | None:
    """Builds a data-migration SQL script replaying whatever a backfill call
    just wrote: any backfill_windows row touched at or after `since`
    (captured just before the call) — whether it ended up 'fetched' or
    'failed' — this ensures that we do not repeat the same calls ensuring a cool off
    period set to a day currently.

    This is the alternative to committing the whole binary metals.db file on
    every backfill: a small, diffable, human-readable script that
    apply_pending_migrations() replays on a freshly-restored DB after a
    Render restart, instead of restoring a giant opaque blob."""
    windows = conn.execute(
        """SELECT start_date, end_date, status, fetched_at FROM backfill_windows
           WHERE fetched_at >= ? ORDER BY start_date""",
        (since,),
    ).fetchall()
    attempts = conn.execute(
        """SELECT attempt_date, attempted_at, status, error_detail
           FROM backfill_attempts WHERE attempted_at >= ? ORDER BY attempted_at""",
        (since,),
    ).fetchall()
    if not windows and not attempts:
        return None

    lines = []
    for start_date, end_date, status, fetched_at in windows:
        for d, metal, price_usd in conn.execute(
            "SELECT date, metal, price_usd FROM metal_prices WHERE date BETWEEN ? AND ? ORDER BY date, metal",
            (start_date, end_date),
        ):
            lines.append(
                f"INSERT OR IGNORE INTO metal_prices (date, metal, price_usd) "
                f"VALUES ({_sql_literal(d)}, {_sql_literal(metal)}, {price_usd});"
            )
        for d, currency, rate_to_usd in conn.execute(
            "SELECT date, currency, rate_to_usd FROM fx_rates WHERE date BETWEEN ? AND ? ORDER BY date, currency",
            (start_date, end_date),
        ):
            lines.append(
                f"INSERT OR IGNORE INTO fx_rates (date, currency, rate_to_usd) "
                f"VALUES ({_sql_literal(d)}, {_sql_literal(currency)}, {rate_to_usd});"
            )
        lines.append(
            f"INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) "
            f"VALUES ({_sql_literal(start_date)}, {_sql_literal(end_date)}, {_sql_literal(status)}, {_sql_literal(fetched_at)}) "
            f"ON CONFLICT(start_date, end_date) DO UPDATE SET status = excluded.status, fetched_at = excluded.fetched_at;"
        )
    for attempt_date, attempted_at, status, error_detail in attempts:
        lines.append(
            f"INSERT INTO backfill_attempts (attempt_date, attempted_at, status, error_detail) "
            f"VALUES ({_sql_literal(attempt_date)}, {_sql_literal(attempted_at)}, "
            f"{_sql_literal(status)}, {_sql_literal(error_detail)});"
        )
    return "\n".join(lines) + "\n"


def init_db(conn: sqlite3.Connection) -> None:
    """Kept as the entry point existing callers (the CLI backfill/backup
    tools, tests, db_sync) already use — just applies whatever migrations
    are pending."""
    apply_pending_migrations(conn)


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
    """`fetched_at` is set on every status transition, and thus,
    it doubles as "last touched at" so generate_backfill_migration_sql can
    pick up a failed window's status change too, otherwise a failure made
    right before a Render restart is invisible to the next migration and
    the window silently reverts to whatever's in git."""
    fetched_at = datetime.now(timezone.utc).isoformat()
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
    expires_at: str, ip: str | None = None, status: str = "issued",
) -> int:
    """Stores a hashed one-time login code, or logs a rejected request —
    `status` is "issued" for a real code, or "rate_limited_email"/
    "rate_limited_ip" for a request that was refused for exceeding one of
    those caps (still worth logging, for tracking abuse patterns). Either
    way this doubles as the access log: every request leaves a row here with
    the requesting email and IP, synced to GitHub separately (see
    generate_admin_login_migration_sql) once its login flow concludes."""
    cur = conn.execute(
        """INSERT INTO admin_login_codes (email, code_hash, created_at, expires_at, ip, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (email, code_hash, created_at, expires_at, ip, status),
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
    """The most recent unused, unexpired, actually-issued code for this
    email, if any — excludes rate-limit log rows explicitly (not just via
    their already-expired expires_at) so they can never be matched here.
    Columns are returned in a fixed positional order (not by name) since
    callers may or may not have sqlite3.Row set as the connection's
    row_factory."""
    return conn.execute(
        """SELECT rowid, email, code_hash, created_at, expires_at, used_at, attempts, ip
           FROM admin_login_codes
           WHERE email = ? AND status = 'issued' AND used_at IS NULL AND expires_at > ?
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


def generate_admin_login_migration_sql(
    conn: sqlite3.Connection, synced_at: str
) -> tuple[str, list[int]] | None:
    """Builds a data-migration SQL script replaying admin_login_codes rows
    not yet synced (synced_at IS NULL) — only ones with status='issued'.
    Rate-limited log rows are deliberately excluded and stay local-only
    forever: they're for your own local visibility into abuse patterns, not
    something worth a GitHub commit. Returns (sql, row_ids) so the caller can
    mark exactly those rows synced locally once the commit actually succeeds
    (see mark_login_codes_synced) — a failed push leaves them unsynced, to
    be retried on the next successful login.

    The generated INSERTs set synced_at = the given `synced_at` (not NULL) —
    critical, since these rows get replayed by apply_pending_migrations() on
    a freshly-restored DB after a restart. Without this, a replayed row would
    look unsynced on the new instance and get bundled into yet another
    migration file the next time someone logs in, duplicating it forever
    (admin_login_codes has no unique constraint to fall back on).

    Uses synced_at rather than a timestamp cutoff because a code is
    requested in one HTTP request and verified in a separate, later one, so
    there's no single "since" that spans both."""
    rows = conn.execute(
        """SELECT rowid, email, code_hash, created_at, expires_at, used_at, attempts, ip, status
           FROM admin_login_codes WHERE synced_at IS NULL AND status = 'issued' ORDER BY created_at"""
    ).fetchall()
    if not rows:
        return None

    lines = []
    row_ids = []
    for rowid, email, code_hash, created_at, expires_at, used_at, attempts, ip, status in rows:
        row_ids.append(rowid)
        lines.append(
            f"INSERT OR IGNORE INTO admin_login_codes "
            f"(email, code_hash, created_at, expires_at, used_at, attempts, ip, status, synced_at) "
            f"VALUES ({_sql_literal(email)}, {_sql_literal(code_hash)}, {_sql_literal(created_at)}, "
            f"{_sql_literal(expires_at)}, {_sql_literal(used_at)}, {attempts}, "
            f"{_sql_literal(ip)}, {_sql_literal(status)}, {_sql_literal(synced_at)});"
        )
    return "\n".join(lines) + "\n", row_ids


def mark_login_codes_synced(conn: sqlite3.Connection, row_ids: list[int], synced_at: str) -> None:
    conn.executemany(
        "UPDATE admin_login_codes SET synced_at = ? WHERE rowid = ?",
        [(synced_at, rid) for rid in row_ids],
    )
    conn.commit()
