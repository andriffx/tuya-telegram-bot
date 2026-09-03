"""
Modul database MySQL eksternal untuk bot Telegram Tuya.
Menggunakan connection pool resmi dari mysql-connector-python dan Pure Direct Query.
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional, Set

import mysql.connector
from mysql.connector import pooling
from mysql.connector.errors import Error as MySQLError

from config import MYSQL_CONFIG

logger = logging.getLogger(__name__)

USERS_FILE = Path("users_db.json")

_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = threading.Lock()


def get_pool() -> Optional[pooling.MySQLConnectionPool]:
    """Inisialisasi connection pool secara lazy dan thread-safe."""
    global _pool
    if _pool is not None:
        return _pool

    with _pool_lock:
        if _pool is not None:
            return _pool

        try:
            pool_config = {
                "pool_name": "tuya_mysql_pool",
                "pool_size": MYSQL_CONFIG.get("pool_size", 5),
                "pool_reset_session": True,
                "host": MYSQL_CONFIG.get("host", "127.0.0.1"),
                "port": MYSQL_CONFIG.get("port", 3306),
                "user": MYSQL_CONFIG.get("user", "root"),
                "password": MYSQL_CONFIG.get("password", ""),
                "database": MYSQL_CONFIG.get("database", "tuyabot"),
                "connection_timeout": MYSQL_CONFIG.get("connect_timeout", 5),
            }
            _pool = pooling.MySQLConnectionPool(**pool_config)
            logger.info(
                "MySQL connection pool '%s' berhasil diinisialisasi ke %s:%s/%s (size: %d)",
                _pool.pool_name,
                pool_config["host"],
                pool_config["port"],
                pool_config["database"],
                pool_config["pool_size"],
            )
            return _pool
        except Exception as e:
            logger.critical(
                "[DATABASE CRITICAL] Gagal membuat MySQL connection pool (%s:%s): %s",
                MYSQL_CONFIG.get("host"),
                MYSQL_CONFIG.get("port"),
                e,
            )
            return None


@contextmanager
def get_db_connection():
    """
    Context manager untuk meminjam koneksi dari pool, memastikan auto-reconnect,
    commit otomatis jika berhasil, rollback jika gagal, dan melepas koneksi kembali ke pool.
    """
    pool = get_pool()
    if pool is None:
        raise ConnectionError(
            f"[DATABASE ERROR] Connection pool tidak tersedia untuk {MYSQL_CONFIG.get('host')}:{MYSQL_CONFIG.get('port')}"
        )

    conn = None
    cursor = None
    try:
        conn = pool.get_connection()
        # Periksa keaktifan koneksi dan lakukan reconnect jika perlu
        try:
            conn.ping(reconnect=True, attempts=3, delay=1)
        except Exception as ping_err:
            logger.warning("[DATABASE WARNING] Gagal ping MySQL, mencoba lanjut: %s", ping_err)

        cursor = conn.cursor()
        yield conn, cursor
        conn.commit()
    except Exception as err:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error("[DATABASE ERROR] Eksekusi transaksi MySQL gagal: %s", err)
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def init_db(migrate_json: bool = True) -> bool:
    """
    Buat tabel-tabel yang dibutuhkan jika belum ada dan lakukan migrasi data lama jika diperlukan.
    """
    queries = [
        """
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id BIGINT PRIMARY KEY,
            role TINYINT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS bot_air_recipients (
            user_id BIGINT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS device_activity_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            user_role VARCHAR(20),
            device_name VARCHAR(50) NOT NULL,
            action VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user_id (user_id),
            INDEX idx_created_at (created_at)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS device_power_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            device_name VARCHAR(50) NOT NULL DEFAULT 'air',
            power_w FLOAT NOT NULL DEFAULT 0,
            voltage_v FLOAT NOT NULL DEFAULT 0,
            current_a FLOAT NOT NULL DEFAULT 0,
            switch_state BOOLEAN,
            source VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created_at (created_at)
        );
        """,
    ]

    try:
        with get_db_connection() as (conn, cursor):
            for q in queries:
                cursor.execute(q)
        logger.info("Inisialisasi tabel database MySQL berhasil.")
    except Exception as e:
        logger.critical("[DATABASE CRITICAL] Gagal membuat tabel di MySQL: %s", e)
        return False

    if migrate_json:
        try:
            migrate_from_json_if_needed()
        except Exception as e:
            logger.error("[DATABASE ERROR] Gagal migrasi data dari JSON: %s", e)

    return True


def migrate_from_json_if_needed() -> None:
    """
    Migrasi satu kali dari users_db.json ke database MySQL jika file ada dan tabel masih kosong.
    Setelah sukses, file di-backup menjadi users_db.json.bak.
    """
    if not USERS_FILE.exists() or USERS_FILE.stat().st_size == 0:
        return

    existing_users = get_all_runtime_users()
    if existing_users:
        logger.info("Tabel bot_users sudah berisi data. Melewati migrasi users_db.json.")
        return

    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        users = data.get("users", {})
        recipients = data.get("air_notify_recipients", [])

        migrated_users = 0
        for uid_str, role_int in users.items():
            if set_user_role(int(uid_str), int(role_int)):
                migrated_users += 1

        migrated_recipients = 0
        for uid in recipients:
            if add_air_recipient(int(uid)):
                migrated_recipients += 1

        logger.info(
            "Berhasil migrasi %d user dan %d penerima notif dari %s ke MySQL",
            migrated_users,
            migrated_recipients,
            USERS_FILE,
        )

        bak_file = USERS_FILE.with_suffix(".json.bak")
        USERS_FILE.rename(bak_file)
        logger.info("File lama diubah menjadi backup: %s", bak_file)
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal saat memproses migrasi JSON: %s", e)


# ── Query Langsung: Manajemen User ──

def get_user_role(user_id: int) -> Optional[int]:
    """Ambil role user runtime dari MySQL. Return None jika user tidak ditemukan atau DB error."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute("SELECT role FROM bot_users WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row:
                return int(row[0])
            return None
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil role untuk user_id=%s dari MySQL: %s", user_id, e)
        return None


def set_user_role(user_id: int, role: int) -> bool:
    """Simpan atau perbarui role user di MySQL."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO bot_users (user_id, role)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE role = VALUES(role), updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, role),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menyimpan role user_id=%s role=%s ke MySQL: %s", user_id, role, e)
        return False


def remove_user(user_id: int) -> bool:
    """Hapus user runtime dari MySQL."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute("DELETE FROM bot_users WHERE user_id = %s", (user_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menghapus user_id=%s dari MySQL: %s", user_id, e)
        return False


def get_all_runtime_users() -> Dict[int, int]:
    """Ambil semua user runtime dari MySQL."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute("SELECT user_id, role FROM bot_users")
            rows = cursor.fetchall()
            return {int(row[0]): int(row[1]) for row in rows}
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil daftar user runtime dari MySQL: %s", e)
        return {}


# ── Query Langsung: Penerima Notif Air ──

def get_air_recipients() -> Set[int]:
    """Ambil semua ID admin penerima notif air dari MySQL."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute("SELECT user_id FROM bot_air_recipients")
            rows = cursor.fetchall()
            return {int(row[0]) for row in rows}
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil daftar bot_air_recipients dari MySQL: %s", e)
        return set()


def add_air_recipient(user_id: int) -> bool:
    """Tambah admin ke daftar notifikasi kontrol air di MySQL."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute(
                "INSERT IGNORE INTO bot_air_recipients (user_id) VALUES (%s)",
                (user_id,),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menambahkan recipient user_id=%s ke MySQL: %s", user_id, e)
        return False


def remove_air_recipient(user_id: int) -> bool:
    """Hapus admin dari daftar notifikasi kontrol air di MySQL."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute("DELETE FROM bot_air_recipients WHERE user_id = %s", (user_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menghapus recipient user_id=%s dari MySQL: %s", user_id, e)
        return False


# ── Logging: Device Activity & Power ──

def log_activity(
    user_id: int,
    user_role: str,
    device_name: str,
    action: str,
    status: str,
    message: str = "",
) -> bool:
    """Catat log aksi perangkat ke tabel device_activity_logs."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO device_activity_logs (user_id, user_role, device_name, action, status, message)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, user_role, device_name, action, status, message),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mencatat activity log ke MySQL: %s", e)
        return False


def log_power(
    device_name: str,
    power_w: float,
    voltage_v: float,
    current_a: float,
    switch_state: Optional[bool],
    source: str,
) -> bool:
    """Catat snapshot konsumsi daya ke tabel device_power_logs."""
    try:
        with get_db_connection() as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO device_power_logs (device_name, power_w, voltage_v, current_a, switch_state, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (device_name, power_w, voltage_v, current_a, switch_state, source),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mencatat power log ke MySQL: %s", e)
        return False
