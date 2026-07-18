import sqlite3
import pytest
import requests
from unittest.mock import Mock
from datetime import date, timedelta
from metallictrends.db import init_db

from sample_data import SAMPLE_10_DAY_RATES


@pytest.fixture
def db_conn():
    """In-memory SQLite connection with full schema created.
    Isolated per test — closed and discarded after each test function."""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    """Set a dummy API key for every test so client.py can be imported without a .env file."""
    monkeypatch.setenv("METALS_API_KEY", "test-key")


def _extend_rates(start, end):
    """Synthesises a rates dict for any date range by cycling through
    SAMPLE_10_DAY_RATES entries. Each day gets distinct metals and currency
    values rather than identical ones."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    sample_entries = list(SAMPLE_10_DAY_RATES.values())
    dates = [
        (start_date + timedelta(days=i)).isoformat()
        for i in range((end_date - start_date).days + 1)
    ]
    return {
        d: {**sample_entries[i % len(sample_entries)], "date": d}
        for i, d in enumerate(dates)
    }


def _make_mock_response(start, end, rates):
    """Builds a Mock that behaves like a successful requests.Response.
    raise_for_status() does nothing and json() returns the full API response
    dict with the given rates."""
    mock = Mock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "status": "success",
        "currency": "USD",
        "unit": "toz",
        "start_date": start,
        "end_date": end,
        "rates": rates,
    }
    return mock


@pytest.fixture
def mock_1_day_response():
    """Valid API response for a single day (minimum date range).
    Uses the exact values from 2023-01-01 in the metals.dev docs sample."""
    rates = {"2023-01-01": SAMPLE_10_DAY_RATES["2023-01-01"]}
    return _make_mock_response("2023-01-01", "2023-01-01", rates)


@pytest.fixture
def mock_10_day_response():
    """Valid API response for 10 days using the exact sample
    from the metals.dev timeseries endpoint documentation."""
    return _make_mock_response("2023-01-01", "2023-01-10", SAMPLE_10_DAY_RATES)


@pytest.fixture
def mock_30_day_response():
    """Valid API response for 30 days (maximum allowed window).
    Values are synthesised by cycling through the 10-day sample — each day
    gets distinct values. Shape and count are what the tests verify."""
    rates = _extend_rates("2023-01-01", "2023-01-30")
    return _make_mock_response("2023-01-01", "2023-01-30", rates)


@pytest.fixture
def fake_fetch_timeseries():
    """A stand-in for client.fetch_timeseries that returns synthetic data for
    any [start, end] window, unlike the fixed-range mock_*_response fixtures above.
    Needed for backfill flows whose date range is computed at test time (e.g.
    relative to `date.today()`) rather than hardcoded."""
    def _fetch(start, end):
        return {
            "status": "success",
            "currency": "USD",
            "unit": "toz",
            "start_date": start,
            "end_date": end,
            "rates": _extend_rates(start, end),
        }
    return _fetch


@pytest.fixture
def mock_invalid_key_response():
    """Simulates a 401 Unauthorized response from the API.
    raise_for_status() raises HTTPError with e.response.status_code == 401."""
    http_response = Mock()
    http_response.status_code = 401
    mock = Mock()
    mock.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "401 Unauthorized: Invalid API key", response=http_response
    )
    return mock


@pytest.fixture
def mock_http_error_response():
    """Simulates a server-side failure (500) or rate limit error (429).
    raise_for_status() raises HTTPError with e.response.status_code == 500."""
    http_response = Mock()
    http_response.status_code = 500
    mock = Mock()
    mock.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "500 Internal Server Error", response=http_response
    )
    return mock
