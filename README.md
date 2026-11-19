# iMao

A lightweight, self-hosted Wi-Fi captive portal and voucher-based bandwidth manager. iMao is being developed as a platform that an operator can prepare on a Linux computer and connect to their own Ethernet/Wi-Fi hardware when ready to deploy.

## Development approach

**The current priority is to build and test the iMao application itself.** Do not configure the user's Wi-Fi adapter, change routes, start hotspot services, or activate firewall rules as part of ordinary application development.

The eventual iMao operator will run the Linux host commands in this README on the computer that will act as the gateway. Those commands are not run by GitHub and are not automatically executed by the application. Hardware-specific values must be discovered and supplied on that computer at deployment time.

## Current implementation status

Implemented:
- FastAPI application and single-use voucher authentication
- SQLite-backed vouchers, sessions, login throttling and usage accounting fields
- Environment-based configuration; host-specific interface names, addresses and Wi-Fi credentials are not hard-coded
- Read-only network discovery and local hostapd/dnsmasq/nftables configuration rendering
- Isolated nftables policy with an expiring IPv4 authorization set and NAT masquerading
- Separate root-owned, command-allow-listed helper for client authorization, revocation and directional byte counters
- Optional voucher-to-network authorization bridge
- Background traffic accounting, session expiry and queued revocation retries
- Automated Python test workflow in GitHub Actions

Still pending:
- Full integration testing on supported Linux gateway hardware
- Verification of actual nftables JSON/counter behavior on target distributions
- Hard byte-exact quota enforcement (polling-based enforcement can exceed the limit between polls and during in-flight packets)
- Reliable hostapd/dnsmasq setup, static hotspot address management and service lifecycle/rollback
- OS captive-portal probes, RFC 8908 API, HTTP-only unauthenticated interception, optional Caddy TLS template and RFC 8910 DHCPv4 option 114 generation
- Complete administration dashboard, voucher management, reporting, production deployment, monitoring and recovery testing

## Requirements

### Development computer
- Linux, preferably a current Ubuntu or Debian release
- Python 3.10 or newer
- Git
- Internet access to install Python dependencies

### Eventual gateway computer
- Linux (Ubuntu/Debian instructions below)
- Ethernet connection for upstream internet
- Wi-Fi adapter that supports access-point (AP) mode
- iproute2, iw, hostapd, dnsmasq and nftables
- Administrative (sudo) access for later network-service installation
- The gateway must be able to keep its Ethernet connection while the Wi-Fi adapter is used as an access point

The development computer and gateway can be the same Linux computer. Do not assume the Wi-Fi adapter supports AP mode until it has been checked.

---

# Linux terminal command reference

The following is the command checklist for the person installing or developing iMao. Run commands from a Linux terminal. Commands that change host networking or firewall state are clearly marked as later deployment operations and should not be run during ordinary application development.

## A. Prepare a Linux computer

On Ubuntu/Debian, install the development and network inspection tools:

~~~bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip iproute2 iw
~~~

The following packages are needed on the eventual gateway when preparing the Wi-Fi access point and firewall. They can be installed now or at deployment time:

~~~bash
sudo apt install -y hostapd dnsmasq nftables
~~~

Check the installed tools:

~~~bash
git --version
python3 --version
ip -Version
iw --version
nft --version
~~~

## B. Download the iMao source code

Clone the repository and enter its directory:

~~~bash
git clone https://github.com/tjm650/iMao.git
cd iMao
~~~

If the repository is already cloned, update it instead:

~~~bash
cd iMao
git pull origin main
~~~

## C. Create the Python environment and install dependencies

Run these commands from the repository root:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
~~~

Whenever the terminal is reopened, activate the environment again:

~~~bash
cd iMao
source .venv/bin/activate
~~~

## D. Create the local environment configuration

Create a local configuration file:

~~~bash
cp .env.example .env
nano .env
~~~

Generate a strong application secret:

~~~bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
~~~

Copy the generated value into APP_SECRET_KEY in .env. Keep .env private and do not commit it. The example file contains placeholders for the gateway's interface names, hotspot subnet, SSID and Wi-Fi password; those values must be filled in on the actual gateway after network discovery.

## E. Run the automated tests and code checks

Run the test suite:

~~~bash
python -m pytest -q tests
~~~

Compile-check Python source files:

~~~bash
python -m compileall -q backend scripts tests
~~~

These commands check application code. They do not configure the Wi-Fi adapter or change firewall settings.

## F. Start the application for local development

From the repository root, with the virtual environment active:

~~~bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
~~~

Open the local development portal at:

~~~text
http://127.0.0.1:8000
~~~

For a gateway deployment, the host binding and exposure policy will need to be configured deliberately. Do not expose the development server directly to the public internet. Stop the development server with Ctrl+C.

## G. Create test vouchers

With the virtual environment active and from the repository root:

~~~bash
python scripts/create-voucher.py
~~~

Create a voucher with a different quota (example: 1000 MiB):

~~~bash
python scripts/create-voucher.py --quota-mb 1000
~~~

The voucher code is shown once. Save it securely for testing; the raw code is not stored in the database.

## H. Discover the eventual gateway's network hardware (read-only)

Run this on the Linux computer that will provide the hotspot:

~~~bash
ip -br address
ip route
iw dev
iw list
python scripts/imao-network.py discover
~~~

The iMao discovery command reports the default route, network interfaces and whether AP mode appears to be supported. It is read-only: it does not change interface addresses, routes, services or firewall rules.

Identify:
- The Ethernet interface carrying the default route (upstream)
- The Wi-Fi interface intended for the hotspot
- Whether the Wi-Fi adapter advertises AP mode
- Existing LAN/VPN subnets that the proposed hotspot subnet must not overlap

Do not guess interface names or choose a subnet that overlaps an existing network. If AP mode is unavailable, use a compatible Wi-Fi adapter before proceeding.

## I. Configure and render local network templates (deployment preparation only)

Only after the hardware and non-overlapping hotspot subnet have been identified, edit the local configuration:

~~~bash
nano .env
~~~

Set the actual values for:
- UPSTREAM_INTERFACE — Ethernet interface used for internet access
- HOTSPOT_INTERFACE — Wi-Fi interface supporting AP mode
- HOTSPOT_CIDR and HOTSPOT_GATEWAY — selected hotspot subnet and gateway
- HOTSPOT_SSID, HOTSPOT_PASSPHRASE and WIFI_COUNTRY_CODE — Wi-Fi settings

Render the local configuration files:

~~~bash
python scripts/imao-network.py render
~~~

This creates files under runtime-config/. The hostapd file contains the Wi-Fi passphrase; keep it private. Rendering does not assign the gateway address, start hostapd/dnsmasq or apply firewall rules.

If PORTAL_PUBLIC_URL is configured, review the generated Caddyfile. Ensure public DNS points to the gateway and ACME validation can reach Caddy on TCP 80/443. Set COOKIE_SECURE=true in the production .env. When FastAPI is behind Caddy, trust forwarded headers only from 127.0.0.1.

Review the generated files:

~~~bash
sed -n '1,200p' runtime-config/hostapd.conf
sed -n '1,200p' runtime-config/dnsmasq.conf
sed -n '1,240p' runtime-config/nftables.conf
sed -n '1,160p' runtime-config/Caddyfile
~~~

Do not share the hostapd output publicly because it contains the Wi-Fi password.

## J. Validate firewall syntax without applying it

After rendering, run:

~~~bash
sudo scripts/imao-firewall.sh check
~~~

This runs nftables syntax validation only. It does not load rules. Keep these settings in the local .env during development and until a reviewed deployment:

~~~dotenv
FIREWALL_BACKEND=none
FIREWALL_ENABLED=false
~~~

## K. Later deployment-only commands — do not run during app development

These commands are documented for the future gateway operator. They require confirmed interface/subnet values, a reviewed rollback plan and a deliberate decision to activate the hotspot. The current development phase does not require them.

### Install the restricted privileged helper

First identify the unprivileged Linux account that will run the iMao API. Then, from the repository root:

~~~bash
sudo bash scripts/install-privileged-helper.sh LINUX_SERVICE_USERNAME
~~~

Replace LINUX_SERVICE_USERNAME with the actual account name. The installer creates a root-owned helper and a narrowly scoped sudoers entry; it does not install or activate the iMao firewall.

Edit the root-owned helper configuration:

~~~bash
sudo nano /etc/imao/netctl.json
sudo chown root:root /etc/imao/netctl.json
sudo chmod 600 /etc/imao/netctl.json
sudo visudo -c
~~~

Set the real hotspot_interface and hotspot_cidr in that JSON file. Do not make it writable by the API service account.

### Firewall activation is a separate, high-impact step

**Do not run this until the generated rules, interface names, address plan and rollback procedure have been reviewed.** The firewall script changes only the dedicated iMao tables, but a wrong interface or subnet can still interrupt hotspot connectivity.

Only when a gateway deployment has been explicitly approved:
1. Back up the existing firewall configuration using the distribution's normal firewall-management procedure.
2. Confirm the Ethernet default route and hotspot interface one more time.
3. Set FIREWALL_BACKEND=nftables and FIREWALL_ENABLED=true in the local .env.
4. Apply the dedicated iMao rules:

~~~bash
sudo scripts/imao-firewall.sh install --confirm
sudo scripts/imao-firewall.sh status
~~~

The removal command removes only iMao's dedicated tables. It is a recovery operation and should only be used after understanding the effect on connected hotspot clients:

~~~bash
sudo scripts/imao-firewall.sh remove --confirm
~~~

Do not use nft flush ruleset; it would remove rules belonging to other host services and could disrupt connectivity.

**Important:** hostapd/dnsmasq installation, static hotspot IP assignment, service startup and complete firewall rollback are still being developed and documented. Do not assume the commands above alone create a fully working hotspot.

---

## Stage 3: network configuration details

The renderer validates unresolved placeholders, distinct interface names, subnet/gateway relationship, country code, SSID length and WPA2 passphrase length. DHCP range is derived from the configured subnet. If PORTAL_PUBLIC_URL is set to an HTTPS DNS origin, it also generates a Caddy TLS reverse-proxy configuration, a local DNS override for the portal hostname and DHCPv4 option 114 containing the RFC 8908 API URI. Generated files are local-only and excluded from Git.

The templates currently provide:
- hostapd WPA2-PSK/CCMP access point configuration
- dnsmasq DHCP and DNS configuration bound to the hotspot interface
- nftables forwarding policy, expiring client authorization set and NAT masquerading

## Stage 4: session authorization and quota accounting

When explicitly enabled on a prepared gateway:
- Successful voucher redemption calls the restricted helper to authorize the client's IPv4 address.
- Upload and download counters are read from the dedicated iMao nftables forwarding chain.
- Usage deltas are persisted in SQLite and accumulated against the voucher's quota.
- Logout, session expiry and quota exhaustion queue network revocation; failed revocations are retried.
- The helper accepts only configured-hotspot-subnet IPv4 addresses and does not invoke a shell with client-supplied arguments.

**Quota precision:** accounting polls every two seconds by default. Some extra data can pass between polls or while packets are in flight. Usage is capped in the database at the voucher allowance, and forwarding is revoked when the worker observes exhaustion. This is not byte-exact real-time enforcement yet.

## Captive portal detection and HTTPS setup

iMao now provides HTTP probe handlers for common operating-system checks. Unauthenticated clients receive an HTTP 302 redirect to the voucher portal; active clients receive the platform's expected online response. These handlers support probe-based detection and must be reached through the eventual gateway's HTTP interception/redirect rules. They do not intercept HTTPS.

- Android: `/generate_204` and `/gen_204` return HTTP 204 for authorized clients.
- Apple iOS/macOS: `/hotspot-detect.html` returns a small HTML page containing `Success`.
- Windows: `/connecttest.txt` returns `Microsoft Connect Test`; legacy `/ncsi.txt` returns `Microsoft NCSI`.
- Firefox: `/success.txt` and `/canonical.html` return `success`.
- RFC 8908: `/api/captive-portal` returns the per-client `captive` boolean using the `application/captive+json` media type.

For gateway deployment, set `PORTAL_PUBLIC_URL=https://portal.example.com` in the local `.env` to a DNS hostname you control. The renderer then:
- Adds an nftables prerouting redirect for unauthenticated hotspot IPv4 TCP port 80 traffic to the local portal. Authorized clients are excluded. TCP 443 is never redirected.
- Generates a Caddyfile that reverse-proxies the HTTPS hostname to FastAPI. Caddy obtains and renews a publicly trusted certificate when public DNS points to the gateway and inbound TCP ports 80 and 443 can reach Caddy (or another supported ACME challenge path is configured).
- Adds a dnsmasq local DNS override so hotspot clients resolve the public portal hostname to the hotspot gateway address.
- Advertises `https://portal.example.com/api/captive-portal` through DHCPv4 option 114. This MUST be the RFC 8908 API URI, not the user-facing portal URL.
- Returns `user-portal-url` from the RFC 8908 API.

The generated Caddyfile is a deployment template; Caddy is not installed or started automatically. In production, FastAPI must listen on the gateway interfaces so the local nftables HTTP redirect can reach it; the generated input policy blocks the raw FastAPI port from the upstream interface, while Caddy proxies to `127.0.0.1`. Configure Uvicorn to trust forwarded headers only from loopback (for example, `--proxy-headers --forwarded-allow-ips=127.0.0.1`) so the API can identify hotspot client addresses without trusting arbitrary forwarded headers. Set `COOKIE_SECURE=true` when using HTTPS; the renderer refuses to generate public-portal configuration if this is disabled.

**Important limitations:** the current gateway policy is IPv4-only; IPv6 captive enforcement and DHCPv6/RA option delivery remain pending. HTTP interception is limited to unauthenticated client TCP port 80. HTTPS is never intercepted. Caddy's public certificate issuance requires a reachable public DNS name and an ACME challenge path. The gateway operator must arrange router port forwarding or another supported ACME method; iMao does not supply a domain or certificate.


- GET /api/captive-portal — RFC 8908 captive-state API
- GET /generate_204, /hotspot-detect.html, /connecttest.txt — OS connectivity probes
- GET /health — application health check
- GET / — voucher portal
- POST /api/auth/voucher — redeem a voucher
- GET /api/session — session and usage status
- POST /api/logout — end the current session
- GET /connected — connected-session page

## Security notes

- Keep .env, runtime-config/hostapd.conf, the SQLite database and voucher codes private.
- Never commit real interface names, network addresses, Wi-Fi passwords or application secrets.
- Do not run FastAPI as root.
- Do not expose the development server directly to the public internet.
- Do not redirect arbitrary HTTPS traffic to the portal; browsers will reject certificate mismatches.
- Keep firewall activation disabled until the network configuration and rollback path have been reviewed.
- The privileged helper is intentionally separate from the FastAPI process and must remain root-owned.

## Roadmap

1. Project foundation
2. Voucher authentication and session foundation
3. Host network discovery, AP/DHCP/DNS templates and isolated nftables policy (target-host validation pending)
4. Privileged session authorization bridge, per-client traffic accounting and quota enforcement (implementation committed; target-host validation pending)
5. Captive portal detection and client experience (HTTP interception, optional Caddy TLS template and DHCPv4 option 114 renderer implemented; deployment validation and IPv6 support pending)
6. Admin dashboard, voucher batches and reports
7. systemd deployment, recovery and security testing
