from database.database import connect, initialize_database


def test_database_initialization_adds_session_token_column(tmp_path):
    database_path = tmp_path / "imao.sqlite3"
    initialize_database(database_path)
    with connect(database_path) as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
        assert "session_token_hash" in columns
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "login_attempts" in tables
