import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from backend.app.client_identity import resolve_client_identity
from backend.app.config import get_settings
from backend.app.vouchers import hash_voucher
from database.database import connect

COOKIE_NAME = "imao_session"
MAX_FAILURES = 5
LOCKOUT_MINUTES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_rate_limit(client_ip: str) -> None:
    cutoff = (_now() - timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
    with connect() as db:
        row = db.execute(
            "SELECT COUNT(*) AS failures FROM login_attempts WHERE client_ip = ? AND attempted_at >= ? AND succeeded = 0",
            (client_ip, cutoff),
        ).fetchone()
    if row["failures"] >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait before trying again.")


def _record_attempt(client_ip: str, succeeded: bool) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO login_attempts (client_ip, succeeded, attempted_at) VALUES (?, ?, ?)",
            (client_ip, int(succeeded), _now().isoformat()),
        )
        if succeeded:
            db.execute("DELETE FROM login_attempts WHERE client_ip = ?", (client_ip,))


def redeem_voucher(code: str, client_ip: str, client_mac: str) -> tuple[str, dict]:
    _check_rate_limit(client_ip)
    try:
        code_hash = hash_voucher(code)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    now = _now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        voucher = db.execute(
            "SELECT * FROM vouchers WHERE code_hash = ?", (code_hash,)
        ).fetchone()

        valid = bool(voucher) and voucher["redeemed_at"] is None
        if valid and voucher["expires_at"]:
            try:
                expiry = datetime.fromisoformat(voucher["expires_at"].replace("Z", "+00:00"))
                valid = expiry.tzinfo is not None and expiry > now
            except ValueError:
                valid = False

        if not valid:
            db.rollback()
            _record_attempt(client_ip, False)
            raise HTTPException(status_code=401, detail="Voucher is invalid, expired or already used")

        active = db.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE client_mac = ? AND status = 'active'",
            (client_mac,),
        ).fetchone()["count"]
        if active:
            db.rollback()
            _record_attempt(client_ip, False)
            raise HTTPException(status_code=409, detail="This device already has an active session")

        session_id = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(session_id.encode()).hexdigest()
        db.execute(
            "UPDATE vouchers SET redeemed_at = ?, redeemed_by_user_id = NULL WHERE id = ? AND redeemed_at IS NULL",
            (now.isoformat(), voucher["id"]),
        )
        db.execute(
            """INSERT INTO sessions
               (id, session_token_hash, voucher_id, client_mac, client_ip, status)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (secrets.token_urlsafe(18), token_hash, voucher["id"], client_mac, client_ip),
        )
        db.commit()

    _record_attempt(client_ip, True)
    return session_id, {
        "quota_bytes": voucher["quota_bytes"],
        "used_bytes": voucher["used_bytes"],
        "remaining_bytes": voucher["quota_bytes"] - voucher["used_bytes"],
    }


def authenticate_voucher(request: Request, response: Response, code: str) -> dict:
    client_ip, client_mac = resolve_client_identity(request)
    token, quota = redeem_voucher(code, client_ip, client_mac)
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True, secure=settings.cookie_secure,
        samesite="strict", path="/", max_age=60 * 60 * 24,
    )
    return {"status": "connected", **quota}


def current_session(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No active session")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        row = db.execute(
            """SELECT s.id, s.client_mac, s.client_ip, s.started_at, s.status,
                      v.quota_bytes, v.used_bytes
               FROM sessions s JOIN vouchers v ON v.id = s.voucher_id
               WHERE s.session_token_hash = ? AND s.status = 'active'""",
            (token_hash,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Session is no longer active")
    return {
        "status": row["status"],
        "started_at": row["started_at"],
        "quota_bytes": row["quota_bytes"],
        "used_bytes": row["used_bytes"],
        "remaining_bytes": max(row["quota_bytes"] - row["used_bytes"], 0),
    }


def logout_session(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with connect() as db:
            db.execute(
                "UPDATE sessions SET status = 'logged_out', ended_at = CURRENT_TIMESTAMP WHERE session_token_hash = ? AND status = 'active'",
                (token_hash,),
            )
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return {"status": "logged_out"}
