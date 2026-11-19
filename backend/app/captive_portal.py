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
            """SELECT expires_at FROM sessions
               WHERE client_ip = ? AND status = 'active'
               ORDER BY started_at DESC LIMIT 1""",
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
