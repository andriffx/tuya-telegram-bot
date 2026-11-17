#!/usr/bin/env python3
"""Migrasi data dari MySQL (implementasi lama) ke SQLite (implementasi baru).

Dijalankan SEKALI, manual, di dalam container bot yang sedang berjalan. Tidak ada
stage/image terpisah dan bot tidak perlu dimatikan: skrip ini hanya menyisipkan baris,
sementara bot membaca tabel user dari SQLite per permintaan (tanpa cache memori).

Default: hanya memindahkan **data akses** — `bot_users` (role user runtime) dan
`bot_air_recipients` (siapa yang menerima notifikasi air). Log daya/aktivitas/error
adalah telemetri lama dan tidak dibawa; kalau perlu, pakai `--include-logs`.

Contoh (dari host, container bot sudah jalan):

    docker exec -u app tuyabot-withdb python scripts/migrate_mysql_to_sqlite.py
    docker exec -u app tuyabot-withdb python scripts/migrate_mysql_to_sqlite.py --include-logs

`-u app` wajib: tanpa itu perintah jalan sebagai root dan file DB jadi milik root,
sehingga bot (uid 10001) tidak bisa menulis.

Rollback: kembalikan file `mysqldump` ke MySQL dan jalankan image versi lama.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Semua tabel yang dikenal, beserta kolomnya (urutan harus sama dengan skema SQLite).
TABLES = {
    "bot_users": ["user_id", "role", "added_by", "added_by_name", "created_at", "updated_at"],
    "bot_air_recipients": ["user_id", "created_at"],
    "device_activity_logs": ["id", "user_id", "user_role", "device_name", "action", "status", "message", "created_at"],
    "device_power_logs": ["id", "device_name", "power_w", "voltage_v", "current_a", "switch_state", "source", "created_at"],
    "app_error_logs": ["id", "level", "logger_name", "message", "exception_trace", "file_name", "line_number", "created_at"],
}

# Data yang wajib dibawa: tanpa ini user kehilangan role dan penerima notifikasi.
USER_TABLES = ("bot_users", "bot_air_recipients")


def select_tables(include_logs: bool) -> dict[str, list[str]]:
    """Tabel yang akan dimigrasikan. Default hanya data akses."""
    if include_logs:
        return dict(TABLES)
    return {name: TABLES[name] for name in USER_TABLES}


def mysql_connection():
    import mysql.connector

    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "tuyabot"),
        connection_timeout=int(os.getenv("MYSQL_CONNECT_TIMEOUT", "5")),
    )


APP_UID = int(os.getenv("APP_UID", "10001"))


def _drop_to_app_user() -> None:
    """Turun dari root ke uid aplikasi sebelum menyentuh database.

    Dockhand membuka console container sebagai root. Container produksi memakai
    `cap_drop: ALL`, jadi root di sini tidak punya CAP_DAC_OVERRIDE dan tidak bisa
    menulis file milik uid 10001 (SQLite melaporkannya sebagai
    "attempt to write a readonly database"). Dengan menurunkan diri sendiri,
    perintah tetap bisa dijalankan apa adanya dari console, dan file DB tetap
    dimiliki user aplikasi.
    """
    if os.geteuid() != 0:
        return
    print(f"[*] Berjalan sebagai root; turun ke uid {APP_UID} agar file DB tetap milik aplikasi.")
    try:
        os.setgroups([])
        os.setgid(APP_UID)
        os.setuid(APP_UID)
    except OSError as exc:
        print(f"[!] Gagal turun ke uid {APP_UID}: {exc}")
        print("    Jalankan langsung sebagai user aplikasi:")
        print("      docker exec -u app tuyabot-withdb python scripts/migrate_mysql_to_sqlite.py")
        raise SystemExit(3) from exc


def _preflight_writable(path: str) -> str | None:
    """Pastikan file/tujuan SQLite benar-benar bisa ditulis proses ini.

    Container produksi memakai `cap_drop: ALL`, jadi root di dalam container
    TIDAK punya CAP_DAC_OVERRIDE: ia tidak bisa menulis file milik uid 10001.
    Tanpa pemeriksaan ini, kegagalan muncul sebagai
    `sqlite3.OperationalError: attempt to write a readonly database` yang
    membingungkan. Cek dengan menulis probe file, bukan `os.access`, karena
    `os.access` menjawab menurut uid root dan menyesatkan di kondisi ini.
    """
    target = Path(path)
    directory = target.parent if str(target.parent) else Path(".")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-probe-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return f"direktori {directory} tidak bisa ditulis ({exc.strerror or exc})"

    if target.exists():
        try:
            with target.open("ab"):
                pass
        except OSError as exc:
            return f"file {target} tidak bisa ditulis ({exc.strerror or exc})"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrasi data bot Tuya dari MySQL ke SQLite")
    parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Ikut memindahkan device_power_logs, device_activity_logs, app_error_logs "
        "(default: hanya user & penerima notifikasi)",
    )
    parser.add_argument(
        "--mysql-dump",
        help="Path ke file mysqldump yang sudah dibuat SEBELUM migrasi (untuk dokumentasi/rollback)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Timpa data tujuan walau tabel bot_users sudah berisi user",
    )
    args = parser.parse_args()

    if args.mysql_dump and not Path(args.mysql_dump).exists():
        print(f"[!] File dump tidak ditemukan: {args.mysql_dump}")
        return 2

    tables = select_tables(args.include_logs)

    from tuyabot.storage import sqlite_store as database

    sqlite_path = os.getenv("SQLITE_PATH", "data/tuyabot.db")
    database.SQLITE_PATH = sqlite_path
    database.close_connection()

    _drop_to_app_user()
    problem = _preflight_writable(sqlite_path)
    if problem:
        print(f"[!] Database SQLite tidak bisa ditulis: {problem}")
        print(f"    Path   : {Path(sqlite_path).resolve()}")
        if os.geteuid() == 0:
            print("    Anda berjalan sebagai root DI DALAM container. Container ini memakai")
            print("    cap_drop ALL, sehingga root tidak boleh menulis file milik uid 10001.")
            print("    Jalankan sebagai user aplikasi (pilih salah satu):")
            print("      docker exec -u app tuyabot-withdb python scripts/migrate_mysql_to_sqlite.py")
            print("      setpriv --reuid=10001 --regid=10001 --clear-groups python scripts/migrate_mysql_to_sqlite.py")
        return 3

    if not database.init_db(migrate_json=False):
        print("[!] Gagal menyiapkan skema SQLite.")
        return 1

    existing_users = database.get_all_runtime_users()
    if existing_users and not args.force:
        print(f"[!] {sqlite_path} sudah berisi {len(existing_users)} user runtime.")
        print("    Pakai --force bila memang ingin menimpa dengan data dari MySQL.")
        return 1

    print(f"[*] Sumber  : MySQL {os.getenv('MYSQL_HOST', '127.0.0.1')}/{os.getenv('MYSQL_DATABASE', 'tuyabot')}")
    print(f"[*] Tujuan  : SQLite {sqlite_path}")
    scope = "semua tabel (--include-logs)" if args.include_logs else "user & penerima notifikasi"
    print(f"[*] Cakupan : {scope}")
    if not args.include_logs:
        print("[*] Log daya/aktivitas/error TIDAK dimigrasikan (tetap ada di file mysqldump).")

    try:
        source = mysql_connection()
        src_cursor = source.cursor()
    except Exception as e:
        print(f"[!] Tidak bisa terhubung ke MySQL: {e}")
        return 1

    summary = []
    try:
        dst = database._connect()
        dst_cursor = dst.cursor()

        for table, columns in tables.items():
            column_list = ", ".join(columns)
            placeholders = ", ".join("?" for _ in columns)
            try:
                src_cursor.execute(f"SELECT {column_list} FROM {table}")
                rows = src_cursor.fetchall()
            except Exception as e:
                print(f"[!] Gagal membaca {table} dari MySQL: {e}")
                return 1

            dst_cursor.executemany(
                f"INSERT OR REPLACE INTO {table} ({column_list}) VALUES ({placeholders})",
                [tuple(row) for row in rows],
            )
            dst.commit()

            dst_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            summary.append((table, len(rows), int(dst_cursor.fetchone()[0])))

        print("\nRingkasan migrasi:")
        print(f"  {'tabel':24} {'sumber':>8} {'tujuan':>8}  status")
        failed = False
        for table, source_rows, target_rows in summary:
            ok = source_rows == target_rows
            failed = failed or not ok
            print(f"  {table:24} {source_rows:>8} {target_rows:>8}  {'OK' if ok else 'BEDA'}")

        if failed:
            print("\n[!] Ada tabel dengan jumlah baris berbeda. Jangan jalankan bot dulu.")
            return 1

        users = len(database.get_all_runtime_users())
        recipients = len(database.get_air_recipients())
        print(f"\n[✓] Migrasi selesai: {users} user runtime, {recipients} penerima notifikasi air.")
        print("    Jalankan bot, lalu cek /status di Telegram dan tab Pengguna di dashboard.")
        return 0
    finally:
        try:
            src_cursor.close()
            source.close()
        except Exception:
            pass
        database.close_connection()


if __name__ == "__main__":
    raise SystemExit(main())
