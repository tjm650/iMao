import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wimao-network.py"
SPEC = importlib.util.spec_from_file_location("wimao_network", SCRIPT)
network = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(network)


def _environment(url):
    return {
        "UPSTREAM_INTERFACE": "eth0", "HOTSPOT_INTERFACE": "wlan0",
        "HOTSPOT_CIDR": "10.42.0.0/24", "HOTSPOT_GATEWAY": "10.42.0.1",
        "HOTSPOT_SSID": "wiMao", "HOTSPOT_PASSPHRASE": "12345678",
        "WIFI_COUNTRY_CODE": "ZW", "PORTAL_PORT": "8000", "COOKIE_SECURE": "true",
        "PORTAL_PUBLIC_URL": url,
    }


def test_public_portal_url_generates_https_dns_and_dhcp_config(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "Caddyfile.example").write_text(
        "{{PORTAL_HOSTNAME}} { reverse_proxy 127.0.0.1:{{PORTAL_PORT}} }"
    )
    for name in ("hostapd.conf.example", "dnsmasq.conf.example", "nftables.conf.example"):
        (tmp_path / "config" / name).write_text(
            "{{PORTAL_DHCP_OPTION}}\n{{PORTAL_DNS_OVERRIDE}}\n{{PORTAL_PORT}}"
        )
    monkeypatch.setattr(network, "ROOT", tmp_path)
    monkeypatch.setattr(network, "load_env", lambda: _environment("https://portal.example.com"))
    network.render()
    dns = (tmp_path / "runtime-config" / "dnsmasq.conf").read_text()
    caddy = (tmp_path / "runtime-config" / "Caddyfile").read_text()
    assert 'dhcp-option=114,"https://portal.example.com/api/captive-portal"' in dns
    assert "address=/portal.example.com/10.42.0.1" in dns
    assert "portal.example.com" in caddy
    assert "reverse_proxy 127.0.0.1:8000" in caddy


@pytest.mark.parametrize("url", [
    "http://portal.example.com", "https://192.0.2.10",
    "https://portal.example.com/path", "https://portal.example.com:8443",
])
def test_renderer_rejects_invalid_portal_origins(tmp_path, monkeypatch, url):
    (tmp_path / "config").mkdir()
    for name in ("hostapd.conf.example", "dnsmasq.conf.example", "nftables.conf.example"):
        (tmp_path / "config" / name).write_text("{{PORTAL_PORT}}")
    monkeypatch.setattr(network, "ROOT", tmp_path)
    monkeypatch.setattr(network, "load_env", lambda: _environment(url))
    with pytest.raises(SystemExit):
        network.render()


def test_renderer_rejects_reserved_portal_listener_ports(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    for name in ("hostapd.conf.example", "dnsmasq.conf.example", "nftables.conf.example"):
        (tmp_path / "config" / name).write_text("{{PORTAL_PORT}}")
    env = _environment("")
    env["PORTAL_PORT"] = "80"
    monkeypatch.setattr(network, "ROOT", tmp_path)
    monkeypatch.setattr(network, "load_env", lambda: env)
    with pytest.raises(SystemExit):
        network.render()
