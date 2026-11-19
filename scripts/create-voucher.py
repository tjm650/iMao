#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.vouchers import create_voucher


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a single-use iMao access voucher")
    parser.add_argument("--quota-mb", type=int, default=None, help="Voucher allowance in MB (default: configured default)")
    parser.add_argument("--expires-at", default=None, help="Optional ISO-8601 expiry with timezone, e.g. 2027-01-01T00:00:00+00:00")
    args = parser.parse_args()
    print(create_voucher(args.quota_mb, args.expires_at))


if __name__ == "__main__":
    main()
