#!/usr/bin/env python3
"""Migrasi data dari MySQL (implementasi lama) ke SQLite (implementasi baru).

Dijalankan SEKALI di server, saat bot berhenti.

Default: hanya memindahkan **data akses** — `bot_users` (role user runtime) dan
`bot_air_recipients` (siapa yang menerima notifikasi air). Log daya/aktivitas/error
adalah telemetri lama dan tidak dibawa; kalau perlu, pakai `--include-logs`.

Contoh:

    docker build --target migration -t tuyabot-migration .
    docker run --rm --network host --env-file .env -v "$PWD/data:/app/data" \
        tuyabot-migration python scripts/migrate_mysql_to_sqlite.py

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
