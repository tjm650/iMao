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
        # Additive migrations preserve data created by earlier wiMao stages.
        session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
        session_migrations = {
            "session_token_hash": "TEXT",
            "expires_at": "TEXT",
            "last_counter_up": "INTEGER",
            "last_counter_down": "INTEGER",
            "revocation_pending": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in session_migrations.items():
            if name not in session_columns:
                connection.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        voucher_columns = {row["name"] for row in connection.execute("PRAGMA table_info(vouchers)")}
        voucher_migrations = {"revoked_at": "TEXT", "batch_id": "INTEGER REFERENCES voucher_batches(id)"}
        for name, definition in voucher_migrations.items():
            if name not in voucher_columns:
                connection.execute(f"ALTER TABLE vouchers ADD COLUMN {name} {definition}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token_hash)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(status, expires_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_batch ON vouchers(batch_id)")
        admin_columns = {row["name"] for row in connection.execute("PRAGMA table_info(admin_users)")}
        if "role" not in admin_columns:
            connection.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
