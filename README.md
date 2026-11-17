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

# Role-Based Access Control
SUPERADMIN_USERS=your_telegram_user_id

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

# Direktori data + kepemilikan untuk user non-root di image (uid 10001)
sudo mkdir -p logs data backup
sudo chown -R 10001:10001 logs data backup
```

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

### 4. Command Docker

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
  WireGuard di host terpakai. Konsekuensinya API ikut berbagi network host, karena itu
  `API_HOST: 127.0.0.1` di compose wajib dipertahankan: dashboard hanya bisa diakses lewat
  reverse proxy di host (nginx-ui/Cloudflare), bukan langsung dari internet.
- **Container jalan sebagai user non-root (uid 10001)** dan filesystem-nya `read_only`.
  Hanya `logs/`, `data/`, dan `backup/` yang writable — semuanya bind-mount.
  Kalau `chown` di langkah 1 terlewat, bot gagal membuka database/log: jalankan chown lalu
  `docker compose restart`.
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
│   │   ├── deps.py             # Autentikasi X-API-Key
│   │   └── schemas.py          # Pydantic models
│   │
│   └── static/index.html       # Dashboard
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
