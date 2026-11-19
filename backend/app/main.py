from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.auth import authenticate_voucher, current_session, logout_session
from backend.app.config import get_settings
from database.database import initialize_database

settings = get_settings()
app = FastAPI(title="iMao Captive Portal", version="0.2.0")
FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "login"
if FRONTEND_ROOT.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_ROOT), name="portal-static")

DASHBOARD_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "dashboard"
if DASHBOARD_ROOT.exists():
    app.mount("/static-dashboard", StaticFiles(directory=DASHBOARD_ROOT), name="dashboard-static")


class VoucherLogin(BaseModel):
    code: str = Field(min_length=8, max_length=64)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


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
