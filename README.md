# iMao

A lightweight, self-hosted Wi-Fi captive portal and voucher-based bandwidth manager for a Linux laptop acting as the gateway.

## Current status

Implemented:
- FastAPI backend and health/config endpoints
- Environment-based settings; no host-specific IP or interface values in tracked code
- SQLite schema and additive session-token migration
- Single-use voucher generation and HMAC-SHA256 voucher-code storage
- Voucher redemption, client IP/MAC lookup using the Linux neighbour table, session cookies, status and logout endpoints
- Failed-login throttling (5 failed attempts in a rolling 10-minute window per client IP)
- Mobile-first voucher login page and quota calculation tests

Not yet implemented: firewall authorization, captive HTTP redirects, traffic counters, quota disconnection, admin authentication/dashboard, hotspot provisioning or production deployment. A successful portal session does **not** yet grant network access.

## Requirements

- Ubuntu/Debian Linux, Python 3.10+
- Ethernet upstream
- Wi-Fi adapter capable of AP mode
- Later stages: hostapd, dnsmasq, nftables and conntrack tools

## Development setup

```bash
git clone https://github.com/tjm650/iMao.git
cd iMao
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Set a strong secret before creating vouchers. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the result in local `.env` as `APP_SECRET_KEY`. Keep `.env` private and never commit it. Fill in `HOTSPOT_INTERFACE` and `HOTSPOT_CIDR` after discovering the actual host network. The voucher endpoint refuses to authenticate a client until those values are valid and its MAC address can be resolved from the Linux neighbour table.

Start the app from the repository root:

```bash
uvicorn backend.app.main:app --reload
```

Generate a single-use voucher (default 500 MB):

```bash
python scripts/create-voucher.py
```

Or set a different quota:

```bash
python scripts/create-voucher.py --quota-mb 1000
```

The raw voucher code is printed once. Store/share it securely; only its keyed hash is stored in SQLite. Optional expiry must be timezone-aware ISO-8601:

```bash
python scripts/create-voucher.py --quota-mb 500 --expires-at 2027-01-01T00:00:00+00:00
```

Run tests:

```bash
python -m pytest tests
```

## API

- `POST /api/auth/voucher` JSON: `{"code":"XXXX-XXXX-XXXX-XXXX"}`; sets an HttpOnly, SameSite=Strict session cookie.
- `GET /api/session` returns the active session allowance.
- `POST /api/logout` ends the portal session and clears its cookie.
- `GET /health` health check.

The portal uses the direct peer IP from the HTTP connection; it does not trust X-Forwarded-For. The backend checks that IP against `HOTSPOT_CIDR` and resolves its MAC using `ip neigh` on `HOTSPOT_INTERFACE`. This depends on the portal being reached directly on the hotspot LAN, not through an untrusted reverse proxy.

## Host-specific configuration and safety

All machine-specific IP addresses, interface names, subnet details and secrets belong in local `.env` configuration. The tracked `.env.example` contains placeholders only.

Firewall integration remains disabled (`FIREWALL_ENABLED=false`, `FIREWALL_BACKEND=none`). Do not enable it until the upstream Ethernet and hotspot Wi-Fi interfaces are positively identified and firewall rules are reviewed locally. Keep console access available during later firewall work.

A captive portal cannot transparently redirect arbitrary HTTPS traffic. The later implementation will use operating-system captive-network detection and HTTP portal discovery.

## Roadmap

1. Foundation (complete)
2. Voucher authentication and session foundation (implemented; requires host configuration and live integration tests)
3. Hostapd/dnsmasq setup and nftables gateway rules
4. Per-client traffic accounting and quota enforcement
5. User dashboard and logout experience
6. Admin dashboard, voucher batches and reports
7. systemd deployment, recovery and security testing
