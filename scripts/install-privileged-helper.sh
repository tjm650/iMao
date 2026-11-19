#!/usr/bin/env bash
# Install the tiny root-owned helper and a command-scoped sudoers rule.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${1:-}"
if [[ -z "$SERVICE_USER" ]] || ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Usage: sudo $0 SERVICE_USER (the Linux account running the wiMao API)" >&2
  exit 2
fi
command -v visudo >/dev/null
install -d -o root -g root -m 0755 /usr/local/lib/wimao /etc/wimao
install -o root -g root -m 0750 "$ROOT/scripts/wimao-netctl.py" /usr/local/lib/wimao/wimao-netctl.py
cat > /usr/local/sbin/wimao-netctl <<'WRAPPER'
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/local/lib/wimao/wimao-netctl.py "$@"
WRAPPER
chown root:root /usr/local/sbin/wimao-netctl
chmod 0750 /usr/local/sbin/wimao-netctl
if [[ ! -f /etc/wimao/netctl.json ]]; then
  install -o root -g root -m 0600 "$ROOT/config/netctl.json.example" /etc/wimao/netctl.json
fi
cat > /etc/sudoers.d/wimao-netctl <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: /usr/local/sbin/wimao-netctl authorize *, /usr/local/sbin/wimao-netctl revoke *, /usr/local/sbin/wimao-netctl stats *
EOF
chmod 0440 /etc/sudoers.d/wimao-netctl
visudo -cf /etc/sudoers.d/wimao-netctl
echo "Helper installed. Edit /etc/wimao/netctl.json as root with the actual hotspot interface and CIDR."
