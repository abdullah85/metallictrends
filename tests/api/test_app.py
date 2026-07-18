import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import metallictrends.api.app as api
from metallictrends.db import init_db


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    """Points api.py at a fresh, file-backed SQLite DB (not :memory:, which would
    reset on every new connection) so the connection api._connect() opens per
    request can see data seeded by the test and any writes made during the request."""
    db_path = tmp_path / "metals.db"
    conn = sqlite3.connect(db_path)
    init_db(conn)
    conn.close()
    monkeypatch.setattr(api, "DB_PATH", str(db_path))
    return str(db_path)


def _seed_gold_series(db_path: str, last_date: str, days: int = 35) -> None:
    """Seeds `days` consecutive days of gold prices (and INR fx rates) ending on
    `last_date`, so `_latest_meta` has enough history to render without hitting
    the 404s _snapshot raises for missing data."""
    conn = sqlite3.connect(db_path)
    end = date.fromisoformat(last_date)
    for i in range(days):
        d = (end - timedelta(days=days - 1 - i)).isoformat()
        conn.execute(
            "INSERT INTO metal_prices (date, metal, price_usd) VALUES (?, 'gold', ?)",
            (d, 1900.0 + i),
        )
        conn.execute(
            "INSERT INTO fx_rates (date, currency, rate_to_usd) VALUES (?, 'INR', 0.012)",
            (d,),
        )
    conn.commit()
    conn.close()


def _max_gold_date(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT MAX(date) FROM metal_prices WHERE metal = 'gold'").fetchone()
    conn.close()
    return row[0]


def test_homepage_triggers_backfill_when_data_is_stale(api_db, fake_fetch_timeseries):
    """GET / backfills the gap first when the DB's last date is behind today, so
    the page renders with freshly caught-up data instead of stale data."""
    stale_last_date = (date.today() - timedelta(days=5)).isoformat()
    _seed_gold_series(api_db, stale_last_date)

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        response = TestClient(api.app).get("/")

    assert response.status_code == 200
    mock_fetch.assert_called_once_with(
        (date.fromisoformat(stale_last_date) + timedelta(days=1)).isoformat(),
        date.today().isoformat(),
    )
    assert _max_gold_date(api_db) == date.today().isoformat()


def test_homepage_skips_backfill_when_data_is_current(api_db, fake_fetch_timeseries):
    """GET / makes no outbound requests when the DB is already caught up to today —
    the '>' check must be strict, not '>='."""
    _seed_gold_series(api_db, date.today().isoformat())

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        response = TestClient(api.app).get("/")

    assert response.status_code == 200
    mock_fetch.assert_not_called()


def test_homepage_backfill_capped_at_1_request_when_very_stale(api_db, fake_fetch_timeseries):
    """GET / makes at most 1 backfill request even when the DB has been stale for
    much longer than a month, so one page load can't trigger an unbounded fetch —
    catching up the rest happens on subsequent loads."""
    very_stale_last_date = (date.today() - timedelta(days=365)).isoformat()
    _seed_gold_series(api_db, very_stale_last_date)

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        response = TestClient(api.app).get("/")

    assert response.status_code == 200
    assert mock_fetch.call_count == 1
    assert _max_gold_date(api_db) < date.today().isoformat()


def test_homepage_backfill_retries_once_per_burst_of_traffic(api_db):
    """A burst of homepage hits against a downed metals.dev makes only one real
    backfill attempt, not one per visit — retries are spaced out (currently 8h
    apart) rather than firing on every page load, so a brief traffic spike can't
    hammer a downed API."""
    stale_last_date = (date.today() - timedelta(days=5)).isoformat()
    _seed_gold_series(api_db, stale_last_date)

    with patch(
        "metallictrends.ingestion.run.fetch_timeseries", side_effect=ConnectionError("metals.dev is down")
    ) as mock_fetch:
        for _ in range(5):
            response = TestClient(api.app).get("/")
            assert response.status_code == 200

    assert mock_fetch.call_count == 1
