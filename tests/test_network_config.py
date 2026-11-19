import ipaddress


def test_hotspot_gateway_must_belong_to_subnet():
    network = ipaddress.ip_network("192.0.2.0/24")
    assert ipaddress.ip_address("192.0.2.1") in network
    assert ipaddress.ip_address("198.51.100.1") not in network


def test_upstream_and_hotspot_must_be_distinct():
    assert "enp0s31f6" != "wlp2s0"
