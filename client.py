import os
import requests
from datetime import date
from dotenv import load_dotenv

load_dotenv()

_ENDPOINT = "https://api.metals.dev/v1/timeseries"
_MAX_WINDOW_DAYS = 30


def fetch_timeseries(start_date: str, end_date: str) -> dict:
    """Fetch daily metal prices and FX rates for [start_date, end_date].

    Returns the full API response dict. Raises ValueError if the window
    exceeds 30 days — the caller must split larger ranges before calling.
    Raises requests.exceptions.HTTPError on any non-2xx response.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if (end - start).days >= _MAX_WINDOW_DAYS:
        raise ValueError(
            f"Window from {start_date} to {end_date} exceeds {_MAX_WINDOW_DAYS} days"
        )
    response = requests.get(
        _ENDPOINT,
        headers={"Accept": "application/json"},
        params={
            "api_key": os.environ["METALS_API_KEY"],
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    response.raise_for_status()
    return response.json()
