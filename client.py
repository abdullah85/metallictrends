import os
import requests
from dotenv import load_dotenv

load_dotenv()

_ENDPOINT = "https://api.metals.dev/v1/timeseries"


def fetch_timeseries(start_date: str, end_date: str) -> dict:
    """Fetch daily metal prices and FX rates for [start_date, end_date].

    Returns the full API response dict. The caller is responsible for
    splitting date ranges into 30-day windows before calling this function.
    Raises requests.exceptions.HTTPError on any non-2xx response.
    """
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
