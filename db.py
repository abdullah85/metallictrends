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
    """)


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
