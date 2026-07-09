# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `web/index.html` — a browser dashboard for viewing stored price data, with finalized frontend aesthetics.
- `api.py` — a `/api/metals` and `/api/prices` HTTP API serving data from the SQLite store.
- `render.yaml` for deploying the API to Render.
- `frontend/` — a React + Vite portfolio tracking tool: log metal purchases, chart holdings performance
  against spot price, and import/export transactions as CSV. Built and served from `web/portfolio/`,
  opened as an inline modal from the dashboard's stat tiles.
- `GET /api/prices/{metal}` now accepts `start`/`end` date-range params (uncapped, for the portfolio
  tool's arbitrary purchase-date lookback) alongside the existing capped `days` window.
- `GET /api/prices/{metal}/on/{on_date}` — price on a given date, or the closest prior trading date,
  used to default the portfolio tool's price field.

### Changed
- Locked `/api/metals` and `/api/prices` to same-origin requests.
- Dashboard stat tiles are now clickable, opening the portfolio tracker modal.

### Fixed
- Added `UNIQUE` constraints on schema tables and reused `init_db` in tests to prevent duplicate rows.

## [v0.1.0] - 2026-07-01

Initial release: a resumable, checkpointed data ingestion pipeline for daily precious metals
prices (gold, silver, platinum, palladium) from the [metals.dev](https://metals.dev/) API.

### Added
- `client.py` — `fetch_timeseries` client for the metals.dev timeseries endpoint, with guards
  against windows exceeding the API's 30-day limit.
- `db.py` — SQLite storage layer with `save_metal_prices`, `save_fx_rates`, and
  `update_window_status` for checkpointed ingestion.
- `run.py` — `chunk_date_range` and `run_backfill` orchestrator with a CLI entrypoint, splitting
  arbitrary date ranges into 30-day windows and resuming from the last successful window.
- `backup.py` — `backup_db` and `export_csv` utilities, with a CLI entrypoint, for producing
  timestamped database backups and portable CSV exports.
- Unit test suite (`tests/`) covering the client, database layer, and backfill orchestrator using
  `pytest` and `unittest.mock`, with recorded API responses so no live quota is consumed.
- `README.md` with setup instructions, screenshots, and sample query output.
- `APIResearch.md` documenting the evaluation of metals price API providers.

### Fixed
- 30-day window boundary check in the client and backfill orchestrator.
