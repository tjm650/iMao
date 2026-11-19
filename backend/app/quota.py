from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaStatus:
    quota_bytes: int
    used_bytes: int
    remaining_bytes: int
    exhausted: bool
    percent_used: float


def calculate_quota(quota_bytes: int, used_bytes: int) -> QuotaStatus:
    if quota_bytes < 0 or used_bytes < 0:
        raise ValueError("Quota and usage cannot be negative")

    remaining = max(quota_bytes - used_bytes, 0)
    percent = 100.0 if quota_bytes == 0 else min(used_bytes / quota_bytes * 100, 100.0)

    return QuotaStatus(
        quota_bytes=quota_bytes,
        used_bytes=used_bytes,
        remaining_bytes=remaining,
        exhausted=used_bytes >= quota_bytes,
        percent_used=round(percent, 2),
    )


def megabytes_to_bytes(megabytes: int) -> int:
    if megabytes <= 0:
        raise ValueError("Quota must be greater than zero")
    return megabytes * 1024 * 1024
