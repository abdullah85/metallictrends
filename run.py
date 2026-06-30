import argparse
import sqlite3
from datetime import date, timedelta

from client import fetch_timeseries
from db import init_db, save_metal_prices, save_fx_rates, update_window_status


def chunk_date_range(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split [start_date, end_date] into consecutive windows of at most 30 days."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    windows = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=29), end)
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end + timedelta(days=1)
    return windows


def _is_fetched(conn: sqlite3.Connection, start: str, end: str) -> bool:
    row = conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ? AND end_date = ?",
        (start, end),
    ).fetchone()
    return row is not None and row[0] == "fetched"


def run_backfill(conn: sqlite3.Connection, start_date: str, end_date: str) -> None:
    """Fetch and store all windows in [start_date, end_date], skipping completed ones."""
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
        except Exception:
            update_window_status(conn, start, end, "failed")


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
