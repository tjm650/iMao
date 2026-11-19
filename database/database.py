import sqlite3
from pathlib import Path

from backend.app.config import get_settings


def connect(database_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(database_path or get_settings().database_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path | None = None) -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    schema = schema_path.read_text(encoding="utf-8")
    with connect(database_path) as connection:
        connection.executescript(schema)
