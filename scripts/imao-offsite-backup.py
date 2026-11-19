#!/usr/bin/env python3
"""Create an encrypted SQLite backup and upload it to a configured rclone remote.

Required environment:
  BACKUP_AGE_RECIPIENT       age public recipient (never a private key)
  BACKUP_RCLONE_DESTINATION rclone destination directory, e.g. cryptremote:wimao
Optional:
  DATABASE_PATH             live SQLite path (default: ./database/wimao.sqlite3)
  BACKUP_PYTHON             Python executable used for the local backup (default: current interpreter)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_TOOL = ROOT / "scripts" / "wimao-db.py"


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, cwd=ROOT)


def main() -> int:
    try:
        recipient = required("BACKUP_AGE_RECIPIENT")
        destination = required("BACKUP_RCLONE_DESTINATION").rstrip("/")
        if ":" not in destination or destination.startswith(":"):
            raise RuntimeError("BACKUP_RCLONE_DESTINATION must be an explicit configured rclone remote path")
        age = shutil.which("age")
        rclone = shutil.which("rclone")
        if not age or not rclone:
            raise RuntimeError("Both age and rclone must be installed and available on PATH")

        database = Path(os.environ.get("DATABASE_PATH", "./database/wimao.sqlite3")).expanduser()
        python = os.environ.get("BACKUP_PYTHON", sys.executable)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"wimao-{stamp}.sqlite3.age"
        remote_file = f"{destination}/{filename}"

        with tempfile.TemporaryDirectory(prefix="wimao-backup-") as work:
            os.chmod(work, 0o700)
            workdir = Path(work)
            plaintext = workdir / f"wimao-{stamp}.sqlite3"
            encrypted = workdir / filename

            run([python, str(DB_TOOL), "--database", str(database), "backup", "--output", str(plaintext)])
            run([age, "--recipient", recipient, "--output", str(encrypted), str(plaintext)])
            plaintext.unlink()
            run([rclone, "copyto", "--immutable", str(encrypted), remote_file])
            run([rclone, "check", "--one-way", str(encrypted), remote_file])

        print(f"Encrypted backup uploaded and checked: {remote_file}")
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"wiMao off-site backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
