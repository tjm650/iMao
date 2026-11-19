#!/usr/bin/env python3
"""Safe SQLite backup, verification and restore utilities for wwiMao."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import get_settings


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _create_private_file(path: Path) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)


def _integrity_check(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")
    db = _connect(path)
    try:
        result = db.execute("PRAGMA integrity_check").fetchone()
    finally:
        db.close()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed for {path}: {result[0] if result else 'no result'}")


def backup(database: Path, destination: Path) -> Path:
    database = database.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if database == destination:
        raise ValueError("Backup destination must differ from the live database")
    if not database.is_file():
        raise FileNotFoundError(f"Database file not found: {database}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary backup already exists: {temporary}")
    _create_private_file(temporary)
    try:
        source = _connect(database)
        target = _connect(temporary)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        _integrity_check(temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


def restore(backup_file: Path, database: Path, confirm: bool) -> Path:
    backup_file = backup_file.expanduser().resolve()
    database = database.expanduser().resolve()
    if not confirm:
        raise ValueError("Restore is destructive; rerun with --confirm after stopping wwiMao")
    if backup_file == database:
        raise ValueError("Restore source and destination must differ")
    _integrity_check(backup_file)
    database.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            raise RuntimeError(
                f"SQLite sidecar remains: {sidecar}. Stop wwiMao cleanly and confirm no process is using the database."
            )
    if database.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safety_copy = database.with_name(f"{database.name}.pre-restore-{stamp}")
        backup(database, safety_copy)
        print(f"Pre-restore safety backup created: {safety_copy}")
    temporary = database.with_name(database.name + ".restore.tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary restore file already exists: {temporary}")
    _create_private_file(temporary)
    try:
        source = _connect(backup_file)
        target = _connect(temporary)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        _integrity_check(temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, database)
        return database
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=get_settings().database_file,
                        help="live SQLite database path (defaults to DATABASE_PATH in .env)")
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup", help="create a consistent SQLite backup")
    backup_parser.add_argument("--output", type=Path, help="backup path; defaults to ./backups with UTC timestamp")
    verify_parser = commands.add_parser("verify", help="run SQLite integrity_check on a backup")
    verify_parser.add_argument("backup_file", type=Path)
    restore_parser = commands.add_parser("restore", help="restore a verified backup (stop wwiMao first)")
    restore_parser.add_argument("backup_file", type=Path)
    restore_parser.add_argument("--confirm", action="store_true", help="confirm replacement of the live database")
    args = parser.parse_args()

    try:
        if args.command == "backup":
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = args.output or Path("backups") / f"wwimao-{stamp}.sqlite3"
            result = backup(args.database, output)
            print(f"Backup created and verified: {result}")
        elif args.command == "verify":
            _integrity_check(args.backup_file.expanduser().resolve())
            print(f"Backup integrity: OK ({args.backup_file})")
        else:
            result = restore(args.backup_file, args.database, args.confirm)
            print(f"Database restored from verified backup: {result}")
        return 0
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"wwiMao database operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
