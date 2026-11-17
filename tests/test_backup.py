"""Test backup SQLite: salinan konsisten, isi sama, dan retensi berjalan."""

import os
import sqlite3
import time

import pytest

import tuyabot.storage.sqlite_store as database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "tuyabot.db"))
    database.close_connection()
    assert database.init_db(migrate_json=False) is True
    yield database
    database.close_connection()


def test_backup_creates_readable_copy_with_same_rows(db, tmp_path):
    db.log_power("air", 123.4, 220.0, 0.56, True, "periodic")
    db.set_user_role(42, 2, added_by=1, added_by_name="Superadmin")

    result = db.backup_to(str(tmp_path / "backup"), retention_days=14)

    copy_path = result["path"]
    assert os.path.exists(copy_path)
    assert result["size_bytes"] > 0

    copy = sqlite3.connect(copy_path)
    try:
        power_rows = copy.execute("SELECT COUNT(*) FROM device_power_logs").fetchone()[0]
        user_rows = copy.execute("SELECT COUNT(*) FROM bot_users").fetchone()[0]
        power_w = copy.execute("SELECT power_w FROM device_power_logs").fetchone()[0]
    finally:
        copy.close()

    assert power_rows == 1
    assert user_rows == 1
    assert round(power_w, 1) == 123.4


def test_backup_prunes_copies_older_than_retention(db, tmp_path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    old_copy = backup_dir / "tuyabot-2020-01-01_000000.db"
    old_copy.write_bytes(b"x")
    old_time = time.time() - 40 * 86400
    os.utime(old_copy, (old_time, old_time))

    fresh_copy = backup_dir / "tuyabot-latest.db"
    fresh_copy.write_bytes(b"x")

    result = db.backup_to(str(backup_dir), retention_days=14)

    assert result["removed"] == 1
    assert not old_copy.exists()
    assert fresh_copy.exists(), "salinan yang masih dalam masa retensi tidak boleh dihapus"
    assert os.path.exists(result["path"])


def test_backup_does_not_interrupt_writes(db, tmp_path):
    """Backup berjalan sambil database tetap bisa ditulis setelahnya."""
    db.log_power("air", 1.0, 220.0, 0.1, True, "periodic")
    db.backup_to(str(tmp_path / "backup"), retention_days=7)
    assert db.log_power("air", 2.0, 220.0, 0.2, True, "periodic") is True
    assert len(db.get_recent_power_logs(limit=10)) == 2


def test_stats_report_backup_information(db, tmp_path, monkeypatch):
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "tuyabot.db"))
    backup_dir = tmp_path / "backup"
    db.backup_to(str(backup_dir), retention_days=7)

    import tuyabot.config as config

    monkeypatch.setattr(config, "BACKUP_DIR", str(backup_dir))
    stats = db.get_db_stats()

    assert stats["backup_count"] == 1
    assert stats["last_backup"].startswith("tuyabot-")
