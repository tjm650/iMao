from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.app import admin
from backend.app.config import Settings
from backend.app import vouchers
from database import database


def _test_settings(path):
    return Settings(database_path=str(path), app_secret_key="test-secret-key-with-at-least-32-characters")


def test_admin_can_create_batch_and_revoke_only_unused_voucher(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path / "admin.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(vouchers, "get_settings", lambda: settings)
    database.initialize_database()

    admin.create_admin("operator", "a-strong-password-123")
    with database.connect() as db:
        admin_id = db.execute("SELECT id FROM admin_users WHERE username='operator'").fetchone()["id"]

    codes = admin.create_voucher_batch(admin_id, 2, 500 * 1024 * 1024, None, "Front desk")
    assert len(codes) == 2
    items = admin.list_vouchers(status="available")
    assert items["total"] == 2
    assert items["items"][0]["batch_label"] == "Front desk"

    voucher_id = items["items"][0]["id"]
    admin.revoke_voucher(admin_id, voucher_id)
    assert admin.list_vouchers(status="available")["total"] == 1
    assert admin.list_vouchers(status="revoked")["total"] == 1


def test_admin_batch_rejects_naive_or_past_expiry(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path / "expiry.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(vouchers, "get_settings", lambda: settings)
    database.initialize_database()
    with database.connect() as db:
        db.execute("INSERT INTO admin_users (username,password_hash) VALUES ('operator','hash')")
        admin_id = db.execute("SELECT id FROM admin_users").fetchone()["id"]

    with pytest.raises(HTTPException) as error:
        admin.create_voucher_batch(admin_id, 1, 1024, "2030-01-01T00:00:00", None)
    assert error.value.status_code == 422


def test_database_migrates_existing_vouchers_table(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with database.connect(path) as db:
        db.execute("CREATE TABLE vouchers (id INTEGER PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, quota_bytes INTEGER NOT NULL, used_bytes INTEGER NOT NULL DEFAULT 0, expires_at TEXT, redeemed_by_user_id INTEGER, redeemed_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO vouchers (code_hash, quota_bytes) VALUES ('existing-hash', 1024)")
    database.initialize_database(path)
    with database.connect(path) as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(vouchers)")}
        assert {"revoked_at", "batch_id"}.issubset(columns)
        assert db.execute("SELECT code_hash FROM vouchers").fetchone()["code_hash"] == "existing-hash"
