"""
db_sync.py

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

import requests

logger = logging.getLogger("db_sync")

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
DB_PATH = os.environ.get("DB_PATH", "metals.db")

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_PATH}"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def push_db_to_github() -> None:
    """Commits the local DB file to GitHub. Deliberately has NO "[skip render]"
    phrase -- the resulting normal auto-deploy is what bakes the updated file
    into the image Render restarts from next."""
    if not os.path.exists(DB_PATH):
        return

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
    else:
        logger.error("Failed to push DB to GitHub: %s %s", put_resp.status_code, put_resp.text)
