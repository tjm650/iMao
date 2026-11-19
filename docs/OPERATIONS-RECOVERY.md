# iMao network recovery and rollback runbook

This runbook is for the eventual Linux gateway operator. It is not an instruction to activate the gateway during development. Use a local console or out-of-band management path before changing network services; a remote SSH session can be disconnected by a network rollback.

## 1. Recovery principles

- Preserve the host's existing firewall and network manager configuration. iMao owns only the dedicated nftables tables `inet imao` and `ip imao_nat`.
- Never run `nft flush ruleset`, flush another application's table, or replace the host's complete firewall configuration as an iMao rollback.
- Keep a copy of the pre-deployment firewall configuration and network-manager configuration outside the iMao repository, with permissions appropriate to any secrets they contain.
- Record the actual interface names, addresses, routes, service names and the exact change window in the operator's deployment record. Do not infer these values.
- Prefer console access. Do not perform the first firewall or interface transition over the only management connection.

## 2. Before enabling network services

1. Confirm the Ethernet upstream and Wi-Fi AP-capable adapter using the read-only discovery commands in the README.
2. Confirm the hotspot subnet does not overlap any existing LAN, VPN, or upstream subnet.
3. Save the current host network configuration and the output of `ip -br address`, `ip route`, `iw dev`, and `sudo nft list ruleset` to a protected, timestamped operator backup location.
4. Validate generated configuration files and run `sudo scripts/imao-firewall.sh check`. This is syntax-only and does not apply rules.
5. Validate the systemd unit files using the procedure in the README. Review `systemd-analyze security` output rather than treating a score as proof of security.
6. Confirm a local console or out-of-band recovery path and have a second operator review the rollback commands.
7. Keep `FIREWALL_ENABLED=false` until the operator explicitly approves activation.

## 3. Symptoms and initial diagnosis

For an unavailable portal, failed client authentication, or loss of hotspot connectivity, collect diagnostics before changing state:

```bash
sudo systemctl status imao --no-pager
sudo systemctl status hostapd dnsmasq caddy --no-pager
sudo journalctl -u imao -n 150 --no-pager
sudo journalctl -u hostapd -n 100 --no-pager
sudo journalctl -u dnsmasq -n 100 --no-pager
sudo journalctl -u caddy -n 100 --no-pager
ip -br address
ip route
iw dev
sudo nft list table inet imao
sudo nft list table ip imao_nat
```

A missing service or table is not, by itself, a reason to alter unrelated host configuration. Preserve logs and identify the failing layer first.

## 4. Stop iMao services safely

Use the local console. Stop the portal before stopping its supporting services:

```bash
sudo systemctl stop imao
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq
```

Stop Caddy only if it is dedicated to this iMao deployment and no other site depends on it:

```bash
sudo systemctl stop caddy
```

Do not disable or mask shared host services as a troubleshooting shortcut. If the backup or monitoring timers were enabled, stop their timers before changing their configuration:

```bash
sudo systemctl stop imao-offsite-backup.timer imao-monitor.timer
```

## 5. Roll back only iMao firewall tables

First inspect the tables and confirm they belong to this deployment:

```bash
sudo scripts/imao-firewall.sh status
```

Then, only if the iMao tables are present and the operator has approved rollback:

```bash
sudo scripts/imao-firewall.sh remove --confirm
```

This command deletes only `inet imao` and `ip imao_nat`. It does not restore any previous host firewall state and it does not change interface addresses, routes, hostapd, dnsmasq, or Caddy. Removing the tables disconnects or blocks clients that depended on iMao forwarding. Do not use it as a generic repair command.

If the iMao script is unavailable, the equivalent narrowly scoped commands are:

```bash
sudo nft delete table inet imao
sudo nft delete table ip imao_nat
```

Only run the command for a table confirmed to exist. Never substitute a global ruleset flush.

## 6. Restore host networking

The iMao firewall rollback does not reverse network-manager changes or restore a prior host firewall. Restore those from the operator's saved, host-specific configuration using the distribution's own network manager and firewall manager.

- Do not copy a guessed interface name or IP address from an example.
- Do not restart NetworkManager, systemd-networkd, or another network manager until its ownership of the affected interface is confirmed.
- If the gateway's management connection is lost, use local console/out-of-band access and the saved host configuration.
- Confirm the Ethernet default route and management access before restarting any iMao service.

## 7. Database recovery

Follow the separate backup and restore instructions in the README. Before restoring, stop `imao`, verify the decrypted backup with `scripts/imao-db.py verify`, and confirm that the database path is correct. The restore utility creates a pre-restore safety copy when the live database exists and refuses to proceed while SQLite WAL/SHM sidecars remain.

A successful SQLite integrity check proves file-level consistency, not that every application workflow or external backup is correct. After restore, start the application in a controlled maintenance window and verify readiness, administrator access, voucher metadata, and session state before reconnecting clients.

## 8. Controlled service recovery

After correcting the root cause and reviewing the host configuration:

1. Validate the systemd units and generated network configuration again.
2. Start only the dependencies required for the approved deployment, one at a time.
3. Check each service's status and journal.
4. Check `/health` and `/ready` locally.
5. Verify portal HTTPS and RFC 8908 responses from a test client.
6. Verify voucher redemption, traffic accounting, expiry and revocation with test vouchers.
7. Keep client access disabled until the firewall and forwarding path are confirmed.

## 9. Record the incident

Record UTC timestamps, software commit, host OS/kernel, changed files, commands run, service states, firewall table state, backup identifier, restore result, and reviewer. Do not include voucher codes, passwords, private age identities, webhook URLs, or unredacted client personal data in incident notes.

## 10. Explicitly out of scope until deployment approval

This repository does not install or enable systemd services/timers, configure the host network manager, start hostapd/dnsmasq, apply firewall rules, provision public DNS/TLS, or contact a real backup/alert provider. Those are operator actions for the identified gateway and must be validated there.
