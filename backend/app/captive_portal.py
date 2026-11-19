"""Per-client captive state used by OS connectivity probes and RFC 8908 API."""
import ipaddress
from datetime import datetime, timezone

from backend.app.config import get_settings
from database.database import connect


def client_is_authorized(client_ip: str) -> bool:
    """Return true only for an unexpired active session on the configured hotspot subnet."""
    settings = get_settings()
    try:
        address = ipaddress.ip_address(client_ip)
        network = ipaddress.ip_network(settings.hotspot_cidr, strict=False)
    except ValueError:
        return False
    if address not in network or address.is_unspecified or address.is_loopback:
        return False

    with connect() as db:
        row = db.execute(
            """SELECT s.expires_at FROM sessions s
               JOIN vouchers v ON v.id = s.voucher_id
               WHERE s.client_ip = ? AND s.status = 'active'
                 AND s.revocation_pending = 0 AND v.used_bytes < v.quota_bytes
               ORDER BY s.started_at DESC LIMIT 1""",
            (str(address),),
        ).fetchone()
    if not row:
        return False
    expires_at = row["expires_at"]
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            return False
        return expiry > datetime.now(timezone.utc)
    except ValueError:
        return False
