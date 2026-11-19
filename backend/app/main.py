import asyncio
import csv
import io
import logging
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.accounting import account_active_sessions, expire_sessions, retry_pending_revocations
from backend.app.admin import (create_voucher_batch, dashboard_summary, list_admins, list_vouchers, login_admin,
                               logout_admin, require_admin, require_permission, revoke_voucher, update_admin_access, usage_report)
from backend.app.auth import authenticate_voucher, current_session, logout_session
from backend.app.config import get_settings
from backend.app.captive_portal import client_is_authorized
from backend.app.quota import megabytes_to_bytes
from database.database import connect, initialize_database

logger = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(title="iMao Captive Portal", version="0.4.0")
FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "login"
if FRONTEND_ROOT.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_ROOT), name="portal-static")
DASHBOARD_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dashboard"
if DASHBOARD_ROOT.exists():
    app.mount("/static-dashboard", StaticFiles(directory=DASHBOARD_ROOT), name="dashboard-static")
ADMIN_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "admin"
if ADMIN_ROOT.exists():
    app.mount("/static-admin", StaticFiles(directory=ADMIN_ROOT), name="admin-static")


class VoucherLogin(BaseModel):
    code: str = Field(min_length=8, max_length=64)


class AdminLogin(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class VoucherBatchRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=500)
    quota_mb: int = Field(default=500, ge=1, le=1048576)
    expires_at: str | None = None
    label: str | None = Field(default=None, max_length=100)


async def _accounting_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(account_active_sessions)
            await asyncio.to_thread(expire_sessions)
            await asyncio.to_thread(retry_pending_revocations)
        except Exception:
            logger.exception("iMao accounting cycle failed")
        await asyncio.sleep(max(2, settings.session_poll_seconds))


@app.on_event("startup")
async def startup() -> None:
    if settings.firewall_enabled and settings.firewall_backend != "nftables":
        raise RuntimeError("FIREWALL_ENABLED requires FIREWALL_BACKEND=nftables")
    if settings.firewall_enabled and settings.session_max_hours != 12:
        raise RuntimeError("The current nftables helper uses a fixed 12-hour authorization lease; SESSION_MAX_HOURS must be 12")
    initialize_database()
    app.state.accounting_task = asyncio.create_task(_accounting_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "accounting_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _probe_response(request: Request, platform: str) -> Response:
    client_ip = request.client.host if request.client else ""
    authorized = client_is_authorized(client_ip)
    headers = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
    if not authorized:
        return RedirectResponse(url=(settings.portal_public_url.rstrip("/") + "/" if settings.portal_public_url else "/"), status_code=302, headers=headers)
    if platform == "android":
        return Response(status_code=204, headers=headers)
    if platform == "apple":
        return Response(content="<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>",
                        media_type="text/html", headers=headers)
    if platform == "windows":
        return PlainTextResponse("Microsoft Connect Test", headers=headers)
    if platform == "windows-legacy":
        return PlainTextResponse("Microsoft NCSI", headers=headers)
    if platform == "firefox":
        return PlainTextResponse("success", headers=headers)
    return Response(status_code=204, headers=headers)


@app.get("/generate_204", include_in_schema=False)
@app.get("/gen_204", include_in_schema=False)
def android_probe(request: Request):
    return _probe_response(request, "android")


@app.get("/hotspot-detect.html", include_in_schema=False)
def apple_probe(request: Request):
    return _probe_response(request, "apple")


@app.get("/connecttest.txt", include_in_schema=False)
def windows_probe(request: Request):
    return _probe_response(request, "windows")


@app.get("/ncsi.txt", include_in_schema=False)
def windows_legacy_probe(request: Request):
    return _probe_response(request, "windows-legacy")


@app.get("/success.txt", include_in_schema=False)
@app.get("/canonical.html", include_in_schema=False)
def firefox_probe(request: Request):
    return _probe_response(request, "firefox")


@app.get("/api/captive-portal", include_in_schema=False)
def captive_portal_api(request: Request):
    client_ip = request.client.host if request.client else ""
    payload = {"captive": not client_is_authorized(client_ip)}
    if settings.portal_public_url:
        payload["user-portal-url"] = settings.portal_public_url.rstrip("/") + "/"
    return JSONResponse(payload, media_type="application/captive+json",
                        headers={"Cache-Control": "no-store, private", "Vary": "Accept"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "imao"}


@app.get("/", include_in_schema=False)
def portal_home():
    page = FRONTEND_ROOT / "index.html"
    if not page.exists():
        return JSONResponse({"detail": "Portal frontend is not installed yet"}, status_code=503)
    return FileResponse(page)


@app.get("/connected", include_in_schema=False)
def connected_page():
    page = Path(__file__).resolve().parents[2] / "frontend" / "dashboard" / "index.html"
    if not page.exists():
        return JSONResponse({"detail": "Session page is not installed yet"}, status_code=503)
    return FileResponse(page)


@app.get("/admin", include_in_schema=False)
def admin_page():
    page = ADMIN_ROOT / "index.html"
    if not page.exists():
        return JSONResponse({"detail": "Admin interface is not installed yet"}, status_code=503)
    return FileResponse(page)


@app.post("/api/admin/login")
def admin_login(payload: AdminLogin, request: Request, response: Response):
    return login_admin(payload.username, payload.password, request, response)


@app.get("/api/admin/me")
def admin_me(request: Request):
    admin = require_admin(request)
    return {"username": admin["username"], "expires_at": admin["expires_at"]}


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response):
    return logout_admin(request, response)


@app.get("/api/admin/summary")
def admin_summary(request: Request):
    require_permission(request, 'dashboard:read')
    return dashboard_summary()


@app.get("/api/admin/vouchers")
def admin_vouchers(request: Request, limit: int = 100, offset: int = 0, status: str | None = None):
    require_permission(request, 'voucher:read')
    return list_vouchers(limit, offset, status)


@app.post("/api/admin/vouchers/batches")
def admin_create_batch(payload: VoucherBatchRequest, request: Request):
    admin = require_permission(request, 'voucher:create')
    return {"count": len(codes := create_voucher_batch(admin["id"], payload.count, megabytes_to_bytes(payload.quota_mb),
                                                         payload.expires_at, payload.label)), "codes": codes}


@app.post("/api/admin/vouchers/{voucher_id}/revoke")
def admin_revoke_voucher(voucher_id: int, request: Request):
    admin = require_permission(request, 'voucher:revoke')
    revoke_voucher(admin["id"], voucher_id)
    return {"status": "revoked"}


@app.get("/api/admin/sessions")
def admin_sessions(request: Request, limit: int = 100, offset: int = 0):
    require_permission(request, 'reports:read')
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        rows = db.execute(
            """SELECT s.id, s.client_mac, s.client_ip, s.started_at, s.ended_at, s.expires_at,
                      s.status, s.bytes_up, s.bytes_down, v.id AS voucher_id
               FROM sessions s LEFT JOIN vouchers v ON v.id=s.voucher_id
               ORDER BY s.started_at DESC LIMIT ? OFFSET ?""", (limit, offset)
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 100):
    require_permission(request, 'audit:read')
    with connect() as db:
        rows = db.execute(
            """SELECT l.id, a.username, l.action, l.details, l.created_at
               FROM audit_logs l LEFT JOIN admin_users a ON a.id=l.admin_user_id
               ORDER BY l.id DESC LIMIT ?""", (max(1, min(limit, 200)),)
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/config")
def public_config() -> dict[str, int | str]:
    return {"service": "iMao", "default_quota_mb": settings.default_quota_mb}


@app.post("/api/auth/voucher")
def voucher_login(payload: VoucherLogin, request: Request, response: Response):
    return authenticate_voucher(request, response, payload.code)


@app.get("/api/session")
def session_status(request: Request):
    return current_session(request)


@app.post("/api/logout")
def logout(request: Request, response: Response):
    return logout_session(request, response)


@app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
def captive_fallback(request: Request, path: str):
    client_ip = request.client.host if request.client else ""
    if not client_is_authorized(client_ip):
        return RedirectResponse(url=(settings.portal_public_url.rstrip("/") + "/" if settings.portal_public_url else "/"),
                                status_code=303, headers={"Cache-Control": "no-store"})
    return JSONResponse({"detail": "Not found"}, status_code=404)
