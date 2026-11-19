#!/usr/bin/env python3
"""Discover host networking and render iMao configs without changing the host."""
import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env = os.environ.copy()
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
        return result.stdout.strip(), result.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", 127


def discover():
    links_raw, links_rc = run(["ip", "-j", "-br", "address"])
    routes_raw, routes_rc = run(["ip", "-j", "route", "show", "default"])
    wireless_raw, wireless_rc = run(["iw", "dev"])
    iw_list, iw_rc = run(["iw", "list"])

    links = json.loads(links_raw) if links_raw else []
    routes = json.loads(routes_raw) if routes_raw else []
    wireless_names = re.findall(r"^\s*Interface\s+(\S+)", wireless_raw, re.M)
    ap_supported = bool(re.search(r"\*\s+AP\s*$", iw_list, re.M))
    wifi = []
    for name in wireless_names:
        entry = next((x for x in links if x.get("ifname") == name), {})
        wifi.append({"name": name, "state": entry.get("operstate", "unknown"),
                     "addresses": [a.get("local") for a in entry.get("addr_info", [])]})
    ethernet = [x for x in links if x.get("ifname") not in wireless_names
                and x.get("ifname") != "lo"]
    report = {
        "default_routes": routes,
        "wireless_interfaces": wifi,
        "other_interfaces": ethernet,
        "wireless_ap_mode_supported": ap_supported,
        "tools": {"ip": links_rc == 0 and routes_rc == 0, "iw": wireless_rc == 0 and iw_rc == 0},
        "note": "Read-only discovery. No interface, route, service or firewall settings were changed."
    }
    print(json.dumps(report, indent=2))


def required(env, key):
    value = env.get(key, "").strip()
    if not value or value.startswith("REPLACE_"):
        raise SystemExit(f"Set {key} in your local .env before rendering network configuration.")
    return value


def render():
    env = load_env()
    upstream = required(env, "UPSTREAM_INTERFACE")
    hotspot = required(env, "HOTSPOT_INTERFACE")
    cidr = ipaddress.ip_network(required(env, "HOTSPOT_CIDR"), strict=False)
    gateway = ipaddress.ip_address(required(env, "HOTSPOT_GATEWAY"))
    if gateway not in cidr:
        raise SystemExit("HOTSPOT_GATEWAY must be inside HOTSPOT_CIDR.")
    if upstream == hotspot:
        raise SystemExit("UPSTREAM_INTERFACE and HOTSPOT_INTERFACE must be different.")

    for name, value in (("UPSTREAM_INTERFACE", upstream), ("HOTSPOT_INTERFACE", hotspot)):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", value):
            raise SystemExit(f"{name} is not a valid Linux interface name.")
    ssid = required(env, "HOTSPOT_SSID")
    passphrase = required(env, "HOTSPOT_PASSPHRASE")
    country = required(env, "WIFI_COUNTRY_CODE")
    if any(ch in ssid + passphrase for ch in "\\r\\n"):
        raise SystemExit("SSID and passphrase must not contain newline characters.")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise SystemExit("WIFI_COUNTRY_CODE must be a two-letter uppercase country code.")
    if not 8 <= len(passphrase) <= 63:
        raise SystemExit("HOTSPOT_PASSPHRASE must contain 8–63 characters.")
    if len(ssid.encode("utf-8")) > 32:
        raise SystemExit("HOTSPOT_SSID must be at most 32 bytes.")

    hosts = list(cidr.hosts())
    if len(hosts) < 8:
        raise SystemExit("Choose a hotspot subnet with at least 8 usable addresses.")
    candidates = [ip for ip in hosts if ip != gateway]
    start, end = candidates[0], candidates[min(len(candidates)-1, 99)]
    values = {
        "HOTSPOT_INTERFACE": hotspot, "UPSTREAM_INTERFACE": upstream,
        "HOTSPOT_CIDR": str(cidr), "HOTSPOT_GATEWAY": str(gateway),
        "HOTSPOT_SSID": ssid, "HOTSPOT_PASSPHRASE": passphrase,
        "WIFI_COUNTRY_CODE": country, "HOTSPOT_DHCP_START": str(start),
        "HOTSPOT_DHCP_END": str(end), "PORTAL_PORT": env.get("PORTAL_PORT", "8000")
    }
    output = ROOT / "runtime-config"
    output.mkdir(exist_ok=True)
    for name in ("hostapd.conf", "dnsmasq.conf", "nftables.conf"):
        template = ROOT / "config" / f"{name}.example"
        content = template.read_text(encoding="utf-8")
        for key, value in values.items():
            content = content.replace("{{" + key + "}}", value)
        if "{{" in content:
            raise SystemExit(f"Unresolved template placeholder in {name}.")
        (output / name).write_text(content, encoding="utf-8")
        os.chmod(output / name, 0o600 if name == "hostapd.conf" else 0o644)
        print(f"Rendered {output / name}")
    print("No host services or firewall rules were changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "render"))
    args = parser.parse_args()
    discover() if args.command == "discover" else render()


if __name__ == "__main__":
    main()
