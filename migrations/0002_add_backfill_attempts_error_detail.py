"""Adds backfill_attempts.error_detail. A .py migration (not .sql) because
SQLite has no "ADD COLUMN IF NOT EXISTS" — this needs to check first so it's
safe to apply against a database that already picked up the column via the
old ad-hoc _ensure_column() retrofit, before migrations existed."""


def migrate(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(backfill_attempts)")}
    if "error_detail" not in existing:
        conn.execute("ALTER TABLE backfill_attempts ADD COLUMN error_detail TEXT")
