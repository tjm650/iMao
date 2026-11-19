import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = _load("imao_offsite_backup", "scripts/imao-offsite-backup.py")
monitor = _load("imao_monitor", "scripts/imao-monitor.py")


def test_offsite_backup_requires_explicit_remote_and_age_recipient(monkeypatch):
    monkeypatch.delenv("BACKUP_AGE_RECIPIENT", raising=False)
    monkeypatch.delenv("BACKUP_RCLONE_DESTINATION", raising=False)
    assert backup.main() == 1


def test_offsite_backup_encrypts_before_upload_and_checks_remote(monkeypatch):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENT", "age1publicrecipient")
    monkeypatch.setenv("BACKUP_RCLONE_DESTINATION", "cryptremote:imao")
    monkeypatch.setattr(backup.shutil, "which", lambda name: f"/usr/bin/{name}")
    commands = []

    def fake_run(command):
        commands.append(command)
        if "imao-db.py" in command[1]:
            Path(command[command.index("--output") + 1]).write_bytes(b"sqlite-backup")
        elif command[0] == "/usr/bin/age":
            Path(command[command.index("--output") + 1]).write_bytes(b"encrypted")
    monkeypatch.setattr(backup, "run", fake_run)

    assert backup.main() == 0
    assert len(commands) == 4
    assert commands[1][0] == "/usr/bin/age"
    assert commands[2][0] == "/usr/bin/rclone"
    assert commands[2][1] == "copyto"
    assert "--immutable" in commands[2]
    assert commands[2][-1].startswith("cryptremote:imao/imao-")
    assert commands[2][-1].endswith(".sqlite3.age")
    assert commands[3][0] == "/usr/bin/rclone"
    assert commands[3][1] == "check"
    assert "--one-way" in commands[3]


def test_offsite_backup_rejects_non_remote_destination(monkeypatch):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENT", "age1publicrecipient")
    monkeypatch.setenv("BACKUP_RCLONE_DESTINATION", "/tmp/backup")
    monkeypatch.setattr(backup.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert backup.main() == 1


def test_monitor_accepts_expected_ready_payload(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b'{"status":"ready","service":"imao"}'

    monkeypatch.setattr(monitor.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    assert monitor.check("http://127.0.0.1:8000/ready", 2) == (True, "OK")


def test_monitor_rejects_unhealthy_payload(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b'{"status":"not_ready","service":"imao"}'

    monkeypatch.setattr(monitor.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    assert monitor.check("http://127.0.0.1:8000/ready", 2) == (False, "Unexpected health response")
