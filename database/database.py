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
        # Safe additive migration for databases created by the first foundation stage.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
        if "session_token_hash" not in columns:
            connection.execute("ALTER TABLE sessions ADD COLUMN session_token_hash TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token_hash)"
        )
