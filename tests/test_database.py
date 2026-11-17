"""Test database SQLite terhadap file sungguhan (bukan mock).

Versi sebelumnya mem-mock `get_db_connection`, sehingga SQL-nya tidak pernah
dieksekusi dan kesalahan seperti `ON DUPLICATE KEY` atau `NOW() - INTERVAL`
tidak akan pernah ketahuan. Sekarang setiap test memakai file SQLite sementara.
"""

import logging
import sqlite3

import pytest

import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "tuyabot.db"))
    database.close_connection()
    assert database.init_db(migrate_json=False) is True
    yield database
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, database.SQLiteDatabaseLogHandler)]:
        root.removeHandler(handler)
    database.close_connection()


def test_init_creates_all_tables(db):
    conn = sqlite3.connect(database.SQLITE_PATH)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()

    assert {
        "bot_users",
        "bot_air_recipients",
        "device_activity_logs",
        "device_power_logs",
        "app_error_logs",
    } <= tables


def test_wal_mode_enabled(db):
    conn = sqlite3.connect(database.SQLITE_PATH)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"


def test_user_role_roundtrip_and_update(db):
    assert db.get_user_role(12345) is None

    assert db.set_user_role(12345, 1, added_by=999, added_by_name="Superadmin") is True
    assert db.get_user_role(12345) == 1

    # Update role tanpa menyebut added_by: kolom itu harus dipertahankan (COALESCE).
    assert db.set_user_role(12345, 2) is True
    assert db.get_user_role(12345) == 2

    details = db.get_all_runtime_users_details()
    assert len(details) == 1
    assert details[0]["added_by"] == 999
    assert details[0]["added_by_name"] == "Superadmin"


def test_runtime_users_and_remove(db):
    db.set_user_role(1, 1)
    db.set_user_role(2, 3)

    assert db.get_all_runtime_users() == {1: 1, 2: 3}
    assert db.remove_user(1) is True
    assert db.remove_user(1) is False
    assert db.get_all_runtime_users() == {2: 3}


def test_air_recipients_idempotent(db):
    assert db.add_air_recipient(111) is True
    assert db.add_air_recipient(111) is True  # INSERT OR IGNORE, tidak error
    db.add_air_recipient(222)

    assert db.get_air_recipients() == {111, 222}
    assert db.remove_air_recipient(111) is True
    assert db.remove_air_recipient(111) is False
    assert db.get_air_recipients() == {222}


def test_logs_and_recent_readers(db):
    db.log_activity(10, "Admin", "lampu", "turn_on", "success", "Lampu ON")
    db.log_activity(10, "Admin", "lampu", "turn_off", "success", "Lampu OFF")
    db.log_power("air", 120.5, 220.0, 0.55, True, "periodic")
    db.log_power("air", 250.0, 219.8, 1.13, True, "action_switch")

    activities = db.get_recent_activities(limit=10)
    assert [a["action"] for a in activities] == ["turn_off", "turn_on"]

    power = db.get_recent_power_logs(limit=10)
    assert [p["power_w"] for p in power] == [250.0, 120.5]
    assert power[0]["switch_state"] is True

    only_air = db.get_recent_power_logs(device_name="air", limit=1)
    assert len(only_air) == 1


def test_cleanup_old_logs_deletes_only_old_rows(db):
    db.log_power("air", 100.0, 220.0, 0.5, True, "periodic")
    db.log_activity(10, "Admin", "air", "turn_on", "success")

    # Sisipkan baris berumur 90 hari langsung ke tabel.
    conn = sqlite3.connect(database.SQLITE_PATH)
    old = "datetime('now','localtime','-90 days')"
    conn.execute(
        f"INSERT INTO device_power_logs (device_name, power_w, voltage_v, current_a, switch_state, source, created_at) "
        f"VALUES ('air', 1, 1, 1, 1, 'periodic', {old})"
    )
    conn.execute(
        f"INSERT INTO device_activity_logs (user_id, user_role, device_name, action, status, created_at) "
        f"VALUES (1, 'Admin', 'air', 'turn_on', 'success', {old})"
    )
    conn.commit()
    conn.close()

    result = db.cleanup_old_logs(retention_days=30)

    assert result == {"power_logs_deleted": 1, "activity_logs_deleted": 1, "error_logs_deleted": 0}
    assert len(db.get_recent_power_logs(limit=10)) == 1


def test_db_stats_report_counts_and_size(db):
    db.set_user_role(1, 1)
    db.add_air_recipient(9)
    db.log_power("air", 10.0, 220.0, 0.05, True, "periodic")

    stats = db.get_db_stats()

    assert stats["connected"] is True
    assert stats["engine"] == "sqlite"
    assert stats["total_power_logs"] == 1
    assert stats["total_runtime_users"] == 1
    assert stats["total_air_recipients"] == 1
    assert stats["size_bytes"] > 0


def test_app_error_logging_and_handler(db):
    assert db.log_app_error(
        level="ERROR",
        logger_name="test_logger",
        message="Test error message",
        exception_trace="Traceback...",
        file_name="test.py",
        line_number=42,
    ) is True

    errors = db.get_recent_app_errors(limit=5)
    assert len(errors) == 1
    assert errors[0]["message"] == "Test error message"
    assert errors[0]["line_number"] == 42

    handler = db.SQLiteDatabaseLogHandler(level=logging.ERROR)
    record = logging.LogRecord(
        name="app_module",
        level=logging.ERROR,
        pathname="app.py",
        lineno=10,
        msg="App crashed!",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    errors = db.get_recent_app_errors(limit=5)
    assert any(e["message"] == "App crashed!" for e in errors)


def test_handler_ignores_its_own_database_errors(db):
    handler = db.SQLiteDatabaseLogHandler(level=logging.ERROR)
    record = logging.LogRecord(
        name="database",
        level=logging.ERROR,
        pathname="database.py",
        lineno=1,
        msg="[DATABASE ERROR] sesuatu",
        args=(),
        exc_info=None,
    )
    handler.emit(record)

    assert db.get_recent_app_errors(limit=5) == []


def test_ping_true_for_working_db(db):
    assert db.ping() is True


def test_error_path_returns_none_instead_of_raising(tmp_path, monkeypatch):
    blocker = tmp_path / "bukan-direktori"
    blocker.write_text("x")
    monkeypatch.setattr(database, "SQLITE_PATH", str(blocker / "sub" / "db.sqlite"))
    database.close_connection()

    assert database.get_user_role(1) is None
    assert database.set_user_role(1, 1) is False
    assert database.ping() is False
    database.close_connection()
