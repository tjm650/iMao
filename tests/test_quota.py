import pytest

from backend.app.quota import calculate_quota, megabytes_to_bytes


def test_remaining_quota():
    status = calculate_quota(1_000, 250)
    assert status.remaining_bytes == 750
    assert status.exhausted is False
    assert status.percent_used == 25.0


def test_quota_exhausted():
    status = calculate_quota(1_000, 1_000)
    assert status.remaining_bytes == 0
    assert status.exhausted is True


def test_usage_never_has_negative_remaining():
    status = calculate_quota(1_000, 1_500)
    assert status.remaining_bytes == 0
    assert status.percent_used == 100.0


def test_reject_negative_values():
    with pytest.raises(ValueError):
        calculate_quota(-1, 0)


def test_mb_conversion():
    assert megabytes_to_bytes(500) == 500 * 1024 * 1024


def test_reject_zero_quota():
    with pytest.raises(ValueError):
        megabytes_to_bytes(0)
