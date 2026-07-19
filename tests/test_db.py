import sqlite3

import pytest
from metallictrends.db import (
    init_db,
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
