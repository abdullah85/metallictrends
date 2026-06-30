import pytest
import requests
from datetime import date
from unittest.mock import patch, Mock
from run import chunk_date_range, run_backfill


# --- chunk_date_range ---

def test_chunk_date_range_single_window():
    """A range of 30 days or fewer produces exactly one window."""
    windows = chunk_date_range("2023-01-01", "2023-01-30")
    assert windows == [("2023-01-01", "2023-01-30")]


def test_chunk_date_range_splits_into_multiple_windows():
    """A range longer than 30 days is split into multiple windows of at most 30 days each."""
    windows = chunk_date_range("2023-01-01", "2023-03-01")
    assert len(windows) > 1
    for start, end in windows:
        assert (date.fromisoformat(end) - date.fromisoformat(start)).days <= 30


def test_chunk_date_range_covers_full_range():
    """The first window starts on start_date and the last window ends on end_date."""
    windows = chunk_date_range("2023-01-01", "2023-03-01")
    assert windows[0][0] == "2023-01-01"
    assert windows[-1][1] == "2023-03-01"


# --- run_backfill ---

def test_backfill_marks_window_fetched_on_success(db_conn, mock_10_day_response):
    """run_backfill marks a window as 'fetched' after a successful API call."""
    with patch("run.fetch_timeseries", return_value=mock_10_day_response.json()):
        run_backfill(db_conn, "2023-01-01", "2023-01-10")
    row = db_conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ?", ("2023-01-01",)
    ).fetchone()
    assert row[0] == "fetched"


def test_backfill_marks_window_failed_on_http_error(db_conn):
    """run_backfill marks a window as 'failed' when fetch_timeseries raises HTTPError."""
    http_response = Mock()
    http_response.status_code = 500
    with patch(
        "run.fetch_timeseries",
        side_effect=requests.exceptions.HTTPError(response=http_response),
    ):
        run_backfill(db_conn, "2023-01-01", "2023-01-10")
    row = db_conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ?", ("2023-01-01",)
    ).fetchone()
    assert row[0] == "failed"


def test_backfill_skips_already_fetched_windows(db_conn, mock_10_day_response):
    """run_backfill does not call fetch_timeseries for windows already marked 'fetched'."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, ?, ?)",
        ("2023-01-01", "2023-01-10", "fetched", "2024-01-01T00:00:00+00:00"),
    )
    db_conn.commit()
    with patch("run.fetch_timeseries") as mock_fetch:
        run_backfill(db_conn, "2023-01-01", "2023-01-10")
    mock_fetch.assert_not_called()
