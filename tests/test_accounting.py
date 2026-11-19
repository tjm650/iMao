from backend.app.accounting import counter_delta
from backend.app.quota import calculate_quota


def test_quota_reports_exhaustion_at_exact_limit():
    status = calculate_quota(500, 500)
    assert status.exhausted
    assert status.remaining_bytes == 0


def test_quota_never_reports_negative_remaining():
    status = calculate_quota(500, 800)
    assert status.remaining_bytes == 0
    assert status.percent_used == 100.0


def test_counter_delta_accumulates_normal_counter_growth():
    assert counter_delta(100, 145) == 45


def test_counter_delta_handles_counter_reset_without_negative_usage():
    assert counter_delta(900, 12) == 12


def test_counter_delta_initializes_new_counter():
    assert counter_delta(None, 42) == 42
