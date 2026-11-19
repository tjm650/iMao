# iMao

A lightweight, self-hosted Wi-Fi captive portal and voucher-based bandwidth manager for a Linux laptop acting as the gateway.

## Current status

Implemented:
- FastAPI application, voucher authentication and database-backed sessions
- Environment-based configuration; host-specific interface names, addresses and Wi-Fi credentials are never hard-coded
- Read-only network discovery for Ethernet/Wi-Fi interfaces, default routes and Wi-Fi AP-mode capability
- Rendered hostapd and dnsmasq configuration templates
- Isolated nftables policy with an expiring IPv4 authorization set and NAT masquerading
- Explicit firewall check/install/authorize/revoke/status/remove commands scoped to iMao-owned nftables tables

Not yet implemented: automatic service installation/activation, automatic firewall authorization from the voucher login, traffic accounting, quota-triggered disconnection, captive HTTP redirects, admin dashboard or production deployment. A voucher login does not yet automatically enable internet access; the authorization bridge and accounting are the next stage.

## Requirements

- Ubuntu/Debian Linux, Python 3.10+
- Ethernet connection for upstream internet
- Wi-Fi adapter capable of access-point mode
- `iproute2`, `iw`, `hostapd`, `dnsmasq`, `nftables`
- Root privileges only for later host service/firewall commands

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

This reports:
- Default route and its interface (candidate Ethernet upstream)
- Detected wireless interfaces and their current addresses
- Whether the Wi-Fi hardware/driver advertises AP mode

The command does not change interfaces, routes, services or firewall rules. Review the output before choosing `UPSTREAM_INTERFACE` and `HOTSPOT_INTERFACE`. The Wi-Fi adapter must support AP mode. Do not assume the interface names.

### 2. Fill in local network values

Edit `.env` on the laptop. Set:
- `UPSTREAM_INTERFACE`: the interface used by the default internet route (Ethernet)
- `HOTSPOT_INTERFACE`: the Wi-Fi adapter selected for AP mode
- `HOTSPOT_CIDR` and `HOTSPOT_GATEWAY`: a subnet/gateway chosen after checking for conflicts with existing networks
- `HOTSPOT_SSID`, `HOTSPOT_PASSPHRASE` and `WIFI_COUNTRY_CODE`: your Wi-Fi settings

The renderer rejects unresolved placeholders, identical interface names, invalid subnet/gateway combinations, weak WPA2 passphrases and invalid interface names. Do not copy an example subnet without checking that it does not overlap with the Ethernet LAN or a VPN route.

### 3. Render service configurations

```bash
python scripts/imao-network.py render
```

This writes local-only files under the ignored `runtime-config/` directory:
- `hostapd.conf`
- `dnsmasq.conf`
- `nftables.conf`

The hostapd template uses WPA2-PSK/CCMP. The dnsmasq template serves DHCP and DNS on the hotspot and uses the host's configured upstream DNS resolvers. Rendering does not install packages, assign addresses, start services or alter firewall rules. Keep `runtime-config/hostapd.conf` private because it contains the Wi-Fi passphrase.

### 4. Review nftables rules without applying them

Install the OS packages only after reviewing the discovered hardware and interface details. Then validate the generated ruleset:

```bash
sudo scripts/imao-firewall.sh check
```

This runs nftables' syntax check only. It does not apply rules. The ruleset:
- Creates only the dedicated `inet imao` and `ip imao_nat` tables
- Allows DHCP, DNS and the portal listener from the hotspot
- Allows forwarding from hotspot clients only when their IPv4 address is in the expiring `authorized_v4` set
- Drops other forwarded traffic arriving from the hotspot
- Masquerades hotspot-subnet traffic out of the configured upstream interface
- Leaves unrelated nftables tables untouched

**Firewall activation is opt-in and remains disabled by default.** Only after reviewing the generated file, confirming both interfaces and retaining local console access, set `FIREWALL_ENABLED=true` in local `.env`. Then the explicit command is:

```bash
sudo scripts/imao-firewall.sh install --confirm
```

It replaces only the two iMao-owned tables. It does not flush the entire ruleset. Nevertheless, incorrect network settings can interrupt hotspot access; keep physical/local access to the laptop.

Add or remove a client manually (temporary authorization only):

```bash
sudo scripts/imao-firewall.sh authorize CLIENT_IPV4 12h
sudo scripts/imao-firewall.sh revoke CLIENT_IPV4
sudo scripts/imao-firewall.sh status
```

Replace `CLIENT_IPV4` with a real hotspot client address. Do not run these examples literally. The current voucher endpoint is not yet wired to this privileged operation; that integration will use a narrowly scoped helper in the next stage.

To remove only the iMao firewall tables:

```bash
sudo scripts/imao-firewall.sh remove --confirm
```

## Application and vouchers

Start the app from the repository root:

```bash
uvicorn backend.app.main:app --reload
```

Generate a single-use voucher (default allowance: 500 MB):

```bash
python scripts/create-voucher.py
python scripts/create-voucher.py --quota-mb 1000
```

The raw code is printed once; only its keyed hash is stored. Optional expiry must be timezone-aware ISO-8601.

## API

- `POST /api/auth/voucher` — redeem a voucher and create a portal session
- `GET /api/session` — retrieve session allowance
- `POST /api/logout` — end the portal session
- `GET /health` — health check

## Tests

```bash
python -m pytest tests
```

Tests have not been run on the target laptop yet. Hardware capability, actual interface names, package availability and firewall behavior must be verified on that machine.

## Security and limitations

- All host-specific network values and secrets belong in the ignored local `.env`.
- Never expose the development server directly to the public internet.
- Never redirect arbitrary HTTPS requests to the portal; browsers will reject certificate mismatches.
- Firewall authorization is currently manual and temporary; voucher-to-firewall integration and byte accounting are not yet complete.
- Do not enable persistent firewall automation until the host's existing firewall and routing setup has been reviewed.

## Roadmap

1. Project foundation
2. Voucher authentication and session foundation
3. Host network discovery, AP/DHCP/DNS templates and isolated nftables policy (configuration tooling implemented; target-host validation pending)
4. Privileged session authorization bridge, per-client traffic accounting and quota enforcement
5. Captive portal detection and client experience
6. Admin dashboard, voucher batches and reports
7. systemd deployment, recovery and security testing
