<div align="center">


# 🤖 Telegram Bot — Tuya Smart Home Controller

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](docker-compose.yml)

**Bot Telegram untuk mengontrol perangkat smart home Tuya (BARDI)** — lampu, smart plug, dan monitoring daya. Dibangun dengan `python-telegram-bot` dan `tinytuya`.

</div>

---

## ✨ Fitur

| Fitur | Status |
|-------|--------|
| 💡 Kontrol Lampu (ON/OFF) | ✅ |
| 🔌 Kontrol Smart Plug (ON/OFF) | ✅ |
| ⚡ Monitoring Daya (Watt, Arus, Voltase) | ✅ |
| 🔐 Role-Based Access Control (RBAC) | ✅ |
| ⏳ Rate Limiting | ✅ |
| 🐳 Docker Support | ✅ |
| 🔄 Auto-restart & Graceful Shutdown | ✅ |

---

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/username/tuya-telegram-bot.git
cd tuya-telegram-bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Konfigurasi Environment

```bash
cp .env.example .env
```

Edit `.env` dan isi:

```env
# Dari @BotFather
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Perangkat Tuya
DEVICE_LAMPU_ID=your_device_id
DEVICE_LAMPU_KEY=your_local_key
DEVICE_LAMPU_IP=your_ip_address
DEVICE_LAMPU_VER=3.5

DEVICE_AIR_ID=your_device_id
DEVICE_AIR_KEY=your_local_key
DEVICE_AIR_IP=your_ip_address
DEVICE_AIR_VER=3.5

# Role-Based Access Control (contoh dummy, ganti dengan ID Telegram Anda)
SUPERADMIN_USERS=123456789

# Database (SQLite, embedded — tidak perlu server)
SQLITE_PATH=data/tuyabot.db
SQLITE_BUSY_TIMEOUT_MS=5000

# Interval Monitoring Daya (Menit)
POWER_LOG_INTERVAL_MINUTES=5
```

### 4. Jalankan Bot & API Dashboard

```bash
PYTHONPATH=src python -m tuyabot.main
```

Dashboard: `http://127.0.0.1:8080/` (atau lewat reverse proxy di host).

Login memakai `DASHBOARD_API_KEY` sekali; setelah itu dashboard memakai cookie sesi
`HttpOnly; SameSite=Strict` (berlaku `SESSION_TTL_HOURS`, default 12 jam). API key tidak
disimpan di browser. Untuk skrip/curl, header `X-API-Key` tetap diterima.

Status perangkat di dashboard datang lewat SSE (`/api/stream`) yang membaca cache di memori —
membuka banyak tab tidak menambah beban ke perangkat. Data tabel (riwayat daya/aktivitas)
dimuat saat tab-nya dibuka.

Variabel yang mengatur bagian ini: `SESSION_TTL_HOURS`, `SESSION_COOKIE_SECURE` (set `true`
bila diakses lewat HTTPS), `SESSION_SECRET` (opsional), `STREAM_INTERVAL_SECONDS`.

---

## 🗄️ Database SQLite (embedded)

Database berupa satu file (`data/tuyabot.db`) berjalan di dalam proses bot — tidak ada
server, kredensial, atau koneksi jaringan yang perlu dijaga. Praktis: satu proses, satu
penulis, sekitar 288 baris per hari.

Pragma yang dipakai: `journal_mode=WAL` (pembaca tidak memblokir penulis),
`synchronous=NORMAL`, `busy_timeout` (default 5000 ms), `foreign_keys=ON`.

Tabel dibuat otomatis saat pertama kali bot dijalankan:

- `bot_users`: daftar user dan role runtime Telegram (`user_id`, `role`, `created_at`, `updated_at`).
- `bot_air_recipients`: ID admin penerima notifikasi saat role User mengontrol air (`user_id`, `created_at`).
- `device_activity_logs`: riwayat aksi switch on/off perangkat (`user_id`, `device_name`, `action`, `status`, `message`, `created_at`).
- `device_power_logs`: riwayat metrik daya smart plug (`device_name`, `power_w`, `voltage_v`, `current_a`, `switch_state`, `source`, `created_at`).
- `app_error_logs`: error aplikasi level ERROR/CRITICAL (`level`, `logger_name`, `message`, `exception_trace`, `file_name`, `line_number`, `created_at`).

Backup harian tanpa menghentikan bot:

```bash
sqlite3 data/tuyabot.db "VACUUM INTO 'backup/tuyabot-$(date +%F).db'"
```

> 💡 **Pindah dari versi MySQL**: `scripts/migrate_mysql_to_sqlite.py` menyalin kelima tabel
> dari MySQL ke SQLite dan memverifikasi jumlah baris sumber vs tujuan. Jalankan sekali saat
> bot berhenti, dengan `MYSQL_*` masih ada di `.env`.

> 💡 **Migrasi `users_db.json` lama**: bila file itu masih ada dan tabel `bot_users` masih
> kosong, datanya dipindahkan otomatis saat start dan file diubah menjadi `users_db.json.bak`.


---

## 🤖 Command Bot

### 📖 Semua Role

| Command | Deskripsi |
|---------|-----------|
| `/start` | Menu utama |
| `/help` | Panduan sesuai role |
| `/whoami` | Cek User ID & role |
| `/status` | Status perangkat (ON/OFF) |
| `/devices` | Daftar perangkat |

### 💧 Role: User

| Command | Deskripsi |
|---------|-----------|
| `/airon` | Nyalakan smart plug |

### 💡 Role: Admin

| Command | Deskripsi |
|---------|-----------|
| `/airon` | Nyalakan smart plug |
| `/airoff` | Matikan smart plug |
| `/lampuon` | Nyalakan lampu |
| `/lampuoff` | Matikan lampu |

### 👑 Role: Superadmin

| Command | Deskripsi |
|---------|-----------|
| `/airon` | Nyalakan smart plug |
| `/airoff` | Matikan smart plug |
| `/lampuon` | Nyalakan lampu |
| `/lampuoff` | Matikan lampu |
| `/users` | Daftar semua user |
| `/allowuser <id> <role>` | Tambah/ubah role user |
| `/removeuser <id>` | Hapus user |

**Kode Role:** `1` = User, `2` = Admin

---

## 👥 Role-Based Access Control

| Role | Kontrol Air | Kontrol Lampu | Manajemen User |
|------|-------------|---------------|----------------|
| 🌐 Publik | ❌ | ❌ | ❌ |
| 💧 User | Nyalakan saja | ❌ | ❌ |
| 💡 Admin | ✅ | ✅ | ❌ |
| 👑 Superadmin | ✅ | ✅ | ✅ |

---

## 🐳 Deploy dengan Docker

### Prasyarat

- Docker & Docker Compose terinstall
- Linux environment (untuk `network_mode: host`)

### 1. Persiapan

```bash
cp .env.example .env
# Edit .env — isi semua konfigurasi
```

Kepemilikan `logs/`, `data/`, dan `backup/` **tidak perlu diurus manual**. Entrypoint
container memperbaikinya ke uid 10001 saat start, lalu langsung turun ke user non-root.

### 2. Build & Run

```bash
docker compose up --build -d
```

### 3. Monitoring

```bash
docker compose logs -f tuyabot
docker compose ps               # kolom STATUS harus "healthy"
curl -s http://127.0.0.1:8080/healthz
```

### Akses dashboard (pilih satu)

Karena `network_mode: host`, alamat bind API ditentukan `API_HOST` di `.env`. Jangan pakai
`0.0.0.0` di VPS ber-IP publik.

| `API_HOST` | Bisa dibuka dari | Catatan |
|---|---|---|
| `127.0.0.1` (default) | hanya dalam VPS | paling aman; akses lewat `ssh -L 8080:127.0.0.1:8080 user@vps` |
| `10.0.0.2` | homelab lewat WireGuard | dashboard tidak tersentuh internet publik; butuh rule ufw di VPS |
| `0.0.0.0` | siapa pun yang bisa menjangkau IP publik | **hindari** |

Untuk cara WireGuard (homelab mengakses `http://10.0.0.2:8080`):

```bash
# .env di VPS
API_HOST=10.0.0.2

# firewall VPS: hanya izinkan lewat interface WireGuard
sudo ufw deny 8080/tcp                                   # tutup dari WAN bila sebelumnya terbuka
sudo ufw allow in on wg0 to any port 8080 proto tcp
sudo ufw status numbered | grep 8080
```

Di sisi homelab, OPNsense perlu mengizinkan LAN → `10.0.0.2:8080` (rule di interface
WireGuard), dan kalau ingin nama yang enak diingat tambahkan record di Unbound:
`tuyabot.home -> 10.0.0.2` (split-horizon, tidak pernah keluar ke internet).

TLS tidak diperlukan di dalam tunnel — biarkan `SESSION_COOKIE_SECURE=false` untuk akses
`http://` lewat WireGuard. Set `true` hanya bila dashboard diakses lewat HTTPS (Cloudflare
atau reverse proxy ber-TLS).

### 3b. Uji dulu tanpa menyentuh produksi

Cara paling aman: jalankan **hanya bagian web** dari image baru. Bot Telegram tidak ikut
start, jadi tidak ada dua proses yang berebut `getUpdates` dengan token yang sama (itu
penyebab 409 Conflict), dan watchdog tidak aktif.

```bash
# dari checkout branch, bukan produksi
git checkout new-patch
docker build -t tuyabot-test .

# container uji: port 8090, database terpisah, tanpa bot Telegram
docker run -d --name tuyabot-test --network host \
  --env-file .env \
  -e API_HOST=127.0.0.1 -e API_PORT=8090 -e SQLITE_PATH=/app/data/test.db \
  -v "$PWD/test-data:/app/data" -v "$PWD/test-logs:/app/logs" \
  tuyabot-test \
  python -m uvicorn tuyabot.web.app:app --host 127.0.0.1 --port 8090

sleep 5
curl -s http://127.0.0.1:8090/healthz          # {"status":"ok"}
docker logs --tail 20 tuyabot-test
```

Buka dashboard lewat SSH tunnel dari komputer Anda:

```bash
ssh -L 8090:127.0.0.1:8090 <user>@<vps>
# lalu buka http://127.0.0.1:8090 di browser
```

Yang bisa diuji di sini: build image, entrypoint (kepemilikan volume), pembuatan skema
SQLite, login + cookie, SSE, grafik, dan **kontrol perangkat lewat REST API**
(`POST /api/devices/lampu/on`) — memakai IP perangkat sungguhan dari `.env`.

Setelah selesai, bersihkan:

```bash
docker rm -f tuyabot-test && rm -rf test-data test-logs
```

### 4. Upgrade dari versi MySQL (sekali saja)

Urutan ini mengubah penyimpanan dari MySQL ke SQLite. Downtime ±2–5 menit (termasuk build).

Yang dimigrasikan default-nya hanya **data akses**: `bot_users` (role user runtime) dan
`bot_air_recipients` (siapa yang menerima notifikasi air). Log daya/aktivitas/error tidak
dibawa — itu telemetri lama, dan tetap tersimpan di file dump. Kalau memang ingin membawa
riwayatnya, tambahkan `--include-logs` di langkah 4.

Migrasi berjalan **di dalam container bot itu sendiri** lewat `docker exec` — tidak ada
image terpisah, tidak perlu mematikan bot. Skrip `scripts/migrate_mysql_to_sqlite.py` dan
`mysql-connector-python` sudah ada di image runtime.

```bash
# 0. Pre-flight
docker compose version                 # butuh Compose v2.24+ (sintaks env_file path/required)
df -h .                                # sisakan minimal 1 GB
grep -c "^MYSQL_" .env                 # harus > 0; kredensial dipakai skrip migrasi

# 1. Tag image lama untuk rollback
docker tag tuyabot-withdb:latest tuyabot-withdb:pre-sqlite

# 2. Dump MySQL dari host (cadangan untuk rollback + arsip log lama)
mkdir -p data backup
mysqldump -u "$MYSQL_USER" -p "$MYSQL_DATABASE" > /root/tuyabot-pre-sqlite.sql
ls -lh /root/tuyabot-pre-sqlite.sql

# 3. Build dan jalankan image baru
docker compose build
docker compose up -d
sleep 20 && docker compose ps          # STATUS harus "healthy"

# 4. Salin data akses MySQL → SQLite, di dalam container yang sedang jalan
#    (`-u app` penting: tanpa itu file DB akan dimiliki root dan bot tidak bisa menulis)
docker exec -u app tuyabot-withdb \
  python scripts/migrate_mysql_to_sqlite.py

#    Keluarannya: tabel | sumber | tujuan | status. Semua harus OK dan exit code 0.
#    Tambahkan --include-logs bila ingin ikut membawa riwayat log.
#    Tambahkan --force bila tabel bot_users sudah berisi dan memang ingin ditimpa.

# 5. Verifikasi
docker exec -u app tuyabot-withdb python -c \
  "import os; print(os.path.getsize(os.getenv('SQLITE_PATH','data/tuyabot.db')), 'bytes')"
docker compose logs --tail 20 tuyabot   # tanpa traceback
```

Kalau langkah 4 keluar dengan exit code bukan 0 atau ada baris selain `OK`: **jangan** lanjut.
Bot tetap jalan dengan database kosong, jadi tidak ada data yang rusak — perbaiki kredensial
`MYSQL_*` lalu ulangi langkah 4, atau rollback.

Di Dockhand: buka container `tuyabot-withdb` → Console → jalankan perintah langkah 4 di sana
(user console sudah `app` bila dijalankan dengan `-u app`, atau tambahkan di awal perintah).

```bash
# Rollback
docker compose down
docker tag tuyabot-withdb:pre-sqlite tuyabot-withdb:latest
docker compose up -d
mysql -u "$MYSQL_USER" -p "$MYSQL_DATABASE" < /root/tuyabot-pre-sqlite.sql   # bila data perlu dipulihkan
```

Setelah seminggu berjalan normal: hapus baris `MYSQL_*` dari `.env`, lalu matikan service MySQL
lama. Skrip migrasi tetap ada di image (tidak mengganggu); ia hanya melakukan apa pun bila
dijalankan manual.

### 5. Command Docker

```bash
docker compose ps           # Status container
docker compose stop         # Stop bot
docker compose start        # Start bot
docker compose restart      # Restart bot
docker compose down         # Hapus container
docker compose down -v      # Hapus container + volumes
```

### ⚠️ Catatan Docker

- **tinytuya memerlukan jalur langsung ke perangkat** — `network_mode: host` dipakai agar rute
  WireGuard di host terpakai. Karena berbagi network host, **alamat bind API diatur `API_HOST`
  di `.env`** (default `127.0.0.1`): dashboard tidak pernah terbuka ke internet publik.
  Pilihan alamat dan cara aksesnya ada di bagian "Akses dashboard" di atas.
- **Container jalan sebagai user non-root (uid 10001)** dan filesystem-nya `read_only`.
  Hanya `logs/`, `data/`, dan `backup/` yang writable — semuanya bind-mount.
  Kepemilikan ketiga direktori diperbaiki otomatis oleh entrypoint saat start, jadi tidak ada
  langkah `chown` manual. Kalau filesystem menolak `chown` (mis. NFS root squash), entrypoint
  menulis peringatan dan lanjut; cek izin volume kalau bot gagal membuka database.
- **Database SQLite** ada di `data/tuyabot.db` (WAL). Backup kapan saja tanpa menghentikan bot:
  `docker compose exec tuyabot python -c "import sqlite3; sqlite3.connect('/app/data/tuyabot.db').execute(\"VACUUM INTO '/app/backup/tuyabot.db'\")"`
- **Healthcheck** memanggil `/healthz` (tanpa API key, tanpa sentuh database), jadi `docker ps`
  jujur soal hidup/matinya proses.
- **Log persist** di `bot.log` via volume mount.

---

## 🛠️ Systemd (Linux)

```bash
sudo cp tuyabot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tuyabot
sudo systemctl start tuyabot
sudo systemctl status tuyabot
```

---

## 📁 Struktur Project

```
tuya-telegram-bot/
│
├── src/tuyabot/
│   ├── main.py                 # Entry point: bot + REST API + scheduler
│   ├── config.py               # Konfigurasi & validasi
│   │
│   ├── infra/                  # Infrastruktur lintas fitur
│   │   ├── asyncdb.py          # Query database di luar event loop
│   │   ├── scheduler.py        # Satu loop untuk semua pekerjaan berkala
│   │   └── state_cache.py      # Cache status perangkat (TTL + single-flight)
│   │
│   ├── devices/                # Akses perangkat
│   │   ├── local.py            # tinytuya: koneksi & DPS, lock per perangkat
│   │   └── service.py          # Executor + timeout untuk I/O perangkat
│   │
│   ├── storage/
│   │   └── sqlite_store.py     # Skema & query SQLite
│   │
│   ├── access/                 # Kontrol akses
│   │   ├── roles.py            # RBAC (ENV + runtime database)
│   │   └── rate_limit.py       # Rate limiting per role
│   │
│   ├── telegram/
│   │   └── handlers.py         # Command, callback, menu, watchdog air
│   │
│   ├── web/                    # REST API dashboard
│   │   ├── app.py              # FastAPI app + /healthz
│   │   ├── routes.py           # Endpoint perangkat, log, database
│   │   ├── deps.py             # Device lookup untuk endpoint
│   │   ├── auth.py             # API key + session cookie (HMAC)
│   │   └── schemas.py          # Pydantic models
│   │
│   └── static/                 # Dashboard
│       ├── index.html          # markup saja
│       ├── css/app.css
│       └── js/                 # app.js, api.js, chart.js
│
├── scripts/
│   ├── scan_devices.py         # Discovery perangkat (sekali saat setup)
│   ├── test_connection.py      # Uji koneksi ke perangkat
│   └── migrate_mysql_to_sqlite.py  # Migrasi data sekali jalan
│
├── tests/                      # pytest (unit + integrasi ringan)
├── docs/REFACTOR.md            # Catatan refactor per fase
├── requirements.txt            # Dependensi runtime
├── requirements-dev.txt        # Dependensi dev/CI
├── pyproject.toml              # Konfigurasi ruff & pytest
├── Dockerfile                  # Docker image
├── docker-compose.yml          # Docker orchestration
├── .github/workflows/ci.yml    # CI: ruff + pytest
└── .env.example                # Template environment
```

---

## 🔌 DPS Mapping Perangkat

### 💡 Lampu (BARDI Smart Light Bulb 12W RGBWW)

| DPS | Kode | Fungsi |
|-----|------|--------|
| `20` | `switch_led` | ON / OFF |
| `21` | `work_mode` | white / colour / scene / music |
| `22` | `bright_value` | Kecerahan (10-1000) |
| `23` | `temp_value` | Suhu warna (0-1000) |
| `24` | `colour_data` | Data warna RGB |

### 🔌 Smart Plug (BARDI Smart Plug 16A)

| DPS | Kode | Fungsi | Unit |
|-----|------|--------|------|
| `1` | `switch_1` | ON / OFF | - |
| `18` | `cur_current` | Arus | mA |
| `19` | `cur_power` | Daya | W (scale 1) |
| `20` | `cur_voltage` | Voltase | V (scale 1) |

---

## 🔒 Keamanan

- **Token & credentials** di `.env` (tidak di-commit)
- **Role-based access** dengan 4 level permission
- **Rate limiting** per role (10–120 request/menit)
- **Graceful shutdown** untuk deploy Docker
- **State awareness** — tidak mengirim perintah redundan

---

## 📈 Monitoring & Backup

### Uptime Kuma (dilakukan di panel Anda)

Bot sudah menyediakan liveness probe yang **tidak butuh API key** dan **tidak menyentuh
database**: `GET /healthz` → `{"status":"ok"}`.

Pengaturan di Uptime Kuma:

| Field | Nilai |
|---|---|
| Monitor type | HTTP(s) – Keyword |
| URL | `http://127.0.0.1:8080/healthz` (dari host VPS) atau `http://<IP-host>:8080/healthz` bila Kuma di mesin lain |
| Keyword | `ok` |
| Heartbeat interval | 60 detik |
| Retries | 2 |
| Authentication | tidak ada |

Pakai `/healthz`, jangan `/api/health`: yang kedua butuh autentikasi dan ikut memeriksa
database, sehingga MySQL/SQLite yang sedang sibuk akan terlihat seperti bot mati.

### Backup otomatis

Scheduler menjalankan job `backup` setiap `BACKUP_INTERVAL_HOURS` (default 24 jam; yang
pertama 15 menit setelah start):

- Salinan dibuat dengan `VACUUM INTO` → konsisten walau bot sedang menulis, tanpa downtime.
- File: `backup/tuyabot-YYYY-MM-DD_HHMMSS.db` (di container: `/app/backup`).
- Salinan lebih tua dari `BACKUP_RETENTION_DAYS` (default 14) dihapus otomatis.
- Status terakhir terlihat di dashboard tab **Sistem** → "Backup terakhir".

Backup manual tanpa menghentikan bot:

```bash
docker compose exec tuyabot python -c "
import sqlite3; sqlite3.connect('/app/data/tuyabot.db').execute(\"VACUUM INTO '/app/backup/manual.db'\")"
```

### Restore

```bash
docker compose stop tuyabot
cp backup/tuyabot-2026-11-17_030000.db data/tuyabot.db
rm -f data/tuyabot.db-wal data/tuyabot.db-shm    # sisa WAL dari file lama
docker compose start tuyabot
```

Kepemilikan file tidak perlu diurus: entrypoint memperbaikinya saat start.

---

## 🔧 Troubleshooting

### Perangkat tidak terhubung

```bash
PYTHONPATH=src python scripts/test_connection.py
```

- Pastikan bot & perangkat di **jaringan WiFi yang sama**
- Cek IP perangkat: `python -m tinytuya scan`
- Update IP di `.env` jika berubah

### Docker: perangkat tidak ditemukan

- `network_mode: host` hanya bekerja di **Linux**
- Mac/Windows Docker Desktop: gunakan Tuya Cloud API, atau deploy di Raspberry Pi

### Token bot tidak valid

- Dapatkan token baru dari [@BotFather](https://t.me/BotFather)
- Update di `.env` — jangan hardcode di kode

---

## 📝 Changelog

| Versi | Perubahan |
|-------|-----------|
| 1.0.0 | RBAC, rate limit, Docker, state awareness |

---

## 📄 Lisensi

MIT License — lihat [LICENSE](LICENSE) untuk detail.
