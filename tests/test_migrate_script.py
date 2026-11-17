"""Guard untuk skrip migrasi: daftar kolom di skrip harus sama dengan skema SQLite.

Tanpa test ini, perubahan skema di database.py bisa membuat skrip migrasi diam-diam
salah kolom dan baru ketahuan saat dijalankan di server (saat bot sudah berhenti).
"""

import importlib.util
import sqlite3
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "migrate_mysql_to_sqlite.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_mysql_to_sqlite", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_columns_match_sqlite_schema(tmp_path, monkeypatch):
    import tuyabot.storage.sqlite_store as database

    db_file = tmp_path / "schema.db"
    monkeypatch.setattr(database, "SQLITE_PATH", str(db_file))
    database.close_connection()
    assert database.init_db(migrate_json=False) is True

    script = _load_script()
    conn = sqlite3.connect(db_file)
    try:
        for table, columns in script.TABLES.items():
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            assert columns == actual, f"kolom {table} di skrip migrasi beda dengan skema"
    finally:
        conn.close()
        database.close_connection()


def test_script_targets_all_tables(tmp_path, monkeypatch):
    import tuyabot.storage.sqlite_store as database

    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "t.db"))
    database.close_connection()
    database.init_db(migrate_json=False)

    script = _load_script()
    conn = sqlite3.connect(database.SQLITE_PATH)
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    database.close_connection()

    assert set(script.TABLES) <= existing


def test_default_scope_is_users_only():
    """Default memindahkan data akses saja; log telemetri tidak dibawa."""
    script = _load_script()

    default_tables = script.select_tables(include_logs=False)
    assert set(default_tables) == {"bot_users", "bot_air_recipients"}

    all_tables = script.select_tables(include_logs=True)
    assert set(all_tables) == set(script.TABLES)
    assert "device_power_logs" in all_tables


def test_columns_for_user_tables_match_schema(tmp_path, monkeypatch):
    import tuyabot.storage.sqlite_store as database

    db_file = tmp_path / "scope.db"
    monkeypatch.setattr(database, "SQLITE_PATH", str(db_file))
    database.close_connection()
    database.init_db(migrate_json=False)

    script = _load_script()
    conn = sqlite3.connect(db_file)
    try:
        for table, columns in script.select_tables(include_logs=False).items():
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            assert columns == actual, f"kolom {table} tidak cocok dengan skema"
    finally:
        conn.close()
        database.close_connection()
