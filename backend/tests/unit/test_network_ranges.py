import ipaddress

import pytest

from app.security.network import is_forbidden_address


@pytest.mark.parametrize(
    "address,expected_reason_substring",
    [
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("10.1.2.3", "private"),
        ("172.16.0.5", "private"),
        ("192.168.1.1", "private"),
        ("169.254.1.1", "link-local"),
        ("169.254.169.254", "metadata"),
        ("fd00:ec2::254", "metadata"),
        ("224.0.0.1", "multicast"),
        ("0.0.0.0", "unspecified"),
    ],
)
def test_forbidden_addresses_are_rejected(address: str, expected_reason_substring: str) -> None:
    reason = is_forbidden_address(ipaddress.ip_address(address))
    assert reason is not None
    assert expected_reason_substring in reason


@pytest.mark.parametrize("address", ["8.8.8.8", "93.184.216.34", "1.1.1.1"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_forbidden_address(ipaddress.ip_address(address)) is None
