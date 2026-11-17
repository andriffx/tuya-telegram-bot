#!/usr/bin/env python3
"""Migrasi data dari MySQL (implementasi lama) ke SQLite (implementasi baru).

Dijalankan SEKALI di server, saat bot berhenti. Skrip ini:

1. membuat skema SQLite (lewat database.init_db),
2. menyalin kelima tabel dari MySQL,
3. membandingkan jumlah baris sumber vs tujuan dan gagal (exit 1) bila beda.

Contoh:

    docker compose stop tuyabot
    python scripts/migrate_mysql_to_sqlite.py --mysql-dump /tmp/tuyabot.sql
    docker compose up -d

Rollback: kembalikan file `mysqldump` ke MySQL dan jalankan image versi lama.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TABLES = {
    "bot_users": ["user_id", "role", "added_by", "added_by_name", "created_at", "updated_at"],
    "bot_air_recipients": ["user_id", "created_at"],
    "device_activity_logs": ["id", "user_id", "user_role", "device_name", "action", "status", "message", "created_at"],
    "device_power_logs": ["id", "device_name", "power_w", "voltage_v", "current_a", "switch_state", "source", "created_at"],
    "app_error_logs": ["id", "level", "logger_name", "message", "exception_trace", "file_name", "line_number", "created_at"],
}


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


def count_rows(cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cursor.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrasi data bot Tuya dari MySQL ke SQLite")
    parser.add_argument(
        "--mysql-dump",
        help="Path ke file mysqldump yang sudah dibuat SEBELUM migrasi (untuk dokumentasi/rollback)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Timpa tabel tujuan walau sudah berisi data",
    )
    args = parser.parse_args()

    if args.mysql_dump and not Path(args.mysql_dump).exists():
        print(f"[!] File dump tidak ditemukan: {args.mysql_dump}")
        return 2

    import database

    sqlite_path = os.getenv("SQLITE_PATH", "data/tuyabot.db")
    database.SQLITE_PATH = sqlite_path
    database.close_connection()

    if not database.init_db(migrate_json=False):
        print("[!] Gagal menyiapkan skema SQLite.")
        return 1

    existing = len(database.get_recent_power_logs(limit=1))
    if existing and not args.force:
        print(f"[!] {sqlite_path} sudah berisi data. Pakai --force bila memang ingin menimpa.")
        return 1

    print(f"[*] Sumber : MySQL {os.getenv('MYSQL_HOST', '127.0.0.1')}/{os.getenv('MYSQL_DATABASE', 'tuyabot')}")
    print(f"[*] Tujuan : SQLite {sqlite_path}")

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

        for table, columns in TABLES.items():
            column_list = ", ".join(columns)
            try:
                src_cursor.execute(f"SELECT {column_list} FROM {table}")
                rows = src_cursor.fetchall()
            except Exception as e:
                print(f"[!] Gagal membaca {table} dari MySQL: {e}")
                return 1

            placeholders = ", ".join("?" for _ in columns)
            dst_cursor.executemany(
                f"INSERT OR REPLACE INTO {table} ({column_list}) VALUES ({placeholders})",
                [tuple(row) for row in rows],
            )
            dst.commit()

            dst_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            copied = int(dst_cursor.fetchone()[0])
            summary.append((table, len(rows), copied))

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

        print("\n[✓] Migrasi selesai. Jalankan bot, lalu cek /api/db/stats dan satu perintah /status.")
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
