import argparse
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from metallictrends.ingestion.client import fetch_timeseries
from metallictrends.db import (
    init_db,
    save_metal_prices,
    save_fx_rates,
    update_window_status,
    record_backfill_attempt,
    count_backfill_attempts,
    last_backfill_attempt_at,
)

logger = logging.getLogger(__name__)

MAX_DAILY_BACKFILL_ATTEMPTS = 1
# Retries are spaced out evenly across a day given the cap above (24h / 3 = 8h),
# so a burst of homepage traffic can't burn through the day's attempts in seconds.
MIN_BACKFILL_RETRY_INTERVAL = timedelta(hours=24) / MAX_DAILY_BACKFILL_ATTEMPTS


def chunk_date_range(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split [start_date, end_date] into consecutive windows of at most 30 days."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    windows = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=30), end)
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end + timedelta(days=1)
    return windows


def _is_fetched(conn: sqlite3.Connection, start: str, end: str) -> bool:
    row = conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ? AND end_date = ?",
        (start, end),
    ).fetchone()
    return row is not None and row[0] == "fetched"


def needs_backfill(conn: sqlite3.Connection, today: date | None = None) -> bool:
    """True once the latest stored metal_prices date has fallen behind today.
    False on an empty table — there's no "last date" yet for this check to act
    on; seeding an empty DB is the CLI backfill's job, not this catch-up path's."""
    row = conn.execute("SELECT MAX(date) AS d FROM metal_prices").fetchone()
    last = row[0]
    if last is None:
        return False
    today = today or date.today()
    timedelta = today - date.fromisoformat(last)
    # Tolerate a gap of 1 day as we may not have the required data yet on metals.dev
    return timedelta.days > 1 # Logic can be improved further


def backfill_recent(conn: sqlite3.Connection, today: date | None = None) -> tuple[bool, str | None]:
    """Catch up from the day after the latest stored date, capped at 1 month
    (30 days) thus capping the backend call to at most 1 request.
    Assumes needs_backfill(conn, today) is already True. Returns (True, None)
    if the window fetched successfully, (False, error_detail) if it failed."""
    row = conn.execute("SELECT MAX(date) AS d FROM metal_prices").fetchone()
    last = date.fromisoformat(row[0])
    today = today or date.today()
    start = last + timedelta(days=1)
    end = min(start + timedelta(days=30), today)
    return run_backfill(conn, start.isoformat(), end.isoformat())


def maybe_backfill(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    """Homepage entry point: backfills recent data when the DB has fallen behind.
    Two independent guards protect a downed metals.dev from every page load
    turning into a doomed API call: a hard cap of 3 failed attempts per day, and
    a minimum spacing of MIN_BACKFILL_RETRY_INTERVAL (8h) since the last failure
    — so retries land spread through the day rather than bursting the moment
    traffic arrives. Successful catch-up isn't throttled by either guard — a very
    stale DB may take several page loads (or days) to fully catch up, advancing
    by up to 30 days each time.

    Returns True iff a backfill attempt actually ran and wrote to the DB
    (rows, and/or the backfill_attempts record) — i.e. iff the caller has
    something new worth persisting. Every early return below is guard-only
    and touches nothing, so False is safe to treat as "DB unchanged"."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    if not needs_backfill(conn, today):
        return False

    today_str = today.isoformat()
    if count_backfill_attempts(conn, today_str, "failed") >= MAX_DAILY_BACKFILL_ATTEMPTS:
        logger.warning(
            "Skipping homepage backfill for %s: already failed %d times today",
            today_str, MAX_DAILY_BACKFILL_ATTEMPTS,
        )
        return False

    last_failed_at = last_backfill_attempt_at(conn, "failed")
    if last_failed_at is not None:
        elapsed = now - datetime.fromisoformat(last_failed_at)
        if elapsed < MIN_BACKFILL_RETRY_INTERVAL:
            logger.info(
                "Skipping homepage backfill: last failed attempt was %s ago, "
                "minimum %s between retries", elapsed, MIN_BACKFILL_RETRY_INTERVAL,
            )
            return False

    success, error_detail = backfill_recent(conn, today)
    if success:
        record_backfill_attempt(conn, today_str, "success", now.isoformat())
    else:
        logger.error("Homepage backfill attempt failed for %s", today_str)
        record_backfill_attempt(conn, today_str, "failed", now.isoformat(), error_detail=error_detail)
    return True


def run_backfill(conn: sqlite3.Connection, start_date: str, end_date: str) -> tuple[bool, str | None]:
    """Fetch and store all windows in [start_date, end_date], skipping completed ones.
    Returns (True, None) if every window ended up 'fetched', (False, error_detail)
    if any failed — error_detail is the most recent failure's message, since a
    homepage-triggered call always covers exactly one window anyway."""
    all_fetched = True
    last_error_detail = None
    for start, end in chunk_date_range(start_date, end_date):
        if _is_fetched(conn, start, end):
            continue

        conn.execute(
            """INSERT OR IGNORE INTO backfill_windows (start_date, end_date, status, fetched_at)
               VALUES (?, ?, 'pending', NULL)""",
            (start, end),
        )
        conn.commit()

        try:
            data = fetch_timeseries(start, end)
            for day, day_data in data["rates"].items():
                save_metal_prices(conn, day, day_data["metals"])
                save_fx_rates(conn, day, day_data["currencies"])
            update_window_status(conn, start, end, "fetched")
        except Exception as exc:
            update_window_status(conn, start, end, "failed")
            logger.warning("Failed to fetch window %s to %s", start, end, exc_info=True)
            all_fetched = False
            last_error_detail = str(exc)
    return all_fetched, last_error_detail


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill metals price data from metals.dev")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--db", default="metals.db", help="SQLite database file (default: metals.db)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        run_backfill(conn, args.start_date, args.end_date)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
