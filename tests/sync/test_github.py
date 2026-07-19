import sqlite3
from unittest.mock import Mock, patch

import pytest

import metallictrends.sync.github as github_sync


@pytest.fixture
def sync_db(tmp_path, monkeypatch):
    """A real, file-backed DB (not :memory:) so push_db_to_github can both
    read it as a file (for the GitHub push) and open a fresh connection to
    record the sync outcome — both need to resolve to the same file."""
    db_path = tmp_path / "metals.db"
    sqlite3.connect(db_path).close()
    monkeypatch.setattr(github_sync, "DB_PATH", str(db_path))
    return str(db_path)


def _mock_response(status_code, text=""):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = {}
    resp.text = text
    return resp


def test_push_db_to_github_records_success(sync_db):
    """A successful push (no existing sha, then a 201 PUT) is recorded as a
    'success' row in github_sync_log with no error detail."""
    with patch.object(github_sync.requests, "get", return_value=_mock_response(404)), \
         patch.object(github_sync.requests, "put", return_value=_mock_response(201)):
        github_sync.push_db_to_github()

    conn = sqlite3.connect(sync_db)
    row = conn.execute("SELECT status, error_detail FROM github_sync_log").fetchone()
    conn.close()
    assert row == ("success", None)


def test_push_db_to_github_records_failure_on_non_2xx(sync_db):
    """A non-2xx PUT response is recorded as 'failed' with the status and body
    captured as error_detail, and does not raise."""
    with patch.object(github_sync.requests, "get", return_value=_mock_response(404)), \
         patch.object(github_sync.requests, "put", return_value=_mock_response(500, text="server error")):
        github_sync.push_db_to_github()

    conn = sqlite3.connect(sync_db)
    row = conn.execute("SELECT status, error_detail FROM github_sync_log").fetchone()
    conn.close()
    assert row[0] == "failed"
    assert "500" in row[1]
    assert "server error" in row[1]


def test_push_db_to_github_records_failure_on_network_error(sync_db):
    """A network-level exception is caught, recorded, and does not propagate —
    a sync hiccup shouldn't crash the caller (the "/" route runs this inline
    after a page has already rendered fresh, locally-backfilled data)."""
    with patch.object(github_sync.requests, "get", side_effect=ConnectionError("no network")):
        github_sync.push_db_to_github()  # must not raise

    conn = sqlite3.connect(sync_db)
    row = conn.execute("SELECT status, error_detail FROM github_sync_log").fetchone()
    conn.close()
    assert row[0] == "failed"
    assert "no network" in row[1]


def test_push_db_to_github_does_nothing_when_db_file_missing(tmp_path, monkeypatch):
    """No DB file means nothing to push, and no sync attempt is recorded."""
    missing_path = tmp_path / "does-not-exist.db"
    monkeypatch.setattr(github_sync, "DB_PATH", str(missing_path))
    with patch.object(github_sync.requests, "get") as mock_get:
        github_sync.push_db_to_github()
    mock_get.assert_not_called()
    assert not missing_path.exists()
