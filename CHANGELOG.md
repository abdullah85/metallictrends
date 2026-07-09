# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `web/index.html` — self-contained landing page built around a single interactive price chart:
  metal selector (gold/silver/platinum/palladium), preset and custom date ranges, a USD/₹ unit
  toggle, permanent x/y axis labels with gridlines, and a speech-bubble-style hover readout showing
  the price and date for any point on the line.
- `api.py` — `/api/metals`, `/api/prices/{metal}`, `/api/fx/{currency}`, and `/api/widget/{metal}`
  HTTP endpoints serving data from the SQLite store.
- `GET /api/prices/{metal}` accepts `start`/`end` date-range params (uncapped) alongside the capped
  `days` window, powering the landing page's full-history range picker (1W through ALL).
- `GET /api/fx/{currency}` — daily FX rate history (uncapped `start`/`end`), so the site can convert
  the full price history to INR using each day's actual rate instead of one approximated rate.
- `GET /` is now a proper FastAPI route (Jinja2, `api.py`'s `_latest_meta`) instead of a static file:
  the hero ingot's price, batch date, "last update" date, and the trust-strip's day count are
  computed straight from the database at request time, so the page never carries a placeholder
  value for them.
- `web/assets/style.css`, `web/assets/script.js`, `web/assets/hero-preview.png` — the page's CSS,
  JS, and hero screenshot, previously inlined into `index.html` (including as base64 data URIs for
  fonts and the hero image), extracted into their own linked files. Cut `index.html` from ~210KB to
  ~44KB.
- `render.yaml` for deploying the API to Render.

### Changed
- Locked `/api/metals`, `/api/prices`, and `/api/fx` to same-origin requests.
- INR prices now use the real daily USD→INR rate for each date, instead of a single rate derived
  from the latest day and applied across the whole history.
- `index.html` now declares a proper `<!DOCTYPE html>`/`<html>`/`<head>`/`<body>` document structure
  with a charset and viewport meta tag, instead of a bare fragment with neither — the missing
  viewport tag meant mobile browsers were rendering the page at desktop width and scaling it down.

### Removed
- `frontend/` — the React + Vite portfolio tracking tool (buy/sell logging, CSV import/export against
  spot price) and its built output `web/portfolio/`, along with the inline modal used to open it from
  the landing page and the `GET /api/prices/{metal}/on/{on_date}` endpoint that only existed to
  support it. Simplifies the product surface for the current go-to-market plan.

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
