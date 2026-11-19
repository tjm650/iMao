#!/usr/bin/env python3
"""Root-owned, allow-listed nftables helper. Install outside the writable repository."""
import ipaddress
import json
import subprocess
import sys
from pathlib import Path

CONFIG = Path("/etc/imao/netctl.json")


def load_config():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    network = ipaddress.ip_network(data["hotspot_cidr"], strict=True)
    iface = data["hotspot_interface"]
    if not isinstance(iface, str) or not iface or len(iface) > 15:
        raise ValueError("Invalid configured hotspot interface")
    return network, iface


def nft(*args):
    return subprocess.run(["/usr/sbin/nft", *args], capture_output=True, text=True, timeout=5, check=True)


def chain_rules():
    result = nft("-j", "list", "chain", "inet", "imao", "forward")
    return json.loads(result.stdout).get("nftables", [])


def find_counter_handles(ip):
    found = {"up": None, "down": None}
    for item in chain_rules():
        rule = item.get("rule")
        if not rule:
            continue
        comment = rule.get("comment", "")
        if comment == f"imao-up:{ip}":
            found["up"] = rule.get("handle")
        elif comment == f"imao-down:{ip}":
            found["down"] = rule.get("handle")
    return found


def remove_counters(ip):
    handles = find_counter_handles(ip)
    for handle in handles.values():
        if handle is not None:
            nft("delete", "rule", "inet", "imao", "forward", "handle", str(handle))


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"authorize", "revoke", "stats"}:
        raise SystemExit("Usage: imao-netctl {authorize|revoke|stats} CLIENT_IPV4")
    action, raw_ip = sys.argv[1:]
    network, iface = load_config()
    address = ipaddress.IPv4Address(raw_ip)
    if address not in network or address == network.network_address or address == network.broadcast_address:
        raise SystemExit("Client address is outside the configured hotspot subnet")

    if action == "authorize":
        # Idempotently refresh the authorization lease and ensure directional byte counters exist.
        nft("delete", "element", "inet", "imao", "authorized_v4", "{", str(address), "}")
        nft("add", "element", "inet", "imao", "authorized_v4", "{", str(address), "timeout", "12h", "}")
        handles = find_counter_handles(str(address))
        if handles["up"] is None:
            nft("insert", "rule", "inet", "imao", "forward", "iifname", iface, "ip", "saddr",
                str(address), "counter", "comment", f"imao-up:{address}")
        if handles["down"] is None:
            nft("insert", "rule", "inet", "imao", "forward", "oifname", iface, "ip", "daddr",
                str(address), "counter", "comment", f"imao-down:{address}")
        print("authorized")
    elif action == "revoke":
        try:
            nft("delete", "element", "inet", "imao", "authorized_v4", "{", str(address), "}")
        except subprocess.CalledProcessError:
            pass
        remove_counters(str(address))
        print("revoked")
    else:
        handles = find_counter_handles(str(address))
        totals = {"bytes_up": 0, "bytes_down": 0}
        for direction, handle in handles.items():
            if handle is None:
                continue
            for item in chain_rules():
                rule = item.get("rule", {})
                if rule.get("handle") == handle:
                    for expression in rule.get("expr", []):
                        counter = expression.get("counter", {}) if isinstance(expression, dict) else {}
                        if direction == "up":
                            totals["bytes_up"] = int(counter.get("bytes", 0))
                        else:
                            totals["bytes_down"] = int(counter.get("bytes", 0))
        print(json.dumps(totals))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"imao-netctl: {exc}", file=sys.stderr)
        raise SystemExit(1)
