# ───────────────────────────────────────────
# Dockerfile — Telegram Bot Tuya Smart Home
# Multi-stage: dependensi dibangun di builder, image akhir tanpa compiler.
# ───────────────────────────────────────────

# ── Stage 1: dependensi ──
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# build-essential hanya ada di stage ini (beberapa wheel perlu kompilasi bila
# tidak tersedia untuk platform ini). Tidak ikut ke image akhir.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


# ── Stage 2: runtime ──
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Asia/Makassar

# User non-root. UID/GID 10001 harus punya izin tulis pada volume ./logs dan
# ./data di host (lihat docs/REFACTOR.md, Fase 4).
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./src
COPY --chown=app:app scripts ./scripts

RUN mkdir -p /app/logs /app/data /app/backup && chown -R app:app /app/logs /app/data /app/backup

# Tidak memakai USER app: entrypoint perlu root sebentar untuk memperbaiki
# kepemilikan volume (bind-mount dari host sering milik root), lalu langsung
# turun ke uid 10001 sebelum aplikasi dijalankan.
COPY --chown=root:root entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 8080

# Liveness: /healthz tidak butuh API key dan tidak menyentuh database.
# Host diambil dari API_HOST supaya tetap benar walau bind-nya bukan loopback
# (mis. alamat WireGuard). 0.0.0.0 tidak bisa dipakai sebagai tujuan request.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os,sys,urllib.request; h=os.getenv('API_HOST','127.0.0.1'); h='127.0.0.1' if h in ('0.0.0.0','','::') else h; p=os.getenv('API_PORT','8080'); sys.exit(0 if urllib.request.urlopen(f'http://{h}:{p}/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "tuyabot.main"]


# ── Stage 3: migrasi MySQL → SQLite (bukan untuk produksi) ──
# Dipakai sekali saat pindah penyimpanan:
#   docker build --target migration -t tuyabot-migration .
FROM runtime AS migration

# mysql-connector-python sengaja TIDAK ada di image runtime; hanya di stage ini.
USER root
RUN /opt/venv/bin/pip install --no-cache-dir "mysql-connector-python>=9.0.0"

# entrypoint tetap dipakai: ia merapikan kepemilikan ./data lalu turun ke uid 10001

