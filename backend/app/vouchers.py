import hashlib
import hmac
import secrets
import string

from backend.app.config import get_settings
from backend.app.quota import megabytes_to_bytes
from database.database import connect


def normalize_code(code: str) -> str:
    return "".join(code.upper().split())


def hash_voucher(code: str) -> str:
    secret = get_settings().app_secret_key
    if secret == "CHANGE_ME" or len(secret) < 32:
        raise RuntimeError("Set APP_SECRET_KEY to a random secret of at least 32 characters")
    return hmac.new(secret.encode(), normalize_code(code).encode(), hashlib.sha256).hexdigest()


def generate_voucher_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def create_voucher(quota_mb: int | None = None, expires_at: str | None = None) -> str:
    settings = get_settings()
    quota = megabytes_to_bytes(quota_mb or settings.default_quota_mb)
    code = generate_voucher_code()
    with connect() as db:
        db.execute(
            "INSERT INTO vouchers (code_hash, quota_bytes, expires_at) VALUES (?, ?, ?)",
            (hash_voucher(code), quota, expires_at),
        )
    return code
