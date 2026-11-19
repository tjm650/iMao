import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.accounting import account_active_sessions, expire_sessions, retry_pending_revocations
from backend.app.auth import authenticate_voucher, current_session, logout_session
from backend.app.config import get_settings
from backend.app.captive_portal import client_is_authorized
from database.database import initialize_database

logger = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(title="iMao Captive Portal", version="0.3.0")
FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "login"
if FRONTEND_ROOT.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_ROOT), name="portal-static")

DASHBOARD_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dashboard"
if DASHBOARD_ROOT.exists():
    app.mount("/static-dashboard", StaticFiles(directory=DASHBOARD_ROOT), name="dashboard-static")


class VoucherLogin(BaseModel):
    code: str = Field(min_length=8, max_length=64)


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
        return RedirectResponse(url="/", status_code=302, headers=headers)
    if platform == "android":
        return Response(status_code=204, headers=headers)
    if platform == "apple":
        return Response(
            content="<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>",
            media_type="text/html", headers=headers,
        )
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
    return JSONResponse(
        payload,
        media_type="application/captive+json",
        headers={"Cache-Control": "no-store, private", "Vary": "Accept"},
    )


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
    """Redirect arbitrary intercepted HTTP requests to the voucher portal."""
    client_ip = request.client.host if request.client else ""
    if not client_is_authorized(client_ip):
        return RedirectResponse(url="/", status_code=303, headers={"Cache-Control": "no-store"})
    return JSONResponse({"detail": "Not found"}, status_code=404)
