from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from backend.app.config import get_settings
from database.database import initialize_database

settings = get_settings()
app = FastAPI(title="iMao Captive Portal", version="0.1.0")

FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "login"


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


@app.get("/api/config")
def public_config() -> dict[str, int | str]:
    # Deliberately excludes interface names, IP addresses, secrets and firewall settings.
    return {
        "service": "iMao",
        "default_quota_mb": settings.default_quota_mb,
    }
