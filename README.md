# iMao

A lightweight, self-hosted Wi-Fi captive portal and voucher-based bandwidth manager for a Linux laptop acting as the gateway.

## Current status

Implemented:
- FastAPI application, single-use voucher authentication and database-backed sessions
- Environment-based configuration; host-specific interface names, addresses and Wi-Fi credentials are never hard-coded
- Read-only network discovery and rendered hostapd/dnsmasq/nftables configuration
- Isolated nftables policy with an expiring IPv4 authorization set and NAT masquerading
- Root-owned, command-allow-listed network helper (installed separately) for client authorization, revocation and directional byte counters
- Voucher login can authorize a client when the optional nftables integration is explicitly enabled
- Periodic traffic accounting persists per-session upload/download totals and voucher usage
- Session expiry, logout and quota exhaustion revoke the client authorization
- Additive SQLite migrations preserve existing Stage 1–3 databases

Still pending:
- Target-Linux-host integration tests and review of the actual nftables JSON/counter behavior
- Exact hard quota enforcement (polling-based enforcement can exceed the quota by traffic sent between polling cycles and in-flight packets)
- Hostapd/dnsmasq service installation and safe startup/rollback
- Captive portal detection, HTTP interception, administrator dashboard, production deployment and recovery testing

## Requirements

- Ubuntu/Debian Linux, Python 3.10+
- Ethernet connection for upstream internet
- Wi-Fi adapter capable of access-point mode
- `iproute2`, `iw`, `hostapd`, `dnsmasq`, `nftables`
- Root privileges only for the separately installed network helper and later host service commands

## Development setup

```bash
git clone https://github.com/tjm650/iMao.git
cd iMao
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Generate a strong application secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put it in local `.env` as `APP_SECRET_KEY`. Never commit `.env`.

## Stage 3: inspect and prepare the network

### 1. Discover interfaces (read-only)

```bash
python scripts/imao-network.py discover
```

Review the default route, Ethernet candidate, Wi-Fi interfaces and AP-mode support. The command does not change interfaces, routes, services or firewall rules. Do not assume interface names.

### 2. Fill in local network values

Edit `.env` on the laptop. Set:
- `UPSTREAM_INTERFACE`: the interface used by the default internet route (Ethernet)
- `HOTSPOT_INTERFACE`: the Wi-Fi adapter selected for AP mode
- `HOTSPOT_CIDR` and `HOTSPOT_GATEWAY`: a subnet/gateway chosen after checking for conflicts with existing networks
- `HOTSPOT_SSID`, `HOTSPOT_PASSPHRASE` and `WIFI_COUNTRY_CODE`: your Wi-Fi settings

The renderer rejects unresolved placeholders, identical interface names, invalid subnet/gateway combinations, weak WPA2 passphrases and invalid interface names. Keep `runtime-config/hostapd.conf` private because it contains the Wi-Fi passphrase.

### 3. Render service configurations

```bash
python scripts/imao-network.py render
```

This writes local-only files under ignored `runtime-config/`. Rendering does not install packages, assign addresses, start services or alter firewall rules.

### 4. Review nftables rules without applying them

```bash
sudo scripts/imao-firewall.sh check
```

This is a syntax check only. Keep `FIREWALL_ENABLED=false` until the actual host interfaces, subnet and generated rules have been reviewed. Do not run the firewall installer just to test the app.

## Stage 4: session authorization and quota accounting

Stage 4 connects successful voucher redemption to the dedicated nftables authorization set. The FastAPI process is **not** run as root. It invokes a small helper through a command-scoped sudoers rule.

### 1. Prepare the helper configuration

After the Stage 3 interface and subnet values are confirmed, install the helper for the Linux account that runs the API:

```bash
sudo bash scripts/install-privileged-helper.sh IMAO_SERVICE_USER
```

Replace `IMAO_SERVICE_USER` with the actual Linux service account. The installer places the executable under root-owned system directories, creates a root-owned config template at `/etc/imao/netctl.json`, and adds a sudoers allow-list for only `authorize`, `revoke` and `stats`. It does not apply firewall rules.

Edit `/etc/imao/netctl.json` as root. It must contain the actual `hotspot_interface` and `hotspot_cidr` values. Protect the file as root-owned and not writable by the API account. The helper validates every client IPv4 address against this subnet and never executes shell commands.

Validate the sudoers entry:

```bash
sudo visudo -c
```

### 2. Configure the API

In the local, uncommitted `.env`, set:

```dotenv
FIREWALL_BACKEND=nftables
FIREWALL_ENABLED=true
NETCTL_PATH=/usr/local/sbin/imao-netctl
NETCTL_SUDO=/usr/bin/sudo
SESSION_POLL_SECONDS=2
SESSION_MAX_HOURS=12
```

Do this only after the dedicated iMao nftables tables have been installed and reviewed. Voucher authentication returns an error rather than claiming success if the helper cannot authorize the client.

### 3. Accounting and enforcement behavior

- Each active client receives directional nftables counters for upload and download traffic.
- The accounting worker polls those counters, persists deltas in SQLite, and increments the voucher's cumulative `used_bytes`.
- Counter resets are handled as a new counter epoch; stored session totals are not reset.
- Logout, session expiry and quota exhaustion queue removal of the client's authorization and temporary counter rules. Failed revocations remain pending and are retried by the background worker; a new session for the same client IP is blocked until cleanup succeeds.
- The default voucher quota remains 500 MiB; session authorization expires after 12 hours by default.
- Accounting is serialized through SQLite write transactions so multiple API workers do not apply the same counter delta twice.

**Quota precision:** accounting polls every two seconds by default. A client may transfer additional data between polls or while packets are in flight, so this implementation is not a hard real-time byte cutoff. The recorded voucher usage is capped at its allowance, and forwarding is revoked as soon as the worker observes exhaustion. A stricter byte-exact quota mechanism is a separate follow-up.

### 4. Important activation boundary

Stage 4 code and helper installation do not themselves activate the host firewall. The firewall must already have the reviewed iMao tables and the API must be configured with the correct interfaces. Never run the app as root, never grant the service account unrestricted sudo, and never flush the global nftables ruleset.

## Application and vouchers

Start the app from the repository root:

```bash
uvicorn backend.app.main:app --reload
```

Generate a single-use voucher (default allowance: 500 MiB):

```bash
python scripts/create-voucher.py
python scripts/create-voucher.py --quota-mb 1000
```

The raw code is printed once; only its keyed hash is stored. Optional expiry must be timezone-aware ISO-8601.

## API

- `POST /api/auth/voucher` — redeem a voucher and, when explicitly enabled, authorize its client
- `GET /api/session` — retrieve session allowance and recorded upload/download usage
- `POST /api/logout` — end the portal session and revoke network authorization
- `GET /health` — health check

## Tests

```bash
python -m pytest tests
```

Tests have not been run on the target Linux laptop. Hardware capability, actual interface names, nftables behavior, sudoers permissions and end-to-end voucher enforcement must be verified there before enabling the firewall.

## Security and limitations

- All host-specific network values and secrets belong in the ignored local `.env` or root-owned `/etc/imao/netctl.json`.
- Never expose the development server directly to the public internet.
- Never redirect arbitrary HTTPS requests to the portal; browsers will reject certificate mismatches.
- Do not run the FastAPI service as root.
- Keep the firewall disabled until the network and rollback path have been reviewed.

## Roadmap

1. Project foundation
2. Voucher authentication and session foundation
3. Host network discovery, AP/DHCP/DNS templates and isolated nftables policy (target-host validation pending)
4. Privileged session authorization bridge, per-client traffic accounting and quota enforcement (implementation committed; target-host validation pending)
5. Captive portal detection and client experience
6. Admin dashboard, voucher batches and reports
7. systemd deployment, recovery and security testing
