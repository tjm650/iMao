from backend.app.quota import calculate_quota


def test_quota_reports_exhaustion_at_exact_limit():
    status = calculate_quota(500, 500)
    assert status.exhausted
    assert status.remaining_bytes == 0


def test_quota_never_reports_negative_remaining():
    status = calculate_quota(500, 800)
    assert status.remaining_bytes == 0
    assert status.percent_used == 100.0
