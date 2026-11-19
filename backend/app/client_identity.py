import ipaddress
import re
import subprocess

from fastapi import HTTPException, Request

from backend.app.config import get_settings

MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def resolve_client_identity(request: Request) -> tuple[str, str]:
    """Resolve the direct hotspot client; never trust forwarded headers."""
    settings = get_settings()
    client_ip = request.client.host if request.client else ""
    try:
        network = ipaddress.ip_network(settings.hotspot_cidr, strict=False)
        address = ipaddress.ip_address(client_ip)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Hotspot network is not configured") from exc

    if address not in network or address.is_unspecified or address.is_loopback:
        raise HTTPException(status_code=403, detail="Connect through the iMao Wi-Fi network")

    interface = settings.hotspot_interface
    if not interface or interface.startswith("REPLACE_"):
        raise HTTPException(status_code=503, detail="Hotspot interface is not configured")

    try:
        result = subprocess.run(
            ["ip", "neigh", "show", client_ip, "dev", interface],
            check=False, capture_output=True, text=True, timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail="Unable to identify this Wi-Fi device") from exc

    match = re.search(r"\blladdr\s+([0-9a-fA-F:]{17})\b", result.stdout)
    if result.returncode != 0 or not match or not MAC_RE.fullmatch(match.group(1)):
        raise HTTPException(status_code=409, detail="Device identity is not available yet. Reconnect to Wi-Fi and try again")

    return client_ip, match.group(1).lower()
