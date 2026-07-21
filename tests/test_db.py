import sqlite3
from datetime import datetime, timezone

import pytest
from metallictrends.db import (
    apply_pending_migrations,
    create_login_code,
    generate_admin_login_migration_sql,
    generate_backfill_migration_sql,
    get_active_login_code,
    init_db,
    mark_login_codes_synced,
    save_metal_prices,
    save_fx_rates,
    update_window_status,
    record_backfill_attempt,
    count_backfill_attempts,
    last_backfill_attempt_at,
    record_github_sync,
)


def test_save_metal_prices_inserts_4_rows(db_conn, mock_10_day_response):
    """save_metal_prices inserts exactly 4 rows per date into metal_prices."""
    rates = mock_10_day_response.json()["rates"]
    date = "2023-01-01"
    save_metal_prices(db_conn, date, rates[date]["metals"])
    rows = db_conn.execute("SELECT * FROM metal_prices WHERE date = ?", (date,)).fetchall()
    assert len(rows) == 4


def test_save_fx_rates_inserts_12_rows(db_conn, mock_10_day_response):
    """save_fx_rates inserts exactly 12 rows per date into fx_rates."""
    rates = mock_10_day_response.json()["rates"]
    date = "2023-01-01"
    save_fx_rates(db_conn, date, rates[date]["currencies"])
    rows = db_conn.execute("SELECT * FROM fx_rates WHERE date = ?", (date,)).fetchall()
    assert len(rows) == 12


def test_update_window_status(db_conn):
    """update_window_status correctly updates a window's status in backfill_windows."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, ?, ?)",
        ("2023-01-01", "2023-01-30", "pending", None)
    )
    db_conn.commit()
    update_window_status(db_conn, "2023-01-01", "2023-01-30", "fetched")
    row = db_conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ? AND end_date = ?",
        ("2023-01-01", "2023-01-30")
    ).fetchone()
    assert row[0] == "fetched"


def test_record_backfill_attempt_inserts_row(db_conn):
    """record_backfill_attempt inserts one row with the given date and status."""
    record_backfill_attempt(db_conn, "2023-01-01", "failed")
    rows = db_conn.execute(
        "SELECT attempt_date, status FROM backfill_attempts"
    ).fetchall()
    assert rows == [("2023-01-01", "failed")]


def test_record_backfill_attempt_uses_explicit_timestamp_when_given(db_conn):
    """An explicit `attempted_at` is stored as-is rather than the real current
    time — callers with their own reference "now" (like run.maybe_backfill) rely
    on this so the recorded timestamp matches the clock they made the decision
    with, not whatever time it happens to be when the row is written."""
    record_backfill_attempt(db_conn, "2023-01-01", "failed", "2023-01-01T06:00:00+00:00")
    row = db_conn.execute("SELECT attempted_at FROM backfill_attempts").fetchone()
    assert row[0] == "2023-01-01T06:00:00+00:00"


def test_count_backfill_attempts_filters_by_date_and_status(db_conn):
    """count_backfill_attempts only counts rows matching both the date and status."""
    record_backfill_attempt(db_conn, "2023-01-01", "failed")
    record_backfill_attempt(db_conn, "2023-01-01", "failed")
    record_backfill_attempt(db_conn, "2023-01-01", "success")
    record_backfill_attempt(db_conn, "2023-01-02", "failed")
    assert count_backfill_attempts(db_conn, "2023-01-01", "failed") == 2
    assert count_backfill_attempts(db_conn, "2023-01-01", "success") == 1
    assert count_backfill_attempts(db_conn, "2023-01-02", "failed") == 1
    assert count_backfill_attempts(db_conn, "2023-01-03", "failed") == 0


def test_last_backfill_attempt_at_returns_most_recent_timestamp(db_conn):
    """last_backfill_attempt_at returns the latest attempted_at for the given
    status, across all days — not just the current one."""
    record_backfill_attempt(db_conn, "2023-01-01", "failed")
    first = db_conn.execute(
        "SELECT attempted_at FROM backfill_attempts WHERE attempt_date = '2023-01-01'"
    ).fetchone()[0]
    record_backfill_attempt(db_conn, "2023-01-02", "failed")
    second = db_conn.execute(
        "SELECT attempted_at FROM backfill_attempts WHERE attempt_date = '2023-01-02'"
    ).fetchone()[0]
    assert last_backfill_attempt_at(db_conn, "failed") == max(first, second)


def test_last_backfill_attempt_at_returns_none_when_no_rows(db_conn):
    """With no attempts recorded yet, there's nothing to space retries against."""
    assert last_backfill_attempt_at(db_conn, "failed") is None


def test_record_backfill_attempt_stores_error_detail(db_conn):
    """A failed attempt's error_detail is persisted alongside its status."""
    record_backfill_attempt(db_conn, "2023-01-01", "failed", error_detail="ConnectionError: boom")
    row = db_conn.execute("SELECT error_detail FROM backfill_attempts").fetchone()
    assert row[0] == "ConnectionError: boom"


def test_record_backfill_attempt_error_detail_defaults_to_none(db_conn):
    """A successful attempt has no error_detail unless one is explicitly given."""
    record_backfill_attempt(db_conn, "2023-01-01", "success")
    row = db_conn.execute("SELECT error_detail FROM backfill_attempts").fetchone()
    assert row[0] is None


def test_record_github_sync_inserts_row(db_conn):
    """record_github_sync inserts one row with the given status and error detail."""
    record_github_sync(db_conn, "failed", "2023-01-01T06:00:00+00:00", error_detail="HTTP 500: boom")
    row = db_conn.execute(
        "SELECT attempted_at, status, error_detail FROM github_sync_log"
    ).fetchone()
    assert row == ("2023-01-01T06:00:00+00:00", "failed", "HTTP 500: boom")


def test_init_db_migrates_existing_backfill_attempts_table(tmp_path):
    """init_db() adds the error_detail column (and the github_sync_log table)
    to a DB created before this column existed, without losing existing rows —
    this is what lets the schema self-apply to the already-deployed DB file
    instead of requiring a manual migration step."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE backfill_attempts (
            attempt_date TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            status       TEXT NOT NULL CHECK(status IN ('success', 'failed'))
        );
    """)
    conn.execute(
        "INSERT INTO backfill_attempts (attempt_date, attempted_at, status) VALUES (?, ?, ?)",
        ("2023-01-01", "2023-01-01T00:00:00+00:00", "success"),
    )
    conn.commit()

    init_db(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(backfill_attempts)")}
    assert "error_detail" in columns
    row = conn.execute("SELECT attempt_date, status FROM backfill_attempts").fetchone()
    assert row == ("2023-01-01", "success")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "github_sync_log" in tables
    conn.close()


# --- apply_pending_migrations ---

def _write_migration(migrations_dir, filename: str, content: str) -> None:
    (migrations_dir / filename).write_text(content)


def test_apply_pending_migrations_applies_sql_and_py_migrations_in_order(tmp_path):
    """Both .sql (run verbatim) and .py (must define migrate(conn)) migrations
    are supported, and applied in filename order — the .py step here depends
    on the table the .sql step created first."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    _write_migration(
        migrations_dir, "0002_seed_foo.py",
        "def migrate(conn):\n    conn.execute('INSERT INTO foo (id) VALUES (1)')\n",
    )
    conn = sqlite3.connect(":memory:")
    applied = apply_pending_migrations(conn, migrations_dir=str(migrations_dir))
    assert applied == ["0001_create_foo.sql", "0002_seed_foo.py"]
    assert conn.execute("SELECT id FROM foo").fetchone() == (1,)


def test_apply_pending_migrations_is_idempotent(tmp_path):
    """A second call with nothing new to apply is a no-op — migrations are
    tracked by filename in schema_migrations, not re-detected by inspecting
    the schema each time."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    conn = sqlite3.connect(":memory:")
    first = apply_pending_migrations(conn, migrations_dir=str(migrations_dir))
    assert first == ["0001_create_foo.sql"]
    second = apply_pending_migrations(conn, migrations_dir=str(migrations_dir))
    assert second == []


def test_apply_pending_migrations_only_applies_newly_added_ones(tmp_path):
    """Simulates a later deploy that adds a new migration file: only the new
    one is applied, the already-recorded one is left alone."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    conn = sqlite3.connect(":memory:")
    apply_pending_migrations(conn, migrations_dir=str(migrations_dir))

    _write_migration(migrations_dir, "0002_create_bar.sql", "CREATE TABLE bar (id INTEGER PRIMARY KEY);")
    second = apply_pending_migrations(conn, migrations_dir=str(migrations_dir))
    assert second == ["0002_create_bar.sql"]


def test_apply_pending_migrations_records_filename_and_timestamp(tmp_path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_create_foo.sql", "CREATE TABLE foo (id INTEGER PRIMARY KEY);")
    conn = sqlite3.connect(":memory:")
    apply_pending_migrations(conn, migrations_dir=str(migrations_dir))
    row = conn.execute("SELECT filename, applied_at FROM schema_migrations").fetchone()
    assert row[0] == "0001_create_foo.sql"
    assert row[1]


# --- generate_backfill_migration_sql ---

def test_generate_backfill_migration_sql_returns_none_when_nothing_new(db_conn):
    assert generate_backfill_migration_sql(db_conn, "2023-01-01T00:00:00+00:00") is None


def test_generate_backfill_migration_sql_excludes_windows_fetched_before_since(db_conn):
    """A window fetched before the `since` cutoff (i.e. not from this call)
    is not included — only what's new."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, 'fetched', ?)",
        ("2023-01-01", "2023-01-10", "2023-01-01T00:00:00+00:00"),
    )
    db_conn.commit()
    assert generate_backfill_migration_sql(db_conn, "2023-06-01T00:00:00+00:00") is None


def test_generate_backfill_migration_sql_includes_new_data(db_conn):
    """Everything a successful backfill call wrote — the window, its price/fx
    rows, and the attempt record — shows up in the generated SQL."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, 'fetched', ?)",
        ("2023-01-01", "2023-01-01", "2023-06-01T12:00:00+00:00"),
    )
    save_metal_prices(db_conn, "2023-01-01", {"gold": 1900.5})
    save_fx_rates(db_conn, "2023-01-01", {"INR": 0.012})
    record_backfill_attempt(db_conn, "2023-01-01", "success", "2023-06-01T12:00:00+00:00")

    sql = generate_backfill_migration_sql(db_conn, "2023-06-01T00:00:00+00:00")

    assert "metal_prices" in sql and "gold" in sql and "1900.5" in sql
    assert "fx_rates" in sql and "INR" in sql
    assert "backfill_windows" in sql
    assert "backfill_attempts" in sql and "success" in sql


def test_generate_backfill_migration_sql_includes_failed_attempt_with_no_fetched_window(db_conn):
    """A failed backfill attempt writes no 'fetched' window, but its
    backfill_attempts row must still be persisted — otherwise the daily
    attempt-count and last-failure-timestamp throttles in maybe_backfill
    reset every time Render restarts, letting it hammer a downed
    metals.dev again right away."""
    record_backfill_attempt(db_conn, "2023-01-01", "failed", "2023-06-01T12:00:00+00:00", error_detail="boom")

    sql = generate_backfill_migration_sql(db_conn, "2023-06-01T00:00:00+00:00")

    assert sql is not None
    assert "backfill_attempts" in sql and "failed" in sql and "boom" in sql


def test_generate_backfill_migration_sql_includes_failed_window(db_conn):
    """A window that failed (not just one that succeeded) must show up too —
    otherwise its status silently reverts to whatever's in git on the next
    Render restart, defeating _is_fetched's bookkeeping of what's already
    been attempted."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, 'pending', NULL)",
        ("2023-01-01", "2023-01-30"),
    )
    db_conn.commit()
    update_window_status(db_conn, "2023-01-01", "2023-01-30", "failed")

    sql = generate_backfill_migration_sql(db_conn, "2023-01-01T00:00:00+00:00")

    assert sql is not None
    assert "backfill_windows" in sql and "failed" in sql


def test_generate_backfill_migration_sql_replay_upserts_window_status(db_conn, tmp_path):
    """A window that fails on one call and succeeds on a later retry produces
    two migration files (one per call). Replaying both in order must leave
    the window 'fetched' — an INSERT OR IGNORE would keep whichever file
    landed first (the failure) since the row already exists on the second
    file's replay, permanently misreporting a window that actually succeeded."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, 'pending', NULL)",
        ("2023-01-01", "2023-01-30"),
    )
    db_conn.commit()
    update_window_status(db_conn, "2023-01-01", "2023-01-30", "failed")
    failed_sql = generate_backfill_migration_sql(db_conn, "2023-01-01T00:00:00+00:00")

    since = datetime.now(timezone.utc).isoformat()
    update_window_status(db_conn, "2023-01-01", "2023-01-30", "fetched")
    fetched_sql = generate_backfill_migration_sql(db_conn, since)

    fresh = sqlite3.connect(":memory:")
    apply_pending_migrations(fresh)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_failed.sql").write_text(failed_sql)
    (migrations_dir / "0002_fetched.sql").write_text(fetched_sql)
    apply_pending_migrations(fresh, migrations_dir=str(migrations_dir))

    assert fresh.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ? AND end_date = ?",
        ("2023-01-01", "2023-01-30"),
    ).fetchone() == ("fetched",)


def test_generate_backfill_migration_sql_output_is_replayable(db_conn, tmp_path):
    """The generated script, run against a completely fresh DB, reproduces
    the same rows — this is exactly what apply_pending_migrations() does
    with it on the next boot."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, 'fetched', ?)",
        ("2023-01-01", "2023-01-01", "2023-06-01T12:00:00+00:00"),
    )
    save_metal_prices(db_conn, "2023-01-01", {"gold": 1900.5})
    save_fx_rates(db_conn, "2023-01-01", {"INR": 0.012})
    sql = generate_backfill_migration_sql(db_conn, "2023-06-01T00:00:00+00:00")

    fresh = sqlite3.connect(":memory:")
    apply_pending_migrations(fresh)  # real project migrations: creates the schema first

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_data.sql").write_text(sql)
    apply_pending_migrations(fresh, migrations_dir=str(migrations_dir))

    assert fresh.execute("SELECT date, metal, price_usd FROM metal_prices").fetchone() == ("2023-01-01", "gold", 1900.5)
    assert fresh.execute("SELECT date, currency, rate_to_usd FROM fx_rates").fetchone() == ("2023-01-01", "INR", 0.012)
    assert fresh.execute("SELECT status FROM backfill_windows").fetchone() == ("fetched",)


def test_apply_pending_migrations_against_the_real_project_migrations():
    """Sanity check against this repo's actual migrations/ directory (the
    default migrations_dir): a fresh in-memory DB ends up with every table
    the app expects, with no errors from the real migration files."""
    conn = sqlite3.connect(":memory:")
    applied = apply_pending_migrations(conn)
    assert "0001_initial_schema.sql" in applied
    assert "0002_add_backfill_attempts_error_detail.py" in applied
    assert "0003_add_admin_login_codes_status_and_synced_at.sql" in applied
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"metal_prices", "fx_rates", "backfill_windows", "backfill_attempts",
            "github_sync_log", "admin_login_codes"} <= tables
    columns = {row[1] for row in conn.execute("PRAGMA table_info(admin_login_codes)")}
    assert {"status", "synced_at"} <= columns


# --- admin_login_codes: status / sync tracking ---

def test_create_login_code_defaults_to_issued_status(db_conn):
    create_login_code(db_conn, "a@example.com", "hash", "2023-01-01T00:00:00+00:00", "2023-01-01T00:10:00+00:00")
    row = db_conn.execute("SELECT status, synced_at FROM admin_login_codes").fetchone()
    assert row == ("issued", None)


def test_create_login_code_records_rate_limited_status(db_conn):
    create_login_code(
        db_conn, "a@example.com", "", "2023-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00",
        ip="1.2.3.4", status="rate_limited_email",
    )
    row = db_conn.execute("SELECT status, ip FROM admin_login_codes").fetchone()
    assert row == ("rate_limited_email", "1.2.3.4")


def test_get_active_login_code_excludes_rate_limited_rows(db_conn):
    """A rate-limited log row must never be returned as something verify-code
    could match against — even if (hypothetically) its expires_at hadn't
    already passed."""
    create_login_code(
        db_conn, "a@example.com", "somehash", "2023-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00",
        status="rate_limited_ip",
    )
    assert get_active_login_code(db_conn, "a@example.com", "2023-01-01T00:00:01+00:00") is None


def test_generate_admin_login_migration_sql_returns_none_when_nothing_unsynced(db_conn):
    assert generate_admin_login_migration_sql(db_conn, "2023-01-01T00:00:00+00:00") is None


def test_generate_admin_login_migration_sql_includes_issued_rows_and_marks_them(db_conn):
    create_login_code(db_conn, "a@example.com", "hash1", "2023-01-01T00:00:00+00:00", "2023-01-01T00:10:00+00:00")
    result = generate_admin_login_migration_sql(db_conn, "2023-06-01T00:00:00+00:00")
    assert result is not None
    sql, row_ids = result
    assert "a@example.com" in sql
    assert len(row_ids) == 1

    mark_login_codes_synced(db_conn, row_ids, "2023-06-01T00:00:00+00:00")
    assert generate_admin_login_migration_sql(db_conn, "2023-06-02T00:00:00+00:00") is None


def test_generate_admin_login_migration_sql_never_includes_rate_limited_rows(db_conn):
    """Rate-limited log rows are for local visibility only — they never get
    synced to GitHub, even when an unrelated issued code is pending too."""
    create_login_code(db_conn, "a@example.com", "hash1", "2023-01-01T00:00:00+00:00", "2023-01-01T00:10:00+00:00")
    create_login_code(
        db_conn, "b@example.com", "", "2023-01-01T00:05:00+00:00", "2023-01-01T00:05:00+00:00",
        ip="9.9.9.9", status="rate_limited_email",
    )
    sql, row_ids = generate_admin_login_migration_sql(db_conn, "2023-06-01T00:00:00+00:00")
    assert "a@example.com" in sql
    assert "b@example.com" not in sql
    assert "rate_limited_email" not in sql
    assert len(row_ids) == 1

    mark_login_codes_synced(db_conn, row_ids, "2023-06-01T00:00:00+00:00")
    # The rate-limited row is still there locally, just never synced.
    remaining = db_conn.execute(
        "SELECT email, synced_at FROM admin_login_codes WHERE status = 'rate_limited_email'"
    ).fetchone()
    assert remaining == ("b@example.com", None)


def test_generate_admin_login_migration_sql_output_is_replayable_without_duplication(db_conn, tmp_path):
    """The replayed row comes back with synced_at already set (not NULL) —
    otherwise a fresh instance would think it's unsynced and re-commit it
    forever, since admin_login_codes has no unique constraint to fall back on."""
    create_login_code(db_conn, "a@example.com", "hash1", "2023-01-01T00:00:00+00:00", "2023-01-01T00:10:00+00:00")
    sql, _row_ids = generate_admin_login_migration_sql(db_conn, "2023-06-01T00:00:00+00:00")

    fresh = sqlite3.connect(":memory:")
    apply_pending_migrations(fresh)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_data.sql").write_text(sql)
    apply_pending_migrations(fresh, migrations_dir=str(migrations_dir))

    row = fresh.execute("SELECT email, status, synced_at FROM admin_login_codes").fetchone()
    assert row == ("a@example.com", "issued", "2023-06-01T00:00:00+00:00")
