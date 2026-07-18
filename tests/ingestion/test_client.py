import pytest
import requests
from unittest.mock import patch
from metallictrends.ingestion.client import fetch_timeseries


def test_fetch_timeseries_returns_rates_for_10_days(mock_10_day_response):
    """fetch_timeseries returns a dict with one rates entry per requested day."""
    with patch("metallictrends.ingestion.client.requests.get", return_value=mock_10_day_response):
        result = fetch_timeseries("2023-01-01", "2023-01-10")
    assert len(result["rates"]) == 10


def test_fetch_timeseries_raises_on_invalid_key(mock_invalid_key_response):
    """fetch_timeseries propagates HTTPError with status_code 401 on a bad API key."""
    with patch("metallictrends.ingestion.client.requests.get", return_value=mock_invalid_key_response):
        with pytest.raises(requests.exceptions.HTTPError) as exc_info:
            fetch_timeseries("2023-01-01", "2023-01-10")
    assert exc_info.value.response.status_code == 401


def test_fetch_timeseries_raises_on_server_error(mock_http_error_response):
    """fetch_timeseries propagates HTTPError with status_code 500 on a server failure."""
    with patch("metallictrends.ingestion.client.requests.get", return_value=mock_http_error_response):
        with pytest.raises(requests.exceptions.HTTPError) as exc_info:
            fetch_timeseries("2023-01-01", "2023-01-10")
    assert exc_info.value.response.status_code == 500


def test_fetch_timeseries_raises_on_window_exceeding_30_days():
    """fetch_timeseries raises ValueError when the window is more than 30 days."""
    with pytest.raises(ValueError):
        fetch_timeseries("2023-01-01", "2023-02-01")
