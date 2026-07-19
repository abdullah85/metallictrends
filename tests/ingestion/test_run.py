import pytest
import requests
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, Mock
from metallictrends.ingestion.run import (
    chunk_date_range,
    run_backfill,
    needs_backfill,
    backfill_recent,
    maybe_backfill,
    MIN_BACKFILL_RETRY_INTERVAL,
)


# --- chunk_date_range ---

def test_chunk_date_range_single_window():
    """A range of 30 days or fewer produces exactly one window."""
    windows = chunk_date_range("2023-01-01", "2023-01-30")
    assert windows == [("2023-01-01", "2023-01-30")]


def test_chunk_date_range_splits_into_multiple_windows():
    """A range longer than 30 days is split into multiple windows of at most 30 days each."""
    windows = chunk_date_range("2023-01-01", "2023-03-01")
    assert len(windows) > 1
    for start, end in windows:
        assert (date.fromisoformat(end) - date.fromisoformat(start)).days <= 30


def test_chunk_date_range_covers_full_range():
    """The first window starts on start_date and the last window ends on end_date."""
    windows = chunk_date_range("2023-01-01", "2023-03-01")
    assert windows[0][0] == "2023-01-01"
    assert windows[-1][1] == "2023-03-01"


# --- run_backfill ---

def test_backfill_marks_window_fetched_on_success(db_conn, mock_10_day_response):
    """run_backfill marks a window as 'fetched' after a successful API call."""
    with patch("metallictrends.ingestion.run.fetch_timeseries", return_value=mock_10_day_response.json()):
        run_backfill(db_conn, "2023-01-01", "2023-01-10")
    row = db_conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ?", ("2023-01-01",)
    ).fetchone()
    assert row[0] == "fetched"


def test_backfill_marks_window_failed_on_http_error(db_conn):
    """run_backfill marks a window as 'failed' when fetch_timeseries raises HTTPError."""
    http_response = Mock()
    http_response.status_code = 500
    with patch(
        "metallictrends.ingestion.run.fetch_timeseries",
        side_effect=requests.exceptions.HTTPError(response=http_response),
    ):
        run_backfill(db_conn, "2023-01-01", "2023-01-10")
    row = db_conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ?", ("2023-01-01",)
    ).fetchone()
    assert row[0] == "failed"


def test_backfill_skips_already_fetched_windows(db_conn, mock_10_day_response):
    """run_backfill does not call fetch_timeseries for windows already marked 'fetched'."""
    db_conn.execute(
        "INSERT INTO backfill_windows (start_date, end_date, status, fetched_at) VALUES (?, ?, ?, ?)",
        ("2023-01-01", "2023-01-10", "fetched", "2024-01-01T00:00:00+00:00"),
    )
    db_conn.commit()
    with patch("metallictrends.ingestion.run.fetch_timeseries") as mock_fetch:
        run_backfill(db_conn, "2023-01-01", "2023-01-10")
    mock_fetch.assert_not_called()


# --- needs_backfill ---

def _seed_gold_price(conn, on_date: str) -> None:
    conn.execute(
        "INSERT INTO metal_prices (date, metal, price_usd) VALUES (?, 'gold', 1900.0)",
        (on_date,),
    )
    conn.commit()


def test_needs_backfill_true_when_gap_exceeds_one_day(db_conn):
    """needs_backfill is True once the latest stored date has fallen more than
    1 day behind today."""
    _seed_gold_price(db_conn, "2023-01-01")
    assert needs_backfill(db_conn, today=date(2023, 1, 3)) is True


def test_needs_backfill_false_when_last_date_is_today(db_conn):
    """needs_backfill is False once the latest stored date matches today exactly —
    the '>' in "current date is higher than the last saved date" must be strict."""
    _seed_gold_price(db_conn, "2023-01-01")
    assert needs_backfill(db_conn, today=date(2023, 1, 1)) is False


def test_needs_backfill_false_when_gap_is_exactly_one_day(db_conn):
    """A 1-day gap is tolerated rather than triggering a backfill, since
    metals.dev may not have the latest day's data ready yet."""
    _seed_gold_price(db_conn, "2023-01-01")
    assert needs_backfill(db_conn, today=date(2023, 1, 2)) is False


def test_needs_backfill_false_on_empty_table(db_conn):
    """With no rows at all there's no 'last date' for this check to act on, so it
    declines rather than guessing — seeding an empty DB is the CLI backfill's job."""
    assert needs_backfill(db_conn, today=date(2023, 1, 1)) is False


def test_needs_backfill_defaults_to_real_today(db_conn):
    """With no `today` argument, needs_backfill compares against the real current date."""
    _seed_gold_price(db_conn, (date.today() - timedelta(days=2)).isoformat())
    assert needs_backfill(db_conn) is True


# --- backfill_recent ---

def test_backfill_recent_covers_gap_up_to_yesterday_when_under_3_months(db_conn, fake_fetch_timeseries):
    """When the gap since the last stored date is 3 months or less, backfill_recent
    fetches exactly that gap: the day after the last date through yesterday.
    It never requests today itself, since metals.dev may not have published
    today's rates yet (confirmed live: a window including today came back with
    status "success" but rates: null)."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        backfill_recent(db_conn, today=date(2023, 1, 11))
    mock_fetch.assert_called_once_with("2023-01-02", "2023-01-10")


def test_backfill_recent_caps_at_1_month_in_1_request(db_conn, fake_fetch_timeseries):
    """When the DB is stale by much more than a month, backfill_recent caps the
    window at 30 days from the last stored date (not the full gap up to
    yesterday) — a single request, per chunk_date_range's own 30-day window
    size. This keeps a single homepage load bounded regardless of how stale
    the data is; catching up the rest of the gap happens on subsequent loads."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        backfill_recent(db_conn, today=date(2024, 1, 1))
    mock_fetch.assert_called_once_with("2023-01-02", "2023-02-01")


def test_backfill_recent_returns_true_on_success(db_conn, fake_fetch_timeseries):
    """backfill_recent reports success back to its caller (maybe_backfill relies
    on this to decide whether to log/record a failed attempt), with no error detail."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries):
        assert backfill_recent(db_conn, today=date(2023, 1, 11)) == (True, None)


def test_backfill_recent_returns_false_on_failure(db_conn):
    """backfill_recent reports failure when the underlying fetch raises, along
    with the exception message as error detail."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=requests.exceptions.ConnectionError("boom")):
        success, error_detail = backfill_recent(db_conn, today=date(2023, 1, 11))
    assert success is False
    assert "boom" in error_detail


def test_backfill_recent_never_requests_today(db_conn, fake_fetch_timeseries):
    """Even with only a 2-day gap (the minimum that triggers needs_backfill),
    backfill_recent's window ends on yesterday, not today."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        backfill_recent(db_conn, today=date(2023, 1, 3))
    mock_fetch.assert_called_once_with("2023-01-02", "2023-01-02")


def test_backfill_recent_records_fetched_windows(db_conn, fake_fetch_timeseries):
    """After backfill_recent runs, the windows it covered are marked 'fetched',
    so a subsequent homepage load won't re-fetch them."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries):
        backfill_recent(db_conn, today=date(2023, 1, 6))
    row = db_conn.execute(
        "SELECT status FROM backfill_windows WHERE start_date = ?", ("2023-01-02",)
    ).fetchone()
    assert row[0] == "fetched"


# --- run_backfill logging ---

def test_run_backfill_logs_a_warning_on_window_failure(db_conn, caplog):
    """A window fetch failure is logged, not silently swallowed."""
    with patch(
        "metallictrends.ingestion.run.fetch_timeseries",
        side_effect=requests.exceptions.ConnectionError("boom"),
    ):
        with caplog.at_level("WARNING", logger="metallictrends.ingestion.run"):
            run_backfill(db_conn, "2023-01-01", "2023-01-10")
    assert any("2023-01-01" in message for message in caplog.messages)


def test_run_backfill_returns_false_when_any_window_fails(db_conn, fake_fetch_timeseries):
    """run_backfill reports False if any window in the range failed, even if
    others succeeded."""
    responses = [fake_fetch_timeseries("2023-01-01", "2023-01-30"), requests.exceptions.ConnectionError()]

    def _flaky(start, end):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=_flaky):
        all_fetched, _ = run_backfill(db_conn, "2023-01-01", "2023-03-01")
    assert all_fetched is False


# --- maybe_backfill ---

def _record_failed_attempt_at(conn, attempt_date: str, attempted_at: str) -> None:
    """Directly seeds a failed attempt with a specific timestamp — used to put
    the DB in a state that couldn't arise from a single-threaded sequence of
    maybe_backfill calls (e.g. testing the day cap in isolation from spacing)."""
    conn.execute(
        "INSERT INTO backfill_attempts (attempt_date, attempted_at, status) VALUES (?, ?, 'failed')",
        (attempt_date, attempted_at),
    )
    conn.commit()


def test_maybe_backfill_does_nothing_when_up_to_date(db_conn, fake_fetch_timeseries):
    """maybe_backfill makes no request when the DB is already caught up to today."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        maybe_backfill(db_conn, now=datetime(2023, 1, 1, tzinfo=timezone.utc))
    mock_fetch.assert_not_called()


def test_maybe_backfill_records_success(db_conn, fake_fetch_timeseries):
    """A successful catch-up records a 'success' attempt for today."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries):
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, tzinfo=timezone.utc))
    row = db_conn.execute(
        "SELECT status FROM backfill_attempts WHERE attempt_date = ?", ("2023-01-11",)
    ).fetchone()
    assert row[0] == "success"


def test_maybe_backfill_logs_and_records_failure(db_conn, caplog):
    """A failed catch-up attempt is logged and recorded as 'failed' for today."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=requests.exceptions.ConnectionError("boom")):
        with caplog.at_level("ERROR", logger="metallictrends.ingestion.run"):
            maybe_backfill(db_conn, now=datetime(2023, 1, 11, tzinfo=timezone.utc))
    row = db_conn.execute(
        "SELECT status FROM backfill_attempts WHERE attempt_date = ?", ("2023-01-11",)
    ).fetchone()
    assert row[0] == "failed"
    assert any("2023-01-11" in message for message in caplog.messages)


def test_maybe_backfill_records_error_detail_on_failure(db_conn):
    """The underlying exception's message is persisted as error_detail, so a
    failed attempt's cause is visible without digging through logs."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=requests.exceptions.ConnectionError("boom")):
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, tzinfo=timezone.utc))
    row = db_conn.execute(
        "SELECT error_detail FROM backfill_attempts WHERE attempt_date = ?", ("2023-01-11",)
    ).fetchone()
    assert "boom" in row[0]


def test_maybe_backfill_records_no_error_detail_on_success(db_conn, fake_fetch_timeseries):
    """A successful attempt has no error_detail."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries):
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, tzinfo=timezone.utc))
    row = db_conn.execute(
        "SELECT error_detail FROM backfill_attempts WHERE attempt_date = ?", ("2023-01-11",)
    ).fetchone()
    assert row[0] is None


def test_maybe_backfill_skips_retry_within_spacing_interval(db_conn, fake_fetch_timeseries):
    """A retry attempted less than MIN_BACKFILL_RETRY_INTERVAL after the last
    failure is skipped, even though the daily cap of 3 hasn't been reached yet —
    this is what spreads retries through the day instead of bursting them."""
    _seed_gold_price(db_conn, "2023-01-01")
    _record_failed_attempt_at(db_conn, "2023-01-11", "2023-01-11T06:00:00+00:00")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, 10, 0, tzinfo=timezone.utc))
    mock_fetch.assert_not_called()


def test_maybe_backfill_retries_once_spacing_interval_has_elapsed(db_conn, fake_fetch_timeseries):
    """Once at least MIN_BACKFILL_RETRY_INTERVAL has passed since the last
    failure, a retry is allowed again."""
    _seed_gold_price(db_conn, "2023-01-01")
    _record_failed_attempt_at(db_conn, "2023-01-11", "2023-01-11T06:00:00+00:00")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        maybe_backfill(
            db_conn,
            now=datetime(2023, 1, 11, 6, 0, tzinfo=timezone.utc) + MIN_BACKFILL_RETRY_INTERVAL,
        )
    mock_fetch.assert_called_once()


def test_maybe_backfill_day_cap_applies_even_after_spacing_interval_elapses(db_conn, fake_fetch_timeseries):
    """3 failed attempts already recorded for the day block a further retry even
    once the spacing interval since the last one has fully elapsed — the day cap
    is a backstop independent of spacing (e.g. against concurrent requests each
    passing the spacing check before either records its failure)."""
    _seed_gold_price(db_conn, "2023-01-01")
    for hour in (0, 1, 2):
        _record_failed_attempt_at(db_conn, "2023-01-11", f"2023-01-11T{hour:02d}:00:00+00:00")
    with patch("metallictrends.ingestion.run.fetch_timeseries", side_effect=fake_fetch_timeseries) as mock_fetch:
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, 20, 0, tzinfo=timezone.utc))
    mock_fetch.assert_not_called()


def test_maybe_backfill_retries_on_a_new_day_once_spacing_allows(db_conn, fake_fetch_timeseries):
    """A failed attempt blocks a same-day repeat via spacing; once both a new
    calendar day has started and the spacing interval has elapsed, it retries."""
    _seed_gold_price(db_conn, "2023-01-01")
    with patch(
        "metallictrends.ingestion.run.fetch_timeseries", side_effect=requests.exceptions.ConnectionError("boom")
    ) as mock_fetch:
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, 0, 0, tzinfo=timezone.utc))
        maybe_backfill(db_conn, now=datetime(2023, 1, 11, 4, 0, tzinfo=timezone.utc))
        maybe_backfill(db_conn, now=datetime(2023, 1, 12, 0, 0, tzinfo=timezone.utc))
    assert mock_fetch.call_count == 2
