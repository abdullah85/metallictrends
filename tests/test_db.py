import pytest
from db import save_metal_prices, save_fx_rates, update_window_status


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
