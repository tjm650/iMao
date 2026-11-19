import configparser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "config" / "systemd"


def _unit(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(path, encoding="utf-8")
    return parser


def test_systemd_templates_have_expected_sections_and_hardening():
    files = sorted(SYSTEMD.glob("*.example"))
    assert len(files) >= 5
    for path in files:
        unit = _unit(path)
        assert unit.sections(), path.name
        assert "Unit" in unit
        if path.name.endswith(".service.example"):
            assert "Service" in unit
            service = unit["Service"]
            assert service.get("User") == "imao"
            assert service.get("Group") == "imao"
            assert service.get("UMask") == "0077"
            assert service.get("ProtectSystem") == "strict"
            assert service.get("ProtectHome") == "true"
            assert service.get("ProtectKernelTunables") == "true"
            assert service.get("ProtectKernelModules") == "true"
            assert service.get("ProtectControlGroups") == "true"
        if path.name.endswith(".timer.example"):
            assert "Timer" in unit
            assert unit["Timer"].get("Persistent") == "true"
            assert unit["Timer"].get("Unit", "").endswith(".service")


def test_api_service_binds_loopback_and_uses_limited_forwarded_headers():
    unit = _unit(SYSTEMD / "imao.service.example")
    command = unit["Service"]["ExecStart"]
    assert "--host 127.0.0.1" in command
    assert "--forwarded-allow-ips=127.0.0.1" in command
    assert "0.0.0.0" not in command


def test_firewall_rollback_is_scoped_and_confirmation_gated():
    script = (ROOT / "scripts" / "imao-firewall.sh").read_text(encoding="utf-8")
    assert "nft flush ruleset" not in script
    assert "nft delete table inet imao" in script
    assert "nft delete table ip imao_nat" in script
    assert '[[ "${FIREWALL_ENABLED:-false}" == "true" ]]' in script
    assert '[[ "${2:-}" == "--confirm" ]]' in script
    assert re.search(r"remove\).*?--confirm", script, re.S)


def test_network_helper_uses_fixed_nft_binary_and_validates_client_subnet():
    helper = (ROOT / "scripts" / "imao-netctl.py").read_text(encoding="utf-8")
    assert '["/usr/sbin/nft", *args]' in helper
    assert "ipaddress.IPv4Address(raw_ip)" in helper
    assert "address not in network" in helper
    assert "shell=True" not in helper


def test_recovery_runbook_warns_against_global_firewall_flush():
    runbook = (ROOT / "docs" / "OPERATIONS-RECOVERY.md").read_text(encoding="utf-8")
    assert "nft flush ruleset" in runbook
    assert "sudo scripts/imao-firewall.sh remove --confirm" in runbook
    assert "local console" in runbook.lower()
