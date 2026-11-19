"""Narrow, non-root interface to the installed wiMao privileged helper."""
import ipaddress
import json
import subprocess
from functools import lru_cache

from backend.app.config import get_settings


class NetctlError(RuntimeError):
    pass


def _run(*args: str) -> str:
    settings = get_settings()
    if not settings.firewall_enabled or settings.firewall_backend != "nftables":
        raise NetctlError("Network authorization is disabled; configure FIREWALL_ENABLED and FIREWALL_BACKEND.")
    command = [settings.netctl_sudo, "-n", settings.netctl_path, *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise NetctlError("The wiMao privileged network helper is unavailable.") from exc
    if result.returncode:
        raise NetctlError(result.stderr.strip() or "The wiMao network helper failed.")
    return result.stdout.strip()


def authorize_client(client_ip: str) -> None:
    _run("authorize", str(ipaddress.IPv4Address(client_ip)))


def revoke_client(client_ip: str) -> None:
    _run("revoke", str(ipaddress.IPv4Address(client_ip)))


def read_counters(client_ip: str) -> tuple[int, int]:
    output = _run("stats", str(ipaddress.IPv4Address(client_ip)))
    try:
        data = json.loads(output)
        up, down = int(data["bytes_up"]), int(data["bytes_down"])
        if up < 0 or down < 0:
            raise ValueError
        return up, down
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise NetctlError("The network helper returned invalid traffic counters.") from exc
