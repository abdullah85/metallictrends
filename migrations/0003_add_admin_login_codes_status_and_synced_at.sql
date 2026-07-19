ALTER TABLE admin_login_codes ADD COLUMN status TEXT NOT NULL DEFAULT 'issued';
ALTER TABLE admin_login_codes ADD COLUMN synced_at TEXT;
