from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.app import admin
from backend.app.config import Settings
from backend.app import vouchers
from database import database


def _test_settings(path):
    return Settings(database_path=str(path), app_secret_key="test-secret-key-with-at-least-32-characters")


def test_bootstrap_creates_only_the_first_administrator(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path / "bootstrap.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()

    admin.bootstrap_admin("firstadmin", "a-strong-password-123")
    with database.connect() as db:
        row = db.execute("SELECT username, password_hash, role FROM admin_users").fetchone()
        assert row["username"] == "firstadmin"
        assert row["role"] == "admin"
        assert row["password_hash"] != "a-strong-password-123"
        assert db.execute(
            "SELECT action FROM audit_logs WHERE action='admin.bootstrap'"
        ).fetchone() is not None

    with pytest.raises(HTTPException) as error:
        admin.bootstrap_admin("secondadmin", "another-strong-password")
    assert error.value.status_code == 409
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 1


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


def test_role_permissions_restrict_viewer_from_voucher_creation(tmp_path, monkeypatch):
    from starlette.requests import Request

    settings = _test_settings(tmp_path / "roles.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()
    admin.create_admin("readonly", "a-strong-password-123", "viewer")
    token = "test-admin-session-token"
    with database.connect() as db:
        admin_id = db.execute("SELECT id FROM admin_users WHERE username='readonly'").fetchone()["id"]
        db.execute(
            "INSERT INTO admin_sessions (admin_user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (admin_id, admin._token_hash(token), (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()),
        )
    request = Request({
        "type": "http", "method": "GET", "path": "/", "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [(b"cookie", f"imao_admin={token}".encode())],
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345), "http_version": "1.1",
    })
    assert admin.require_permission(request, "reports:read")["role"] == "viewer"
    with pytest.raises(HTTPException) as error:
        admin.require_permission(request, "voucher:create")
    assert error.value.status_code == 403


def test_last_active_admin_cannot_be_demoted_or_disabled(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path / "last-admin.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()
    admin.create_admin("primary", "a-strong-password-123")
    with database.connect() as db:
        admin_id = db.execute("SELECT id FROM admin_users WHERE username='primary'").fetchone()["id"]
    with pytest.raises(HTTPException) as error:
        admin.update_admin_access(999, admin_id, "viewer", True)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        admin.update_admin_access(999, admin_id, "admin", False)
    assert error.value.status_code == 409


def test_usage_report_filters_sessions_and_redemptions_by_date(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path / "reports.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()
    with database.connect() as db:
        db.execute(
            "INSERT INTO sessions (id, client_mac, client_ip, started_at, bytes_up, bytes_down) "
            "VALUES ('s1', 'aa:bb:cc:dd:ee:ff', '10.42.0.2', '2026-11-18 10:00:00', 1024, 2048)"
        )
        db.execute(
            "INSERT INTO sessions (id, client_mac, client_ip, started_at, bytes_up, bytes_down) "
            "VALUES ('s2', 'aa:bb:cc:dd:ee:11', '10.42.0.3', '2026-11-19 10:00:00', 4096, 8192)"
        )
        db.execute(
            "INSERT INTO vouchers (code_hash, quota_bytes, used_bytes, redeemed_at) "
            "VALUES ('report-voucher', 5000, 3000, '2026-11-18T10:00:00+00:00')"
        )
    report = admin.usage_report("2026-11-18", "2026-11-18")
    assert report["sessions"]["total"] == 1
    assert report["sessions"]["upload_bytes"] == 1024
    assert report["vouchers"]["redeemed"] == 1
    assert report["revenue"]["available"] is False


def test_admin_role_validation(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path / "invalid-role.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()
    with pytest.raises(ValueError):
        admin.create_admin("badrole", "a-strong-password-123", "superuser")


def test_inactive_admin_cannot_reuse_existing_session(tmp_path, monkeypatch):
    from starlette.requests import Request

    settings = _test_settings(tmp_path / "disabled-admin.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()
    admin.create_admin("disabled", "a-strong-password-123")
    token = "disabled-admin-token"
    with database.connect() as db:
        admin_id = db.execute("SELECT id FROM admin_users WHERE username='disabled'").fetchone()["id"]
        db.execute(
            "INSERT INTO admin_sessions (admin_user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (admin_id, admin._token_hash(token), (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()),
        )
        db.execute("UPDATE admin_users SET is_active=0 WHERE id=?", (admin_id,))
    request = Request({
        "type": "http", "method": "GET", "path": "/", "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [(b"cookie", f"imao_admin={token}".encode())],
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345), "http_version": "1.1",
    })
    with pytest.raises(HTTPException) as error:
        admin.require_admin(request)
    assert error.value.status_code == 401


def test_admin_login_rate_limit_is_enforced_before_password_check(tmp_path, monkeypatch):
    from fastapi import Response
    from starlette.requests import Request

    settings = _test_settings(tmp_path / "login-limit.sqlite3")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    database.initialize_database()
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as db:
        for _ in range(5):
            db.execute(
                "INSERT INTO admin_login_attempts (client_ip, succeeded, attempted_at) VALUES (?, 0, ?)",
                ("127.0.0.1", now),
            )
    request = Request({
        "type": "http", "method": "POST", "path": "/api/admin/login", "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [],
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345), "http_version": "1.1",
    })
    with pytest.raises(HTTPException) as error:
        admin.login_admin("missing", "incorrect-password", request, Response())
    assert error.value.status_code == 429


def test_admin_state_changes_reject_cross_origin_requests():
    from starlette.requests import Request

    request = Request({
        "type": "http", "method": "POST", "path": "/api/admin/vouchers/batches", "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [(b"origin", b"http://attacker.example")],
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345), "http_version": "1.1",
    })
    with pytest.raises(HTTPException) as error:
        admin._validate_same_origin(request)
    assert error.value.status_code == 403


def test_admin_state_changes_accept_matching_origin():
    from starlette.requests import Request

    request = Request({
        "type": "http", "method": "POST", "path": "/api/admin/vouchers/batches", "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [(b"origin", b"http://testserver")],
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345), "http_version": "1.1",
    })
    admin._validate_same_origin(request)
