#!/bin/sh
# Entrypoint: rapikan kepemilikan volume lalu turun ke user non-root.
#
# Kenapa ada: volume ./logs, ./data, ./backup di host bisa dimiliki root (dibuat
# Docker saat pertama kali) atau dimiliki root oleh image versi lama yang jalan
# sebagai root. Tanpa langkah ini, container non-root gagal membuka database/log
# dan operator harus ingat menjalankan `chown` manual setiap kali deploy.
#
# Skrip ini hanya berjalan sebagai root (default image). Kalau container
# dijalankan dengan --user lain, skrip langsung exec tanpa menyentuh apa pun.
set -eu

APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

if [ "$(id -u)" = "0" ]; then
    for dir in /app/logs /app/data /app/backup; do
        [ -d "$dir" ] || mkdir -p "$dir"
        # Hanya perbaiki bila perlu, supaya start berikutnya tidak menyentuh apa pun.
        if [ "$(stat -c '%u:%g' "$dir")" != "${APP_UID}:${APP_GID}" ]; then
            # Jangan gagalkan start kalau filesystem menolak chown (mis. NFS root squash).
            chown -R "${APP_UID}:${APP_GID}" "$dir" 2>/dev/null || \
                echo "[entrypoint] peringatan: gagal chown $dir, lanjut (periksa izin volume)" >&2
        fi
    done

    # Turun ke user aplikasi tanpa meninggalkan proses root.
    if command -v setpriv >/dev/null 2>&1; then
        exec setpriv --reuid="${APP_UID}" --regid="${APP_GID}" --init-groups "$@"
    elif command -v su-exec >/dev/null 2>&1; then
        exec su-exec "${APP_UID}:${APP_GID}" "$@"
    else
        exec su app -s /bin/sh -c 'exec "$@"' sh "$@"
    fi
fi

exec "$@"
