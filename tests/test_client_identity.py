import ipaddress


def test_hotspot_subnet_membership_is_checked():
    network = ipaddress.ip_network("192.0.2.0/24")
    assert ipaddress.ip_address("192.0.2.25") in network
    assert ipaddress.ip_address("198.51.100.25") not in network
