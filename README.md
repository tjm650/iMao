# iMao

A lightweight, self-hosted Wi-Fi captive portal and voucher-based bandwidth manager for a Linux laptop acting as the gateway.

## Current implementation status

The repository currently contains the initial project foundation:

- FastAPI application and health endpoint
- Environment-based configuration
- SQLite schema for users, vouchers and sessions
- Reusable quota calculations
- Mobile-first voucher portal shell
- Initial quota unit tests

**The captive portal is not yet enforcing network access.** Voucher authentication, nftables integration, traffic accounting, admin functions and hotspot setup are subsequent implementation stages. Do not expose this initial service as a production gateway.

## Architecture

- `frontend/`: plain HTML, CSS and JavaScript
- `backend/`: FastAPI application and business logic
- `database/`: SQLite schema and connection helpers
- `config/`: environment template and firewall configuration
- `scripts/`: host setup and installation scripts
- `systemd/`: service unit
- `tests/`: automated tests

## Requirements

- Ubuntu or Debian Linux
- Python 3.10+
- Ethernet connection for upstream internet
- A separate Wi-Fi adapter capable of access-point mode
- hostapd, dnsmasq and nftables (for the later gateway stage)

## Initial development setup

1. Clone the repository.
2. Create a virtual environment.
3. Install backend dependencies.
4. Copy `.env.example` to `.env`.
5. Replace the interface and network placeholders with values discovered on the host.
6. Set a strong random `APP_SECRET_KEY`.

Example:

```bash
git clone https://github.com/tjm650/iMao.git
cd iMao
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Run the initial development server from the repository root:

```bash
uvicorn backend.app.main:app --reload
```

Open the portal at `http://127.0.0.1:8000` and health check at `http://127.0.0.1:8000/health`.

Run tests:

```bash
python -m pytest tests
```

## Network configuration policy

All machine-specific interface names, addresses, subnet details and secrets belong in the local `.env` file. Never commit that file. The tracked `.env.example` contains placeholders only.

The initial configuration assumes Ethernet upstream and voucher authentication, with a default quota of 500 MB. The hotspot interface and gateway network are intentionally unspecified until inspected on the target laptop.

## Safety

- Do not enable firewall automation until the upstream and hotspot interfaces have been positively identified.
- Keep local console access available while changing firewall rules.
- The production firewall must default-deny unauthenticated forwarding and allow only explicitly authorized client identities.
- A captive portal cannot decrypt or transparently redirect arbitrary HTTPS traffic.
- Data enforcement must use cumulative counter deltas and persist usage so restarting the service cannot reset a user's quota.

## Roadmap

1. Project foundation (current)
2. Voucher authentication and secure session handling
3. Hostapd/dnsmasq setup and nftables gateway rules
4. Per-client traffic accounting and quota enforcement
5. User status page and logout
6. Admin dashboard, voucher batches and CSV reports
7. systemd deployment, recovery and security tests
