# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [v0.3.0] - 2026-07-19

Package restructured into a `src/` layout, a recurring metals.dev backfill crash tracked down and
fixed, structured observability added for backfill and GitHub sync attempts, and the landing page's
brand mark and B2B section reworked.

### Added
- Landing page favicon (`web/assets/favicon.svg`/`.png`) and a matching header wordmark — a single
  inline SVG reading "MT MetallicTrends" in a gold gradient, avoiding raster-scaling artifacts.
- "Chart" link in the footer nav, alongside Pricing and Webmasters.
- `GET /` auto-backfills stale metal prices on each load via `maybe_backfill()`, instead of relying
  solely on a manual CLI run, throttled to at most 1 attempt per day spaced across the day.
- `error_detail` column on `backfill_attempts` and a new `github_sync_log` table recording the outcome
  of every DB-to-GitHub sync, so failures are diagnosable from the DB itself instead of only server logs.
- `sync/github.py` (formerly `db_sync.py`) pushes the SQLite DB to GitHub after writes and restores it
  on startup — a persistence workaround for Render's free-tier disk, which is otherwise wiped on every
  redeploy.
- `metallictrends-backfill`/`metallictrends-backup` console-script entry points.

### Changed
- Restructured the project into a `src/metallictrends/` package layout (`ingestion/`, `sync/`, `api/`),
  replacing the flat top-level modules.
- `needs_backfill` tolerates a 1-day gap between the latest stored date and today, and
  `backfill_recent`'s catch-up window now ends on yesterday rather than today — metals.dev may not have
  published the latest day's data yet.
- `push_db_to_github` and homepage backfill attempts are both capped at 1 attempt per day; corrected the
  default `GITHUB_BRANCH`.
- Reworded B2C/Pricing landing-page copy to match the chart's actual current features instead of
  unbuilt ones.
- Broadened the B2B section from a "jewellery store" framing to "webmasters" running any site relevant
  to gold/silver/other metal rates (jewellery, bullion, finance/investment) — renamed the nav/footer
  link, plan card, and section heading accordingly.

### Fixed
- `_require_same_origin` falls back to checking the `Referer` header's origin when `Sec-Fetch-Site` is
  absent, fixing legitimate same-origin requests that were incorrectly rejected with a 403.
- `fetch_timeseries` raises a clear `MetalsApiError` on a null/empty `rates` payload from metals.dev,
  instead of crashing downstream with a bare `AttributeError` — previously hit on every homepage load
  whose catch-up window included today.

## [v0.2.0] - 2026-07-09

Landing page rebuilt around a single interactive, multi-range price chart and served directly
from FastAPI with server-rendered live data, replacing the earlier React portfolio-tracker
prototype.

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
