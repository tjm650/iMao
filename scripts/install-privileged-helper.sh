#!/usr/bin/env bash
# Install the tiny root-owned helper and a command-scoped sudoers rule.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${1:-}"
if [[ -z "$SERVICE_USER" ]] || ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Usage: sudo $0 SERVICE_USER (the Linux account running the iMao API)" >&2
  exit 2
fi
command -v visudo >/dev/null
install -d -o root -g root -m 0755 /usr/local/lib/imao /etc/imao
install -o root -g root -m 0750 "$ROOT/scripts/imao-netctl.py" /usr/local/lib/imao/imao-netctl.py
cat > /usr/local/sbin/imao-netctl <<'WRAPPER'
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/local/lib/imao/imao-netctl.py "$@"
WRAPPER
chown root:root /usr/local/sbin/imao-netctl
chmod 0750 /usr/local/sbin/imao-netctl
cat > /etc/sudoers.d/imao-netctl <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: /usr/local/sbin/imao-netctl authorize *, /usr/local/sbin/imao-netctl revoke *, /usr/local/sbin/imao-netctl stats *
EOF
chmod 0440 /etc/sudoers.d/imao-netctl
visudo -cf /etc/sudoers.d/imao-netctl
echo "Helper installed. Create /etc/imao/netctl.json as root with hotspot_interface and hotspot_cidr."
