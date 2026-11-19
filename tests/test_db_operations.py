import importlib.util
import sqlite3
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "imao-db.py"
SPEC = importlib.util.spec_from_file_location("imao_db", MODULE_PATH)
imao_db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(imao_db)


def _database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS sample (value TEXT)")
        db.execute("INSERT INTO sample(value) VALUES (?)", (value,))


def test_backup_is_consistent_and_private(tmp_path):
    source = tmp_path / "live.sqlite3"
    destination = tmp_path / "backups" / "snapshot.sqlite3"
    _database(source, "saved")
    result = imao_db.backup(source, destination)
    assert result == destination.resolve()
    assert destination.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(destination) as db:
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "saved"
    with pytest.raises(FileExistsError):
        imao_db.backup(source, destination)


def test_restore_requires_confirmation_and_restores_snapshot(tmp_path):
    source = tmp_path / "live.sqlite3"
    snapshot = tmp_path / "snapshot.sqlite3"
    _database(source, "original")
    imao_db.backup(source, snapshot)
    _database(source, "later")
    with pytest.raises(ValueError, match="--confirm"):
        imao_db.restore(snapshot, source, False)
    imao_db.restore(snapshot, source, True)
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT value FROM sample ORDER BY rowid DESC LIMIT 1").fetchone()[0] == "original"


def test_verify_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        imao_db._integrity_check(tmp_path / "missing.sqlite3")


def test_backup_refuses_same_source_and_destination(tmp_path):
    source = tmp_path / "live.sqlite3"
    _database(source, "value")
    with pytest.raises(ValueError, match="differ"):
        imao_db.backup(source, source)
