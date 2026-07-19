import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import time
import uvicorn
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from metallictrends.db import (
    apply_pending_migrations,
    count_recent_login_codes,
    create_login_code,
    generate_admin_login_migration_sql,
    generate_backfill_migration_sql,
    get_active_login_code,
    increment_login_code_attempts,
    mark_login_code_used,
    mark_login_codes_synced,
)
from metallictrends.ingestion.run import maybe_backfill
from metallictrends.notify.email import send_otp_email
from metallictrends.sync.github import commit_migration_file

logging.basicConfig(level=logging.INFO)

GRAMS_PER_TROY_OZ = 31.1034768
METALS = ("gold", "silver", "platinum", "palladium")
DB_PATH = "metals.db"

_SESSION_COOKIE = "mt_admin_session"
_SESSION_TTL_SECONDS = 15 * 60
_CODE_TTL_SECONDS = 10 * 60
_MAX_CODE_ATTEMPTS = 5
_MAX_CODE_REQUESTS_PER_EMAIL_PER_HOUR = 7
_MAX_CODE_REQUESTS_PER_IP_PER_HOUR = 5
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title="MetallicTrends API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
)
templates = Jinja2Templates(directory="web")


def _connect() -> sqlite3.Connection:
    """A plain connection — schema migrations are no longer applied here on
    every call. They're run explicitly at specific entry points instead (see
    index() and the /admin/auth/* handlers) so a request that doesn't touch
    migration-sensitive tables isn't paying for a schema_migrations check on
    every hit."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _require_same_origin(request: Request) -> None:
    """Blocks calls that don't carry browser fetch-metadata proving they came from
    our own page — keeps /api/metals and /api/prices for the site's own UI only.
    Doesn't apply to /api/widget, which is meant to be embedded on other sites.

    Sec-Fetch-Site is the primary signal, but not every browser/proxy sends
    fetch-metadata headers (older Safari, privacy-hardened browsers, some
    reverse proxies) — when it's simply absent, fall back to Referer, which
    every browser attaches to a same-page fetch() unless referrers are
    disabled entirely. A missing-but-genuinely-same-origin request should not
    be treated the same as a cross-site one."""
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site in ("same-origin", "same-site"):
        return
    if sec_fetch_site is None:
        referer = request.headers.get("referer")
        if referer and urlparse(referer).netloc == request.url.netloc:
            return
    raise HTTPException(403, "This endpoint is only accessible from the MetallicTrends site.")


def _sign_session(email: str, secret: str, ttl_seconds: int) -> str:
    """A stateless, tamper-evident session token: email + expiry + an HMAC
    signature over both, base64-encoded. No server-side session store needed —
    verifying is just re-computing the signature and comparing."""
    exp = int(time.time()) + ttl_seconds
    payload = f"{email}|{exp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def _verify_session(token: str, secret: str) -> str | None:
    try:
        email, exp_str, sig = base64.urlsafe_b64decode(token.encode()).decode().split("|", 2)
    except Exception:
        return None
    expected_sig = hmac.new(secret.encode(), f"{email}|{exp_str}".encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig, expected_sig):
        return None
    if int(exp_str) < int(time.time()):
        return None
    return email


def _current_admin_email(request: Request) -> str | None:
    """None if there's no valid session — used where the caller wants to
    branch on auth state (e.g. show a login form vs. the dashboard) rather
    than hard-fail."""
    secret = os.environ.get("ADMIN_SESSION_SECRET")
    token = request.cookies.get(_SESSION_COOKIE)
    if not secret or not token:
        return None
    return _verify_session(token, secret)


def _require_admin_session(request: Request) -> str:
    """Gates JSON /admin/* API routes: 501 if the server has no session
    secret configured, 401 if there's no valid session cookie."""
    if not os.environ.get("ADMIN_SESSION_SECRET"):
        raise HTTPException(501, "Admin auth is not configured on this server.")
    email = _current_admin_email(request)
    if email is None:
        raise HTTPException(401, "Not authenticated.")
    return email


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
    path; the mount still serves everything else (assets/, etc.). Applies any pending
    schema migrations first — "/" is virtually always the first route a visitor hits,
    so this is the main place the schema gets brought current. If the stored data has
    fallen behind today, catches up (capped at 1 month/1 request per load, with failed
    attempts capped at 3/day and spaced at least 8h apart) before rendering so the page
    never serves data staler than it needs to. On a successful catch-up, the newly
    fetched rows are committed to GitHub as a small data-migration file (not the whole
    DB) — apply_pending_migrations() replays it on the next boot, so this is what
    survives a Render restart."""
    with _connect() as conn:
        apply_pending_migrations(conn)
        since = datetime.now(timezone.utc)
        backfilled = maybe_backfill(conn)
        if backfilled:
            migration_sql = generate_backfill_migration_sql(conn, since.isoformat())
            if migration_sql:
                filename = f"{since:%Y%m%d_%H%M%S}_backfill.sql"
                commit_migration_file(conn, filename, migration_sql)
        context = _latest_meta(conn)
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


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    """Always 200s — the page itself decides what to show. With no valid
    session it renders the email/code login form; with one, the (placeholder)
    dashboard. This is deliberately not behind a Depends() that raises, since
    an anonymous visitor is meant to see a real login page, not an error."""
    email = _current_admin_email(request)
    return templates.TemplateResponse(request, "admin.html", {"email": email})


class _RequestCodeBody(BaseModel):
    email: str


class _VerifyCodeBody(BaseModel):
    email: str
    code: str


@app.post("/admin/auth/request-code")
def admin_request_code(body: _RequestCodeBody, request: Request):
    """Emails a 6-digit one-time code to any address the visitor supplies —
    intentionally open (not restricted to a fixed operator address) so
    recruiters/reviewers can self-serve access. The email itself is the
    access control: only someone who can read that inbox gets in. Every
    request is logged (email + IP) in admin_login_codes regardless of
    outcome, and rate-limited per email and per IP so this can't be turned
    into an open mechanism for spamming arbitrary addresses."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")

    ip = request.client.host if request.client else None
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=1)).isoformat()

    with _connect() as conn:
        apply_pending_migrations(conn)
        if count_recent_login_codes(conn, email=email, since=since) >= _MAX_CODE_REQUESTS_PER_EMAIL_PER_HOUR:
            raise HTTPException(429, "Too many code requests for this email. Try again later.")
        if ip and count_recent_login_codes(conn, ip=ip, since=since) >= _MAX_CODE_REQUESTS_PER_IP_PER_HOUR:
            raise HTTPException(429, "Too many code requests from this network. Try again later.")

        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        expires_at = (now + timedelta(seconds=_CODE_TTL_SECONDS)).isoformat()
        create_login_code(conn, email, code_hash, now.isoformat(), expires_at, ip)

    send_otp_email(email, code)
    return {"status": "sent"}


@app.post("/admin/auth/verify-code")
def admin_verify_code(body: _VerifyCodeBody, response: Response):
    """Verifies a code and, on success, sets the signed session cookie.
    Attempts are capped per code (not just per request) so a leaked or
    guessed-at code can't be brute-forced indefinitely — 5 wrong guesses
    invalidates it and a fresh code (subject to the request-code rate
    limits above) is required."""
    secret = os.environ.get("ADMIN_SESSION_SECRET")
    if not secret:
        raise HTTPException(501, "Admin auth is not configured on this server.")

    email = body.email.strip().lower()
    code = body.code.strip()
    now = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        apply_pending_migrations(conn)
        row = get_active_login_code(conn, email, now)
        if row is None:
            raise HTTPException(401, "Invalid or expired code.")
        row_id, _email, code_hash, _created_at, _expires_at, _used_at, attempts, _ip = row
        if attempts >= _MAX_CODE_ATTEMPTS:
            mark_login_code_used(conn, row_id, now)
            raise HTTPException(401, "Too many incorrect attempts. Request a new code.")

        submitted_hash = hashlib.sha256(code.encode()).hexdigest()
        if not secrets.compare_digest(submitted_hash, code_hash):
            if increment_login_code_attempts(conn, row_id) >= _MAX_CODE_ATTEMPTS:
                mark_login_code_used(conn, row_id, now)
            raise HTTPException(401, "Invalid or expired code.")

        mark_login_code_used(conn, row_id, now)

        # Persist the access log (this issued code — rate-limited rows are
        # never synced) only now, on a real completed login, not on every
        # request-code call. skip_render=True: a login shouldn't bounce the
        # live service — this commit gets picked up on whatever the next
        # real deploy happens to be (e.g. the next backfill push).
        result = generate_admin_login_migration_sql(conn, now)
        if result:
            migration_sql, row_ids = result
            filename = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_admin_login.sql"
            if commit_migration_file(conn, filename, migration_sql, skip_render=True):
                mark_login_codes_synced(conn, row_ids, now)

    token = _sign_session(email, secret, _SESSION_TTL_SECONDS)
    response.set_cookie(
        _SESSION_COOKIE, token, max_age=_SESSION_TTL_SECONDS,
        httponly=True, samesite="strict",
    )
    return {"status": "ok"}


@app.post("/admin/auth/logout")
def admin_logout(response: Response):
    response.delete_cookie(_SESSION_COOKIE)
    return {"status": "ok"}


if Path("web").is_dir():
    app.mount("/", StaticFiles(directory="web", html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
