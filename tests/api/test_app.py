import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import metallictrends.api.app as api
from metallictrends.db import init_db


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    """Points api.py at a fresh, file-backed SQLite DB (not :memory:, which would
    reset on every new connection) so the connection api._connect() opens per
    request can see data seeded by the test and any writes made during the request."""
    db_path = tmp_path / "metals.db"
    conn = sqlite3.connect(db_path)
    init_db(conn)
    conn.close()
    monkeypatch.setattr(api, "DB_PATH", str(db_path))
    return str(db_path)


def _seed_gold_series(db_path: str, last_date: str, days: int = 35) -> None:
    """Seeds `days` consecutive days of gold prices (and INR fx rates) ending on
    `last_date`, so `_latest_meta` has enough history to render without hitting
    the 404s _snapshot raises for missing data."""
    conn = sqlite3.connect(db_path)
    end = date.fromisoformat(last_date)
    for i in range(days):
        d = (end - timedelta(days=days - 1 - i)).isoformat()
        conn.execute(
            "INSERT INTO metal_prices (date, metal, price_usd) VALUES (?, 'gold', ?)",
            (d, 1900.0 + i),
        )
        conn.execute(
            "INSERT INTO fx_rates (date, currency, rate_to_usd) VALUES (?, 'INR', 0.012)",
            (d,),
        )
    conn.commit()
    conn.close()


def _max_gold_date(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT MAX(date) FROM metal_prices WHERE metal = 'gold'").fetchone()
    conn.close()
    return row[0]


def test_homepage_triggers_backfill_when_data_is_stale(api_db, fake_fetch_timeseries):
    """GET / backfills the gap first when the DB's last date is behind today, so
    the page renders with freshly caught-up data instead of stale data. The
    catch-up window ends yesterday, not today — metals.dev may not have
    published today's rates yet."""
    stale_last_date = (date.today() - timedelta(days=5)).isoformat()
    _seed_gold_series(api_db, stale_last_date)

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        response = TestClient(api.app).get("/")

    assert response.status_code == 200
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    mock_fetch.assert_called_once_with(
        (date.fromisoformat(stale_last_date) + timedelta(days=1)).isoformat(),
        yesterday,
    )
    assert _max_gold_date(api_db) == yesterday


def test_homepage_skips_backfill_when_data_is_current(api_db, fake_fetch_timeseries):
    """GET / makes no outbound requests when the DB is already caught up to today —
    the '>' check must be strict, not '>='."""
    _seed_gold_series(api_db, date.today().isoformat())

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        response = TestClient(api.app).get("/")

    assert response.status_code == 200
    mock_fetch.assert_not_called()


def test_homepage_backfill_capped_at_1_request_when_very_stale(api_db, fake_fetch_timeseries):
    """GET / makes at most 1 backfill request even when the DB has been stale for
    much longer than a month, so one page load can't trigger an unbounded fetch —
    catching up the rest happens on subsequent loads."""
    very_stale_last_date = (date.today() - timedelta(days=365)).isoformat()
    _seed_gold_series(api_db, very_stale_last_date)

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        response = TestClient(api.app).get("/")

    assert response.status_code == 200
    assert mock_fetch.call_count == 1
    assert _max_gold_date(api_db) < date.today().isoformat()


def test_homepage_backfill_retries_once_per_burst_of_traffic(api_db):
    """A burst of homepage hits against a downed metals.dev makes only one real
    backfill attempt, not one per visit — retries are spaced out (currently 8h
    apart) rather than firing on every page load, so a brief traffic spike can't
    hammer a downed API."""
    stale_last_date = (date.today() - timedelta(days=5)).isoformat()
    _seed_gold_series(api_db, stale_last_date)

    with patch(
        "metallictrends.ingestion.run.fetch_timeseries", side_effect=ConnectionError("metals.dev is down")
    ) as mock_fetch:
        for _ in range(5):
            response = TestClient(api.app).get("/")
            assert response.status_code == 200

    assert mock_fetch.call_count == 1


# --- _require_same_origin ---

def test_same_origin_endpoint_allowed_with_sec_fetch_site_same_origin(api_db):
    """Sec-Fetch-Site: same-origin is the primary signal and is allowed through."""
    response = TestClient(api.app).get(
        "/api/prices/gold", headers={"sec-fetch-site": "same-origin"}
    )
    assert response.status_code == 200


def test_same_origin_endpoint_blocked_when_sec_fetch_site_is_cross_site(api_db):
    """An explicit cross-site value is rejected even if a same-origin-looking
    Referer is also present — Sec-Fetch-Site, when present, is authoritative."""
    response = TestClient(api.app).get(
        "/api/prices/gold",
        headers={"sec-fetch-site": "cross-site", "referer": "http://testserver/"},
    )
    assert response.status_code == 403


def test_same_origin_endpoint_allowed_via_referer_when_sec_fetch_site_missing(api_db):
    """Some browsers/proxies never send Fetch Metadata headers at all. When
    Sec-Fetch-Site is simply absent (not "cross-site"), a same-origin Referer
    is accepted as a fallback so those clients aren't blocked outright."""
    response = TestClient(api.app).get(
        "/api/prices/gold", headers={"referer": "http://testserver/"}
    )
    assert response.status_code == 200


def test_same_origin_endpoint_blocked_when_no_signal_at_all(api_db):
    """With neither Sec-Fetch-Site nor a same-origin Referer, the request is
    indistinguishable from a third party (e.g. curl) hitting the API directly."""
    response = TestClient(api.app).get("/api/prices/gold")
    assert response.status_code == 403


def test_same_origin_endpoint_blocked_when_referer_is_cross_origin(api_db):
    """A Referer pointing at a different origin doesn't satisfy the fallback."""
    response = TestClient(api.app).get(
        "/api/prices/gold", headers={"referer": "http://evil.example/"}
    )
    assert response.status_code == 403


# --- /admin auth: email one-time-code login ---

def test_admin_page_shows_login_form_when_not_authenticated(api_db):
    """With no session cookie, GET /admin renders the email/code login form,
    not the dashboard — a real 200 page, not an error, since anyone should be
    able to reach the login screen itself."""
    response = TestClient(api.app).get("/admin")
    assert response.status_code == 200
    assert "Admin Login" in response.text
    assert "Admin Dashboard" not in response.text


def test_admin_auth_post_endpoints_allowed_by_cors_preflight(api_db):
    """A cross-origin CORS preflight for POST to the admin auth endpoints must
    be allowed — the CORS middleware was originally GET-only for the
    read-only /api/* endpoints and needs POST too now that these exist, or a
    browser that treats /admin as a different origin (e.g. 127.0.0.1 vs
    localhost) gets its preflight rejected before the real request ever
    fires."""
    response = TestClient(api.app).options(
        "/admin/auth/request-code",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]


def test_request_code_rejects_invalid_email(api_db):
    response = TestClient(api.app).post("/admin/auth/request-code", json={"email": "not-an-email"})
    assert response.status_code == 400


def test_request_code_sends_email_and_logs_the_request(api_db):
    """A valid email gets a code sent to it, and the request is logged in
    admin_login_codes (email + IP) regardless of whether it's ever verified —
    that log is the access-tracking mechanism."""
    with patch("metallictrends.api.app.send_otp_email") as mock_send:
        response = TestClient(api.app).post(
            "/admin/auth/request-code", json={"email": "Recruiter@Example.com"}
        )
    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    mock_send.assert_called_once()
    sent_to, _code = mock_send.call_args[0]
    assert sent_to == "recruiter@example.com"  # normalized to lowercase

    conn = sqlite3.connect(api_db)
    row = conn.execute("SELECT email FROM admin_login_codes").fetchone()
    conn.close()
    assert row[0] == "recruiter@example.com"


def test_request_code_rate_limited(api_db):
    """Excess requests for the same email — from the same TestClient, so also
    the same source IP — are eventually rejected once either the per-email or
    per-IP cap is hit. Otherwise this endpoint would let anyone spam an
    arbitrary inbox with codes from your service Gmail account."""
    client = TestClient(api.app)
    limit = min(api._MAX_CODE_REQUESTS_PER_EMAIL_PER_HOUR, api._MAX_CODE_REQUESTS_PER_IP_PER_HOUR)
    with patch("metallictrends.api.app.send_otp_email"):
        for _ in range(limit):
            resp = client.post("/admin/auth/request-code", json={"email": "same@example.com"})
            assert resp.status_code == 200
        over_limit = client.post("/admin/auth/request-code", json={"email": "same@example.com"})
    assert over_limit.status_code == 429


def _request_code(client: TestClient, email: str) -> str:
    """Test helper: requests a code via the real endpoint (with sending
    mocked) and returns the plaintext code that would have been emailed."""
    with patch("metallictrends.api.app.send_otp_email") as mock_send:
        response = client.post("/admin/auth/request-code", json={"email": email})
    assert response.status_code == 200
    return mock_send.call_args[0][1]


def test_verify_code_returns_501_when_session_secret_unconfigured(api_db, monkeypatch):
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    client = TestClient(api.app)
    code = _request_code(client, "person@example.com")
    response = client.post("/admin/auth/verify-code", json={"email": "person@example.com", "code": code})
    assert response.status_code == 501


def test_verify_code_rejects_wrong_code(api_db, monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")
    client = TestClient(api.app)
    _request_code(client, "person@example.com")
    response = client.post(
        "/admin/auth/verify-code", json={"email": "person@example.com", "code": "000000"}
    )
    assert response.status_code == 401


def test_verify_code_succeeds_and_unlocks_the_dashboard(api_db, monkeypatch):
    """The full happy path: request a code, verify it, and the session cookie
    that verify-code sets is enough to see the real dashboard on /admin."""
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")
    client = TestClient(api.app)
    code = _request_code(client, "person@example.com")

    verify = client.post(
        "/admin/auth/verify-code", json={"email": "person@example.com", "code": code}
    )
    assert verify.status_code == 200
    assert "mt_admin_session" in verify.cookies

    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert "Admin Dashboard" in dashboard.text
    assert "person@example.com" in dashboard.text


def test_logout_clears_the_session_and_shows_login_form_again(api_db, monkeypatch):
    """After logging out, /admin shows the login form again instead of the
    dashboard — logout actually revokes access, not just a UI-only state."""
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")
    client = TestClient(api.app)
    code = _request_code(client, "person@example.com")
    client.post("/admin/auth/verify-code", json={"email": "person@example.com", "code": code})
    assert "Admin Dashboard" in client.get("/admin").text

    logout = client.post("/admin/auth/logout")
    assert logout.status_code == 200

    after = client.get("/admin")
    assert "Admin Login" in after.text
    assert "Admin Dashboard" not in after.text


def test_verify_code_cannot_be_reused(api_db, monkeypatch):
    """A code is single-use — verifying it twice fails the second time."""
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")
    client = TestClient(api.app)
    code = _request_code(client, "person@example.com")
    first = client.post("/admin/auth/verify-code", json={"email": "person@example.com", "code": code})
    assert first.status_code == 200
    second = client.post("/admin/auth/verify-code", json={"email": "person@example.com", "code": code})
    assert second.status_code == 401


def test_verify_code_locks_out_after_max_attempts(api_db, monkeypatch):
    """5 wrong guesses invalidate the code entirely — even the real code no
    longer works afterward, forcing a fresh request-code call rather than
    letting an attacker keep guessing against one emailed code indefinitely."""
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret")
    client = TestClient(api.app)
    code = _request_code(client, "person@example.com")

    for _ in range(5):
        resp = client.post(
            "/admin/auth/verify-code", json={"email": "person@example.com", "code": "000000"}
        )
        assert resp.status_code == 401

    final = client.post("/admin/auth/verify-code", json={"email": "person@example.com", "code": code})
    assert final.status_code == 401
