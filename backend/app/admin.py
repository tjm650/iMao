import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, Response

from database.database import connect

COOKIE_NAME = "imao_admin"
SESSION_HOURS = 8
_passwords = PasswordHasher()


def _now():
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_admin(username: str, password: str, role: str = 'admin') -> None:
    username = username.strip()
    if len(username) < 3 or len(username) > 64:
        raise ValueError("Username must be between 3 and 64 characters")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be between 12 and 256 characters")
    if role not in {"admin", "manager", "operator", "viewer"}:
        raise ValueError("Role must be admin, manager, operator or viewer")
    password_hash = _passwords.hash(password)
    with connect() as db:
        db.execute("INSERT INTO admin_users (username, password_hash, role) VALUES (?, ?, ?)", (username, password_hash, role))


def login_admin(username: str, password: str, request: Request, response: Response) -> dict:
    ip = request.client.host if request.client else "unknown"
    cutoff = (_now() - timedelta(minutes=10)).isoformat()
    with connect() as db:
        failures = db.execute(
            "SELECT COUNT(*) FROM admin_login_attempts WHERE client_ip=? AND attempted_at>=? AND succeeded=0",
            (ip, cutoff),
        ).fetchone()[0]
        if failures >= 5:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
        row = db.execute("SELECT id, password_hash, is_active FROM admin_users WHERE username=?", (username.strip(),)).fetchone()
    valid = False
    if row and row["is_active"]:
        try:
            valid = _passwords.verify(row["password_hash"], password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            valid = False
    with connect() as db:
        db.execute("INSERT INTO admin_login_attempts (client_ip, succeeded, attempted_at) VALUES (?, ?, ?)",
                   (ip, int(valid), _now().isoformat()))
        if valid:
            db.execute("DELETE FROM admin_login_attempts WHERE client_ip=?", (ip,))
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid administrator username or password")
    token = secrets.token_urlsafe(40)
    expires = _now() + timedelta(hours=SESSION_HOURS)
    with connect() as db:
        db.execute("INSERT INTO admin_sessions (admin_user_id, token_hash, expires_at) VALUES (?, ?, ?)",
                   (row["id"], _token_hash(token), expires.isoformat()))
        db.execute("UPDATE admin_users SET last_login_at=? WHERE id=?", (_now().isoformat(), row["id"]))
        db.execute("INSERT INTO audit_logs (admin_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                   (row["id"], "admin.login", "Administrator signed in", _now().isoformat()))
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=request.url.scheme == "https",
                        samesite="strict", path="/", max_age=SESSION_HOURS * 3600)
    return {"status": "authenticated", "username": username.strip(), "expires_at": expires.isoformat()}


def require_admin(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Administrator sign-in required")
    with connect() as db:
        row = db.execute(
            """SELECT a.id, a.username, a.role, s.id AS session_id, s.expires_at
               FROM admin_sessions s JOIN admin_users a ON a.id=s.admin_user_id
               WHERE s.token_hash=? AND s.revoked_at IS NULL AND a.is_active=1""",
            (_token_hash(token),),
        ).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) <= _now():
        raise HTTPException(status_code=401, detail="Administrator session expired")
    return dict(row)


def logout_admin(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with connect() as db:
            row = db.execute("SELECT admin_user_id FROM admin_sessions WHERE token_hash=?", (_token_hash(token),)).fetchone()
            db.execute("UPDATE admin_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                       (_now().isoformat(), _token_hash(token)))
            if row:
                db.execute("INSERT INTO audit_logs (admin_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                           (row["admin_user_id"], "admin.logout", "Administrator signed out", _now().isoformat()))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return {"status": "logged_out"}


def dashboard_summary() -> dict:
    with connect() as db:
        active_sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE status='active'").fetchone()[0]
        active_admins = db.execute("SELECT COUNT(*) FROM admin_users WHERE is_active=1").fetchone()[0]
        voucher_counts = db.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN redeemed_at IS NULL AND revoked_at IS NULL THEN 1 ELSE 0 END) AS available,
                      SUM(CASE WHEN redeemed_at IS NOT NULL THEN 1 ELSE 0 END) AS redeemed,
                      SUM(CASE WHEN revoked_at IS NOT NULL THEN 1 ELSE 0 END) AS revoked
               FROM vouchers"""
        ).fetchone()
        traffic = db.execute("SELECT COALESCE(SUM(used_bytes),0) FROM vouchers").fetchone()[0]
        return {"active_sessions": active_sessions, "active_admins": active_admins,
                "vouchers": {k: int(voucher_counts[k] or 0) for k in ("total", "available", "redeemed", "revoked")},
                "recorded_usage_bytes": int(traffic)}


def create_voucher_batch(admin_id: int, count: int, quota_bytes: int, expires_at: str | None, label: str | None) -> list[str]:
    if count < 1 or count > 500:
        raise HTTPException(status_code=422, detail="Batch size must be between 1 and 500")
    if quota_bytes <= 0:
        raise HTTPException(status_code=422, detail="Quota must be greater than zero")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= _now():
                raise ValueError("Expiry must be a future timezone-aware timestamp")
            expires_at = expiry.astimezone(timezone.utc).isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Expiry must be a future ISO-8601 timestamp with a timezone") from exc
    from backend.app.vouchers import generate_voucher_code, hash_voucher
    codes = [generate_voucher_code() for _ in range(count)]
    now = _now().isoformat()
    with connect() as db:
        cursor = db.execute("INSERT INTO voucher_batches (label, created_by_admin_id, voucher_count, created_at) VALUES (?, ?, ?, ?)",
                            (label.strip()[:100] if label else None, admin_id, count, now))
        batch_id = cursor.lastrowid
        for code in codes:
            db.execute("INSERT INTO vouchers (code_hash, quota_bytes, expires_at, batch_id) VALUES (?, ?, ?, ?)",
                       (hash_voucher(code), quota_bytes, expires_at, batch_id))
        db.execute("INSERT INTO audit_logs (admin_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                   (admin_id, "voucher.batch_created", f"Created batch {batch_id} with {count} vouchers", now))
    return codes


def list_vouchers(limit: int = 100, offset: int = 0, status: str | None = None) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    clauses, params = [], []
    if status == "available":
        clauses.append("v.redeemed_at IS NULL AND v.revoked_at IS NULL AND (v.expires_at IS NULL OR v.expires_at > ?)")
        params.append(_now().isoformat())
    elif status == "redeemed":
        clauses.append("v.redeemed_at IS NOT NULL")
    elif status == "revoked":
        clauses.append("v.revoked_at IS NOT NULL")
    elif status not in (None, "all"):
        raise HTTPException(status_code=422, detail="Unknown voucher status")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM vouchers v" + where, params).fetchone()[0]
        rows = db.execute(
            """SELECT v.id, v.batch_id, b.label AS batch_label, v.quota_bytes, v.used_bytes,
                      v.expires_at, v.created_at, v.redeemed_at, v.revoked_at
               FROM vouchers v LEFT JOIN voucher_batches b ON b.id=v.batch_id""" + where +
            " ORDER BY v.id DESC LIMIT ? OFFSET ?", (*params, limit, offset)
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def revoke_voucher(admin_id: int, voucher_id: int) -> None:
    now = _now().isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT redeemed_at, revoked_at FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Voucher not found")
        if row["redeemed_at"] is not None:
            raise HTTPException(status_code=409, detail="Redeemed vouchers cannot be revoked")
        if row["revoked_at"] is None:
            db.execute("UPDATE vouchers SET revoked_at=? WHERE id=?", (now, voucher_id))
            db.execute("INSERT INTO audit_logs (admin_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                       (admin_id, "voucher.revoked", f"Revoked unused voucher {voucher_id}", now))

ROLE_PERMISSIONS = {
    "admin": {"dashboard:read", "voucher:read", "voucher:create", "voucher:revoke", "reports:read", "admins:manage", "audit:read"},
    "manager": {"dashboard:read", "voucher:read", "voucher:create", "voucher:revoke", "reports:read", "audit:read"},
    "operator": {"dashboard:read", "voucher:read", "voucher:create"},
    "viewer": {"dashboard:read", "voucher:read", "reports:read"},
}


def require_permission(request: Request, permission: str) -> dict:
    admin = require_admin(request)
    if permission not in ROLE_PERMISSIONS.get(admin["role"], set()):
        raise HTTPException(status_code=403, detail="Your administrator role does not permit this action")
    return admin


def list_admins() -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, username, role, is_active, created_at, last_login_at FROM admin_users ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def update_admin_access(actor_id: int, target_id: int, role: str, is_active: bool) -> None:
    if role not in {"admin", "manager", "operator", "viewer"}:
        raise HTTPException(status_code=422, detail="Unknown administrator role")
    if actor_id == target_id and (role != "admin" or not is_active):
        raise HTTPException(status_code=409, detail="You cannot demote or disable your own administrator account")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        target = db.execute("SELECT id FROM admin_users WHERE id=?", (target_id,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Administrator not found")
        if not is_active:
            active_admins = db.execute(
                "SELECT COUNT(*) FROM admin_users WHERE role='admin' AND is_active=1"
            ).fetchone()[0]
            current_admin = db.execute(
                "SELECT role, is_active FROM admin_users WHERE id=?", (target_id,)
            ).fetchone()
            if current_admin["role"] == "admin" and current_admin["is_active"] and active_admins <= 1:
                raise HTTPException(status_code=409, detail="At least one active administrator must remain")
        db.execute("UPDATE admin_users SET role=?, is_active=? WHERE id=?",
                   (role, int(is_active), target_id))
        db.execute(
            "INSERT INTO audit_logs (admin_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (actor_id, "admin.access_updated", f"Updated administrator {target_id}: role={role}, active={int(is_active)}", _now().isoformat()),
        )


def usage_report(start_date: str | None = None, end_date: str | None = None) -> dict:
    try:
        start = datetime.fromisoformat(start_date).date() if start_date else None
        end = datetime.fromisoformat(end_date).date() if end_date else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Report dates must use YYYY-MM-DD") from exc
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="Report end date must not precede start date")
    clauses, params = [], []
    if start:
        clauses.append("started_at >= ?")
        params.append(start.isoformat() + "T00:00:00")
    if end:
        clauses.append("started_at < ?")
        params.append((end + timedelta(days=1)).isoformat() + "T00:00:00")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect() as db:
        sessions = db.execute(
            "SELECT COUNT(*) AS total, SUM(bytes_up) AS upload, SUM(bytes_down) AS download FROM sessions" + where,
            params,
        ).fetchone()
        voucher_clauses, voucher_params = [], []
        if start:
            voucher_clauses.append("redeemed_at >= ?")
            voucher_params.append(start.isoformat() + "T00:00:00")
        if end:
            voucher_clauses.append("redeemed_at < ?")
            voucher_params.append((end + timedelta(days=1)).isoformat() + "T00:00:00")
        voucher_where = (" WHERE " + " AND ".join(voucher_clauses)) if voucher_clauses else ""
        vouchers = db.execute(
            "SELECT COUNT(*) AS redeemed, COALESCE(SUM(quota_bytes),0) AS quota_issued, "
            "COALESCE(SUM(used_bytes),0) AS voucher_usage FROM vouchers" + voucher_where,
            voucher_params,
        ).fetchone()
        daily = db.execute(
            "SELECT substr(started_at,1,10) AS day, COUNT(*) AS sessions, "
            "COALESCE(SUM(bytes_up),0) AS upload, COALESCE(SUM(bytes_down),0) AS download "
            "FROM sessions" + where + " GROUP BY substr(started_at,1,10) ORDER BY day",
            params,
        ).fetchall()
    return {
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
        "sessions": {"total": int(sessions["total"] or 0), "upload_bytes": int(sessions["upload"] or 0),
                     "download_bytes": int(sessions["download"] or 0)},
        "vouchers": {"redeemed": int(vouchers["redeemed"] or 0), "quota_issued_bytes": int(vouchers["quota_issued"] or 0),
                     "recorded_usage_bytes": int(vouchers["voucher_usage"] or 0)},
        "daily": [dict(row) for row in daily],
        "revenue": {"available": False, "reason": "iMao has no payment ledger or recorded transaction amounts yet."},
    }
