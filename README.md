# MetallicTrends

Precious metals — gold, silver, platinum, and palladium — have shaped economies and driven markets for centuries. MetallicTrends is a platform for exploring how their prices evolve over time: what drives long-term trends, how different metals correlate, and what patterns emerge from years of daily market data. Currently, we use [metals.dev](https://metals.dev/) to build a resilient ingestion layer that collects historical prices for any date range you specify and stores them in a structured local database — the foundation on which analysis, visualisation, and APIs can be built.

## Overview

MetallicTrends retrieves daily price data for any date range you specify using the [metals.dev timeseries](https://www.metals.dev/docs#timeseries-endpoint) API. Because the API returns a maximum of 30 days per request, the tool automatically splits your range into windows, tracks the status of each in the database, and resumes from the last successful point if interrupted, **without** re-fetching data already retrieved. The retrieved data cannot be listed publicly and hence, the project includes a backup utility that produces timestamped copies of the SQLite database and exports price records to CSV for portability.

## Technical Highlights

- **Resumable backfill** — checkpoint state and price data share the same SQLite file, so a crash cannot leave them out of sync. Re-running the script picks up exactly where it left off.
- **Minimal API usage** — all four metals are returned in a single request per window. The tool makes only as many requests as your date range requires, keeping usage within the free tier where possible.
- **Tested without live requests** — the unit test suite uses `unittest.mock` to intercept HTTP calls and replay a recorded API response, so no API quota is consumed during testing.
- **Deliberate simplicity** — currently built on `requests`, `sqlite3`, and `python-dotenv`. No ORM, no framework, no async. Easy to read, easy to extend.

## Prerequisites

- Python 3.12+
- A [metals.dev](https://metals.dev) account with a valid API key (free tier: 100 requests/month)

## Setup

1. Clone the repository and navigate into it:

   ```bash
   git clone https://github.com/abdullah85/metallictrends.git
   cd metallictrends
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -e ".[dev]"
   ```

4. Copy the environment template and add your API key:

   ```bash
   cp .env.example .env
   ```

   Open `.env` and replace `your_api_key_here` with your metals.dev API key.

## Usage

### Run the extraction

Fetches daily prices for your specified date range and saves results to `metals.db`:

```bash
python run.py --start-date 2021-01-01 --end-date 2026-01-01
```

The script is safe to re-run. Completed windows are skipped; failed windows are retried.

### Back up the data

Copies `metals.db` to a timestamped file and exports price records to CSV:

```bash
python backup.py
```

Output is written to the `data/` directory, which is excluded from version control.

### Run the tests

```bash
pytest
```

No API key required. All HTTP calls are intercepted by `unittest.mock`.

## Project Structure

```
metallictrends/
├── client.py              # Calls the metals.dev timeseries endpoint for a given date window
├── db.py                  # SQLite schema, record insertion, and window status updates
├── run.py                 # Backfill orchestrator — the main script to run
├── backup.py              # Timestamped database backup and CSV export
├── tests/
│   ├── conftest.py        # Shared pytest fixtures available to all test files automatically
│   ├── test_client.py     # Tests for fetch_timeseries in client.py
│   ├── test_db.py         # Tests for save_metal_prices, save_fx_rates, update_window_status in db.py
│   └── test_run.py        # Tests for window chunking, state transitions, and failure handling in run.py
├── data/                  # Git-ignored — stores .db backups and CSV exports
├── media/                 # Screenshots documenting the backfill session
├── .env.example           # API key template
└── pyproject.toml         # Project metadata and dependencies
```

## Data Storage

Price records are stored in `metals.db`, a local SQLite database with three tables:

- `metal_prices` — one row per metal per day (`date`, `metal`, `price_usd`), covering gold, palladium, platinum, and silver in USD per troy ounce
- `fx_rates` — one row per currency per day (`date`, `currency`, `rate_to_usd`), covering 12 currencies returned by the API. Joining `metal_prices` with `fx_rates` on `date` gives the price of any metal in any currency.
- `backfill_windows` — one row per 30-day window tracking fetch status (`pending`, `fetched`, or `failed`)

`metals.db` is excluded from version control.

Use `python backup.py` to create a safe copy after each successful run.

## In Action

The screenshots below document a real backfill session against the metals.dev free tier (100 requests/month).

**After the first run (June 2026) — 65 of 100 requests used:**

![metals.dev dashboard showing 65/100 requests used](media/20260630_2351_metals_dev_dashboard_65_requests_used.png)

**Data confirmation — earliest record at 2021-01-01:**

![Claude Code session showing earliest data at 2021-01-01](media/20260630_2356_claude_code_earliest_data_2021_01_01.png)

**After extending the backfill to 2018-02-01 — quota fully consumed:**

![metals.dev dashboard showing 100/100 requests used](media/20260630_2358_metals_dev_dashboard_100_requests_used.png)
