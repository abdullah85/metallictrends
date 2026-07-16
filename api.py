import sqlite3
import uvicorn
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from run import maybe_backfill
from db_sync import push_db_to_github

GRAMS_PER_TROY_OZ = 31.1034768
METALS = ("gold", "silver", "platinum", "palladium")
DB_PATH = "metals.db"

app = FastAPI(title="MetallicTrends API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)
templates = Jinja2Templates(directory="web")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _require_same_origin(request: Request) -> None:
    """Blocks calls that don't carry browser fetch-metadata proving they came from
    our own page — keeps /api/metals and /api/prices for the site's own UI only.
    Doesn't apply to /api/widget, which is meant to be embedded on other sites."""
    if request.headers.get("sec-fetch-site") not in ("same-origin", "same-site"):
        raise HTTPException(403, "This endpoint is only accessible from the MetallicTrends site.")


def _validate_metal(metal: str) -> str:
    if metal not in METALS:
        raise HTTPException(404, f"Unknown metal '{metal}'. Must be one of {METALS}.")
    return metal


def _series(conn: sqlite3.Connection, metal: str, days: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT date, price_usd FROM metal_prices
           WHERE metal = ? AND date >= date((SELECT MAX(date) FROM metal_prices), ?)
           ORDER BY date""",
        (metal, f"-{days} days"),
    ).fetchall()


def _series_range(
    conn: sqlite3.Connection, metal: str, start: str | None, end: str | None
) -> list[sqlite3.Row]:
    query = "SELECT date, price_usd FROM metal_prices WHERE metal = ?"
    params: list[str] = [metal]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    return conn.execute(query + " ORDER BY date", params).fetchall()


def _pct_change(latest: float, past: float) -> float:
    return round((latest - past) / past * 100, 2) if past else 0.0


def _snapshot(conn: sqlite3.Connection, metal: str) -> dict:
    rows = _series(conn, metal, 31)
    if not rows:
        raise HTTPException(404, f"No price data for '{metal}'.")
    prices = [r["price_usd"] for r in rows]
    return {
        "metal": metal,
        "date": rows[-1]["date"],
        "price_usd": prices[-1],
        "chg_1d_pct": _pct_change(prices[-1], prices[-2]) if len(prices) > 1 else 0.0,
        "chg_7d_pct": _pct_change(prices[-1], prices[-8]) if len(prices) > 7 else 0.0,
        "chg_30d_pct": _pct_change(prices[-1], prices[0]) if len(prices) > 29 else 0.0,
    }


def _inr_rate(conn: sqlite3.Connection, on_date: str) -> float:
    row = conn.execute(
        "SELECT rate_to_usd FROM fx_rates WHERE currency = 'INR' AND date <= ? ORDER BY date DESC LIMIT 1",
        (on_date,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "No INR exchange rate available for this date.")
    return row["rate_to_usd"]


def _latest_meta(conn: sqlite3.Connection) -> dict:
    """Server-rendered context for index.html's hero ingot and trust-strip. Computed
    from the DB at request time so the page never carries a placeholder value that
    could be mistaken for real data — there's no "default" because there's no gap for
    one to fill. Gold is the reference metal since every metal is ingested in the same
    daily run and shares an identical date range (see run.py's backfill orchestrator)."""
    snapshot = _snapshot(conn, "gold")
    count_row = conn.execute("SELECT COUNT(*) AS n FROM metal_prices WHERE metal = 'gold'").fetchone()
    latest_date = date.fromisoformat(snapshot["date"])
    return {
        "ingot_number": f"{snapshot['price_usd']:.1f}",
        "batch_date": snapshot["date"],
        "last_update": f"{latest_date.strftime('%b')} {latest_date.day}, {latest_date.year}",
        "days_count": f"{count_row['n']:,}",
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Renders the landing page itself, injecting `_latest_meta`'s values server-side.
    Must be registered before the StaticFiles mount below so it wins for the exact "/"
    path; the mount still serves everything else (assets/, etc.). If the stored data
    has fallen behind today, catches up (capped at 1 month/1 request per load,
    with failed attempts capped at 3/day and spaced at least 8h apart) before
    rendering so the page never serves data staler than it needs to. New rows are
    committed to GitHub right after — that commit is what Render's next restart
    checks out, so no separate restore step is needed anywhere in this file."""
    with _connect() as conn:
        backfilled = maybe_backfill(conn)
        context = _latest_meta(conn)
    if backfilled:
        push_db_to_github()
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/api/metals", dependencies=[Depends(_require_same_origin)])
def list_metals():
    """Latest snapshot (price + 1d/7d/30d change) for all four metals — powers the site's stat tiles."""
    with _connect() as conn:
        return [_snapshot(conn, metal) for metal in METALS]


@app.get("/api/prices/{metal}", dependencies=[Depends(_require_same_origin)])
def price_history(
    metal: str,
    days: int | None = Query(None, ge=1, le=400),
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Time series for the site's own charts. With no params, a 400-day-capped trailing
    window (not a bulk-export endpoint). With `start`/`end`, an uncapped range — used by
    the landing page's own range picker (1W through ALL) — still same-origin locked, and
    bounded by the table's own ~3,000 rows either way."""
    _validate_metal(metal)
    with _connect() as conn:
        rows = _series_range(conn, metal, start, end) if (start or end) else _series(conn, metal, days or 150)
        return [{"date": r["date"], "price_usd": r["price_usd"]} for r in rows]


@app.get("/api/fx/{currency}", dependencies=[Depends(_require_same_origin)])
def fx_history(
    currency: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Daily FX rate history (rate_to_usd), mirroring /api/prices' uncapped start/end
    range — lets the landing page convert its full price history to INR using the
    actual rate for each day instead of a single latest-day rate applied throughout."""
    currency = currency.upper()
    query = "SELECT date, rate_to_usd FROM fx_rates WHERE currency = ?"
    params: list[str] = [currency]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    with _connect() as conn:
        rows = conn.execute(query + " ORDER BY date", params).fetchall()
        if not rows:
            raise HTTPException(404, f"No FX rate data for '{currency}'.")
        return [{"date": r["date"], "rate_to_usd": r["rate_to_usd"]} for r in rows]


@app.get("/api/widget/{metal}")
def widget_payload(
    metal: str,
    unit: str = Query("oz", pattern="^(oz|10g)$"),
    currency: str = Query("usd", pattern="^(usd|inr)$"),
    premium_pct: float = Query(0.0, ge=0, le=50),
    days: int = Query(90, ge=1, le=400),
):
    """Fixed-shape payload for the embeddable jeweller widget: latest price + recent trend
    for a single metal, with an optional store premium applied. Deliberately not a general
    date-range query — this renders a display widget, it does not hand back raw historical
    data for reuse elsewhere."""
    _validate_metal(metal)
    with _connect() as conn:
        snapshot = _snapshot(conn, metal)
        rows = _series(conn, metal, days)
        prices = [r["price_usd"] for r in rows]

        if unit == "10g":
            prices = [p / GRAMS_PER_TROY_OZ * 10 for p in prices]
        if currency == "inr":
            fx = _inr_rate(conn, snapshot["date"])
            prices = [p / fx for p in prices]

        factor = 1 + premium_pct / 100
        prices = [round(p * factor, 2) for p in prices]

        return {
            "metal": metal,
            "unit": unit,
            "currency": currency,
            "premium_pct": premium_pct,
            "as_of": snapshot["date"],
            "latest_price": prices[-1],
            "chg_1d_pct": snapshot["chg_1d_pct"],
            "trend": [{"date": r["date"], "price": p} for r, p in zip(rows, prices)],
        }


if Path("web").is_dir():
    app.mount("/", StaticFiles(directory="web", html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
