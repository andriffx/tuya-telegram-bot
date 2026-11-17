"""
Modul database SQLite (embedded) untuk bot Telegram Tuya.

Kenapa SQLite, bukan MySQL: satu proses, satu penulis, ±288 baris/hari. SQLite
menghapus satu service, satu kredensial, dan satu titik gagal tanpa kehilangan apa pun.

Bentuk API sengaja dipertahankan sama seperti versi MySQL sebelumnya
(`get_db_connection`, `log_activity`, `get_user_role`, dst.) supaya bot, REST API,
dan scheduler tidak perlu tahu penyimpanannya apa.
"""

import json
import logging
import sqlite3
import sys
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path

from ..config import SQLITE_BUSY_TIMEOUT_MS, SQLITE_PATH

logger = logging.getLogger(__name__)

USERS_FILE = Path("users_db.json")

# Satu koneksi per thread. `asyncio.to_thread` memakai beberapa thread, dan SQLite
# tidak boleh berbagi satu koneksi antar thread. Koneksi dibuka lazy dan dipakai ulang.
_local = threading.local()

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS bot_users (
        user_id INTEGER PRIMARY KEY,
        role INTEGER NOT NULL DEFAULT 0 CHECK (role BETWEEN 0 AND 3),
        added_by INTEGER,
        added_by_name TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bot_air_recipients (
        user_id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        user_role TEXT,
        device_name TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_power_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT NOT NULL DEFAULT 'air',
        power_w REAL NOT NULL DEFAULT 0,
        voltage_v REAL NOT NULL DEFAULT 0,
        current_a REAL NOT NULL DEFAULT 0,
        switch_state INTEGER,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_error_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level TEXT NOT NULL,
        logger_name TEXT NOT NULL,
        message TEXT NOT NULL,
        exception_trace TEXT,
        file_name TEXT,
        line_number INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_activity_user ON device_activity_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_activity_created ON device_activity_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_power_created ON device_power_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_power_device ON device_power_logs(device_name)",
    "CREATE INDEX IF NOT EXISTS idx_error_created ON app_error_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_error_level ON app_error_logs(level)",
]


def _is_memory_db() -> bool:
    return SQLITE_PATH in (":memory:", "")


def _connect() -> sqlite3.Connection:
    """Buka (atau ambil ulang) koneksi milik thread ini, lalu set pragma wajib."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    if not _is_memory_db():
        Path(SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(SQLITE_PATH, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    # WAL: pembaca tidak memblokir penulis. synchronous=NORMAL aman dengan WAL.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    _local.conn = conn
    return conn


@contextmanager
def get_db_connection():
    """Pinjam koneksi thread ini; commit bila sukses, rollback bila gagal."""
    conn = _connect()
    cursor = conn.cursor()
    try:
        yield conn, cursor
        conn.commit()
    except Exception as err:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("[DATABASE ERROR] Eksekusi transaksi SQLite gagal: %s", err)
        raise
    finally:
        cursor.close()


def close_connection() -> None:
    """Tutup koneksi milik thread ini (dipakai test dan shutdown)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None


def ping() -> bool:
    """Cek konektivitas database tanpa memuat data apa pun (untuk readiness check)."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception as e:
        logger.warning("[DATABASE WARNING] Ping database gagal: %s", e)
        return False


def init_db(migrate_json: bool = True) -> bool:
    """Buat tabel & index bila belum ada, pasang log handler, migrasi JSON lama."""
    try:
        with get_db_connection() as (_conn, cursor):
            for statement in SCHEMA:
                cursor.execute(statement)
        logger.info("Inisialisasi tabel SQLite berhasil (%s).", SQLITE_PATH)
    except Exception as e:
        logger.critical("[DATABASE CRITICAL] Gagal membuat tabel SQLite: %s", e)
        return False

    try:
        setup_db_logging()
    except Exception as err_log:
        logger.warning("Gagal memasang SQLiteDatabaseLogHandler: %s", err_log)

    if migrate_json:
        try:
            migrate_from_json_if_needed()
        except Exception as e:
            logger.error("[DATABASE ERROR] Gagal migrasi data dari JSON: %s", e)

    try:
        cleanup_old_logs()
    except Exception as e:
        logger.warning("Housekeeping awal saat startup gagal: %s", e)

    return True


def migrate_from_json_if_needed() -> None:
    """Migrasi satu kali dari users_db.json bila file ada dan tabel masih kosong."""
    if not USERS_FILE.exists() or USERS_FILE.stat().st_size == 0:
        return

    if get_all_runtime_users():
        logger.info("Tabel bot_users sudah berisi data. Melewati migrasi users_db.json.")
        return

    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        users = data.get("users", {})
        recipients = data.get("air_notify_recipients", [])

        migrated_users = sum(1 for uid, role in users.items() if set_user_role(int(uid), int(role)))
        migrated_recipients = sum(1 for uid in recipients if add_air_recipient(int(uid)))

        logger.info(
            "Berhasil migrasi %d user dan %d penerima notif dari %s ke SQLite",
            migrated_users,
            migrated_recipients,
            USERS_FILE,
        )

        bak_file = USERS_FILE.with_suffix(".json.bak")
        USERS_FILE.rename(bak_file)
        logger.info("File lama diubah menjadi backup: %s", bak_file)
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal saat memproses migrasi JSON: %s", e)


# ── Manajemen User ──


def get_user_role(user_id: int) -> int | None:
    """Ambil role user runtime. None bila tidak ada atau database error."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("SELECT role FROM bot_users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return int(row[0]) if row else None
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil role untuk user_id=%s: %s", user_id, e)
        return None


def set_user_role(
    user_id: int,
    role: int,
    added_by: int | None = None,
    added_by_name: str | None = None,
) -> bool:
    """Simpan/perbarui role user beserta siapa yang menambahkan."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO bot_users (user_id, role, added_by, added_by_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role = excluded.role,
                    added_by = COALESCE(excluded.added_by, bot_users.added_by),
                    added_by_name = COALESCE(excluded.added_by_name, bot_users.added_by_name),
                    updated_at = datetime('now','localtime')
                """,
                (user_id, role, added_by, added_by_name),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menyimpan role user_id=%s role=%s: %s", user_id, role, e)
        return False


def remove_user(user_id: int) -> bool:
    """Hapus user runtime."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("DELETE FROM bot_users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menghapus user_id=%s: %s", user_id, e)
        return False


def get_all_runtime_users() -> dict[int, int]:
    """Semua user runtime (user_id -> role)."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("SELECT user_id, role FROM bot_users")
            return {int(row[0]): int(row[1]) for row in cursor.fetchall()}
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil daftar user runtime: %s", e)
        return {}


def get_all_runtime_users_details() -> list[dict]:
    """Daftar user runtime lengkap dengan added_by dan timestamp."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                SELECT user_id, role, added_by, added_by_name, created_at, updated_at
                FROM bot_users
                ORDER BY created_at ASC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "user_id": int(r[0]),
                    "role": int(r[1]),
                    "added_by": int(r[2]) if r[2] is not None else None,
                    "added_by_name": r[3] or "-",
                    "created_at": str(r[4]) if r[4] else "-",
                    "updated_at": str(r[5]) if r[5] else "-",
                }
                for r in rows
            ]
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil detail user runtime: %s", e)
        return []


# ── Penerima Notif Air ──


def get_air_recipients() -> set[int]:
    """Semua ID admin penerima notif air."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("SELECT user_id FROM bot_air_recipients")
            return {int(row[0]) for row in cursor.fetchall()}
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil daftar bot_air_recipients: %s", e)
        return set()


def add_air_recipient(user_id: int) -> bool:
    """Tambah admin ke daftar notifikasi kontrol air."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("INSERT OR IGNORE INTO bot_air_recipients (user_id) VALUES (?)", (user_id,))
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menambahkan recipient user_id=%s: %s", user_id, e)
        return False


def remove_air_recipient(user_id: int) -> bool:
    """Hapus admin dari daftar notifikasi kontrol air."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute("DELETE FROM bot_air_recipients WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menghapus recipient user_id=%s: %s", user_id, e)
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
    """Catat log aksi perangkat."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO device_activity_logs (user_id, user_role, device_name, action, status, message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, user_role, device_name, action, status, message),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mencatat activity log: %s", e)
        return False


def log_power(
    device_name: str,
    power_w: float,
    voltage_v: float,
    current_a: float,
    switch_state: bool | None,
    source: str,
) -> bool:
    """Catat snapshot konsumsi daya."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO device_power_logs (device_name, power_w, voltage_v, current_a, switch_state, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (device_name, power_w, voltage_v, current_a, switch_state, source),
            )
            return True
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mencatat power log: %s", e)
        return False


# ── Logging: Application Error Logs ──


def log_app_error(
    level: str,
    logger_name: str,
    message: str,
    exception_trace: str | None = None,
    file_name: str | None = None,
    line_number: int | None = None,
) -> bool:
    """Simpan log error aplikasi."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO app_error_logs (level, logger_name, message, exception_trace, file_name, line_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (level, logger_name, message, exception_trace, file_name, line_number),
            )
            return True
    except Exception as e:
        # PENTING: jangan pakai logger.error di sini agar tidak memicu loop rekursif.
        print(f"[DATABASE WARN] Gagal menyimpan error log ke SQLite: {e}", file=sys.stderr)
        return False


class SQLiteDatabaseLogHandler(logging.Handler):
    """Handler logging yang menyimpan log ERROR dan CRITICAL ke tabel app_error_logs."""

    def __init__(self, level: int = logging.ERROR):
        super().__init__(level)
        self._is_handling = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._is_handling:
            return

        msg_str = record.getMessage()
        if record.name == "database" or "[DATABASE" in msg_str:
            return

        try:
            self._is_handling = True
            exc_trace = None
            if record.exc_info:
                exc_trace = "".join(traceback.format_exception(*record.exc_info))
            elif record.exc_text:
                exc_trace = record.exc_text

            log_app_error(
                level=record.levelname,
                logger_name=record.name,
                message=msg_str,
                exception_trace=exc_trace,
                file_name=record.filename,
                line_number=record.lineno,
            )
        except Exception:
            pass
        finally:
            self._is_handling = False


def setup_db_logging(level: int = logging.ERROR) -> None:
    """Pasang SQLiteDatabaseLogHandler ke root logger (sekali saja)."""
    root_logger = logging.getLogger()
    for h in root_logger.handlers:
        if isinstance(h, SQLiteDatabaseLogHandler):
            return
    root_logger.addHandler(SQLiteDatabaseLogHandler(level=level))
    logger.info("SQLiteDatabaseLogHandler terpasang ke root logger (level >= %s).", logging.getLevelName(level))


def get_recent_app_errors(limit: int = 20) -> list[dict]:
    """Riwayat error aplikasi terbaru."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                SELECT id, level, logger_name, message, exception_trace, file_name, line_number, created_at
                FROM app_error_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "id": r[0],
                    "level": r[1],
                    "logger_name": r[2],
                    "message": r[3],
                    "exception_trace": r[4],
                    "file_name": r[5],
                    "line_number": r[6],
                    "created_at": str(r[7]),
                }
                for r in cursor.fetchall()
            ]
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil app error logs: %s", e)
        return []


def get_recent_power_logs(device_name: str | None = None, limit: int = 50) -> list[dict]:
    """Data konsumsi daya terbaru."""
    try:
        with get_db_connection() as (_conn, cursor):
            sql = """
                SELECT id, device_name, power_w, voltage_v, current_a, switch_state, source, created_at
                FROM device_power_logs
            """
            params: tuple = ()
            if device_name:
                sql += " WHERE device_name = ?"
                params = (device_name,)
            sql += " ORDER BY id DESC LIMIT ?"
            params += (limit,)

            cursor.execute(sql, params)
            return [
                {
                    "id": r[0],
                    "device_name": r[1],
                    "power_w": float(r[2]),
                    "voltage_v": float(r[3]),
                    "current_a": float(r[4]),
                    "switch_state": bool(r[5]) if r[5] is not None else None,
                    "source": r[6],
                    "created_at": str(r[7]),
                }
                for r in cursor.fetchall()
            ]
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil recent power logs: %s", e)
        return []


def get_recent_activities(limit: int = 50) -> list[dict]:
    """Riwayat aktivitas perangkat terbaru."""
    try:
        with get_db_connection() as (_conn, cursor):
            cursor.execute(
                """
                SELECT id, user_id, user_role, device_name, action, status, message, created_at
                FROM device_activity_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "user_role": r[2],
                    "device_name": r[3],
                    "action": r[4],
                    "status": r[5],
                    "message": r[6],
                    "created_at": str(r[7]),
                }
                for r in cursor.fetchall()
            ]
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal mengambil recent activity logs: %s", e)
        return []


def get_db_stats() -> dict:
    """Statistik ringkas database (dipakai dashboard)."""
    from ..config import LOG_RETENTION_DAYS

    path = Path(SQLITE_PATH)
    stats = {
        "connected": False,
        "engine": "sqlite",
        "database": path.name or SQLITE_PATH,
        "host": str(path.parent) if path.parent != Path("") else ".",
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "retention_days": LOG_RETENTION_DAYS,
        "total_power_logs": 0,
        "total_activity_logs": 0,
        "total_error_logs": 0,
        "total_runtime_users": 0,
        "total_air_recipients": 0,
    }
    try:
        with get_db_connection() as (_conn, cursor):
            stats["connected"] = True
            for key, table in (
                ("total_power_logs", "device_power_logs"),
                ("total_activity_logs", "device_activity_logs"),
                ("total_error_logs", "app_error_logs"),
                ("total_runtime_users", "bot_users"),
                ("total_air_recipients", "bot_air_recipients"),
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[key] = cursor.fetchone()[0]
    except Exception as e:
        logger.warning("[DATABASE WARNING] Gagal mengambil statistik database: %s", e)
    return stats


# ── Housekeeping / Log Retention ──


def cleanup_old_logs(retention_days: int | None = None) -> dict[str, int]:
    """Hapus log lebih tua dari retention_days hari."""
    if retention_days is None:
        from ..config import LOG_RETENTION_DAYS

        retention_days = LOG_RETENTION_DAYS

    results = {
        "power_logs_deleted": 0,
        "activity_logs_deleted": 0,
        "error_logs_deleted": 0,
    }
    cutoff = f"-{int(retention_days)} days"

    try:
        with get_db_connection() as (_conn, cursor):
            for key, table in (
                ("power_logs_deleted", "device_power_logs"),
                ("activity_logs_deleted", "device_activity_logs"),
                ("error_logs_deleted", "app_error_logs"),
            ):
                cursor.execute(
                    f"DELETE FROM {table} WHERE created_at < datetime('now','localtime', ?)",
                    (cutoff,),
                )
                results[key] = cursor.rowcount

        logger.info(
            "Housekeeping database selesai (retention=%s hari). Total dibersihkan: %s (Power: %s, Activity: %s, Error: %s)",
            retention_days,
            sum(results.values()),
            results["power_logs_deleted"],
            results["activity_logs_deleted"],
            results["error_logs_deleted"],
        )
        return results
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menjalankan housekeeping/cleanup log lama: %s", e)
        return results
