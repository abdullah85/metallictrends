"""
metallictrends.sync.github

Keeps metals.db durable across Render's free-tier restarts by committing it
straight to GitHub whenever new rows are fetched.

No separate "restore" step is needed: Render is already configured to
redeploy on every push to the linked branch, so the commit made here
IS the file Render's next build checks out. Restart / redeploy / spin-up
all just re-run `git checkout` on whatever was last pushed.

Required environment variables (set these in Render's dashboard):
  GITHUB_TOKEN  - fine-grained PAT with "Contents: Read and write"
                   permission on the target repo
  GITHUB_REPO   - "your-username/your-repo"
  GITHUB_BRANCH - branch to commit to, e.g. "main" (default: main)
  DB_PATH       - path for BOTH the local SQLite file and its location
                   inside the repo, e.g. "metals.db"
"""

import os
import base64
import logging
import sqlite3

import requests

from metallictrends.db import init_db, record_github_sync

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "deploy")
DB_PATH = os.environ.get("DB_PATH", "metals.db")

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_PATH}"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def push_db_to_github() -> None:
    """Commits the local DB file to GitHub. Deliberately has NO "[skip render]"
    phrase -- the resulting normal auto-deploy is what bakes the updated file
    into the image Render restarts from next.

    Records its own outcome to github_sync_log (success/failure + error detail)
    so the admin dashboard can show real sync history — the log row is written
    to the local DB *after* the push, so it's only reflected on GitHub itself
    starting with the next successful push. Any exception (network failure, a
    non-2xx response, etc.) is caught here rather than left to propagate, since
    this runs inline in the "/" route after a successful local backfill — a
    sync hiccup shouldn't turn into a 500 for a page that already has fresh data."""
    if not os.path.exists(DB_PATH):
        return

    success = False
    error_detail = None
    try:
        with open(DB_PATH, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()

        get_resp = requests.get(API_URL, headers=HEADERS, params={"ref": GITHUB_BRANCH}, timeout=15)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        payload = {
            "message": "Update metals.db with latest fetched entries",
            "content": content_b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(API_URL, headers=HEADERS, json=payload, timeout=30)
        if put_resp.status_code in (200, 201):
            logger.info("Pushed metals.db to GitHub — Render will redeploy with this commit.")
            success = True
        else:
            error_detail = f"HTTP {put_resp.status_code}: {put_resp.text[:300]}"
            logger.error("Failed to push DB to GitHub: %s %s", put_resp.status_code, put_resp.text)
    except Exception as exc:
        error_detail = str(exc)
        logger.error("Failed to push DB to GitHub: %s", exc, exc_info=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        record_github_sync(conn, "success" if success else "failed", error_detail=error_detail)
    finally:
        conn.close()


def commit_migration_file(
    conn: sqlite3.Connection, filename: str, content: str, skip_render: bool = False
) -> bool:
    """Commits a single generated data-migration file under migrations/ on
    GitHub — a small, diffable text file instead of the whole binary DB.
    apply_pending_migrations() replays it automatically on the next boot, so
    this is what makes newly-fetched data durable across a Render restart
    without ever pushing metals.db itself.

    skip_render=True appends "[skip render]" to the commit message, which
    Render recognizes and doesn't trigger a redeploy for — used for the
    admin-login access log, which shouldn't bounce the live service just
    because someone logged into /admin. The commit still lands on the
    branch, though: Render checks out the current HEAD whenever the *next*
    real (non-skipped) deploy fires, e.g. the next backfill push, so this
    only defers when it's picked up, not whether it ever is.

    Takes the caller's already-open connection (unlike push_db_to_github,
    which is called standalone and manages its own) since this always runs
    from inside an existing `with _connect() as conn:` block in app.py."""
    path = f"migrations/{filename}"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

    success = False
    error_detail = None
    try:
        content_b64 = base64.b64encode(content.encode()).decode()

        get_resp = requests.get(url, headers=HEADERS, params={"ref": GITHUB_BRANCH}, timeout=15)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        message = f"Add data migration {filename}"
        if skip_render:
            message += " [skip render]"
        payload = {
            "message": message,
            "content": content_b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(url, headers=HEADERS, json=payload, timeout=30)
        if put_resp.status_code in (200, 201):
            logger.info(
                "Committed migration %s to GitHub%s.", filename,
                " (deploy skipped)" if skip_render else " — Render will redeploy with this commit",
            )
            success = True
        else:
            error_detail = f"HTTP {put_resp.status_code}: {put_resp.text[:300]}"
            logger.error(
                "Failed to commit migration %s to GitHub: %s %s", filename, put_resp.status_code, put_resp.text
            )
    except Exception as exc:
        error_detail = str(exc)
        logger.error("Failed to commit migration %s to GitHub: %s", filename, exc, exc_info=True)

    record_github_sync(conn, "success" if success else "failed", error_detail=error_detail)
    return success
