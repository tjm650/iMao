#!/usr/bin/env bash
# Operates only on the dedicated wwiMao nftables tables. Never flushes global rules.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
NFT_FILE="$ROOT/runtime-config/nftables.conf"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env. Copy .env.example and configure the host first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

require_value() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" || "$value" == REPLACE_* ]]; then
    echo "Configure $name in .env first." >&2
    exit 1
  fi
}
require_value UPSTREAM_INTERFACE
require_value HOTSPOT_INTERFACE
require_value HOTSPOT_CIDR
[[ "$UPSTREAM_INTERFACE" != "$HOTSPOT_INTERFACE" ]] || { echo "Interfaces must differ." >&2; exit 1; }
command -v nft >/dev/null || { echo "nftables is not installed." >&2; exit 1; }

require_firewall_enabled() {
  [[ "${FIREWALL_ENABLED:-false}" == "true" ]] || {
    echo "FIREWALL_ENABLED must be true for commands that change firewall state." >&2
    exit 1
  }
}

case "${1:-}" in
  check)
    [[ -f "$NFT_FILE" ]] || { echo "Run scripts/wwimao-network.py render first." >&2; exit 1; }
    nft -c -f "$NFT_FILE"
    echo "Ruleset syntax is valid. No rules were applied."
    ;;
  install)
    require_firewall_enabled
    [[ "${2:-}" == "--confirm" ]] || { echo "Usage: sudo scripts/wwimao-firewall.sh install --confirm" >&2; exit 2; }
    [[ -f "$NFT_FILE" ]] || { echo "Run scripts/wwimao-network.py render first." >&2; exit 1; }
    nft -c -f "$NFT_FILE"
    # Replace only wwiMao's own tables; unrelated firewall tables are left untouched.
    nft delete table inet wwimao 2>/dev/null || true
    nft delete table ip wwimao_nat 2>/dev/null || true
    nft -f "$NFT_FILE"
    echo "wwiMao firewall tables installed. No client is authorized yet."
    ;;
  authorize)
    require_firewall_enabled
    [[ $# -eq 3 ]] || { echo "Usage: sudo scripts/wwimao-firewall.sh authorize CLIENT_IPV4 TTL (e.g. 12h)" >&2; exit 2; }
    python3 - "$2" <<'PY'
import ipaddress, sys
ipaddress.IPv4Address(sys.argv[1])
PY
    nft add element inet wwimao authorized_v4 "{ $2 timeout $3 }"
    ;;
  revoke)
    require_firewall_enabled
    [[ $# -eq 2 ]] || { echo "Usage: sudo scripts/wwimao-firewall.sh revoke CLIENT_IPV4" >&2; exit 2; }
    nft delete element inet wwimao authorized_v4 "{ $2 }"
    ;;
  status)
    nft list table inet wwimao
    nft list table ip wwimao_nat
    ;;
  remove)
    [[ "${2:-}" == "--confirm" ]] || { echo "Usage: sudo scripts/wwimao-firewall.sh remove --confirm" >&2; exit 2; }
    nft delete table inet wwimao 2>/dev/null || true
    nft delete table ip wwimao_nat 2>/dev/null || true
    echo "Only wwiMao's dedicated nftables tables were removed."
    ;;
  *)
    echo "Usage: $0 {check|install --confirm|authorize CLIENT_IPV4 TTL|revoke CLIENT_IPV4|status|remove --confirm}" >&2
    exit 2
    ;;
esac
