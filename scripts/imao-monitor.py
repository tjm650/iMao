#!/usr/bin/env python3
"""Check iMao liveness/readiness and optionally send a generic webhook alert."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def check(url: str, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            payload = json.loads(response.read(4096).decode("utf-8"))
            expected = "ready" if url.endswith("/ready") else "ok"
            if payload.get("status") != expected:
                return False, "Unexpected health response"
            return True, "OK"
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        # Avoid printing response bodies or URLs, which may contain sensitive query data.
        return False, type(exc).__name__


def alert(webhook: str, message: str, timeout: float) -> None:
    body = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Alert endpoint returned HTTP {response.status}")


def main() -> int:
    base = os.environ.get("IMAO_MONITOR_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    timeout = float(os.environ.get("IMAO_MONITOR_TIMEOUT_SECONDS", "5"))
    webhook = os.environ.get("IMAO_ALERT_WEBHOOK", "").strip()
    checks = [("liveness", base + "/health"), ("readiness", base + "/ready")]
    failures = []
    for name, url in checks:
        ok, detail = check(url, timeout)
        print(f"{name}: {'OK' if ok else 'FAILED'} ({detail})")
        if not ok:
            failures.append(f"{name} check failed: {detail}")

    if failures and webhook:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = "iMao health check failed at " + stamp + ": " + "; ".join(failures)
        try:
            alert(webhook, message, timeout)
            print("Alert delivered")
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            print(f"Alert delivery failed: {type(exc).__name__}", file=sys.stderr)
            return 2
    elif failures:
        print("No IMAO_ALERT_WEBHOOK configured; no external alert was sent", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
