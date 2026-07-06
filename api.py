import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

GRAMS_PER_TROY_OZ = 31.1034768
METALS = ("gold", "silver", "platinum", "palladium")
DB_PATH = "metals.db"

app = FastAPI(title="MetallicTrends API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)


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


@app.get("/api/metals", dependencies=[Depends(_require_same_origin)])
def list_metals():
    """Latest snapshot (price + 1d/7d/30d change) for all four metals — powers the site's stat tiles."""
    with _connect() as conn:
        return [_snapshot(conn, metal) for metal in METALS]


@app.get("/api/prices/{metal}", dependencies=[Depends(_require_same_origin)])
def price_history(metal: str, days: int = Query(150, ge=1, le=400)):
    """Capped time series for the site's own charts. Not a bulk-export endpoint: `days` is clamped to 400."""
    _validate_metal(metal)
    with _connect() as conn:
        rows = _series(conn, metal, days)
        return [{"date": r["date"], "price_usd": r["price_usd"]} for r in rows]


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
