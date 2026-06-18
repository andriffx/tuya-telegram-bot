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
```

### 4. Jalankan Bot

```bash
python bot.py
```

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
touch users_db.json
```

### 2. Build & Run

```bash
docker-compose up --build -d
```

### 3. Monitoring

```bash
docker-compose logs -f tuyabot
```

### 4. Command Docker

```bash
docker-compose ps           # Status container
docker-compose stop         # Stop bot
docker-compose start        # Start bot
docker-compose restart      # Restart bot
docker-compose down         # Hapus container
docker-compose down -v      # Hapus container + volumes
```

### ⚠️ Catatan Docker

- **tinytuya memerlukan LAN langsung** — `network_mode: host` diperlukan. Jika menggunakan Mac/Windows Docker Desktop, deploy di Raspberry Pi/Linux server, atau gunakan Tuya Cloud API.
- **Data user persist** di `users_db.json` via volume mount.
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
├── bot.py                    # Entry point bot Telegram
├── tuya_controller.py        # Logic kontrol perangkat Tuya
├── auth_manager.py           # Role-based access control
├── rate_limiter.py           # Rate limiting proteksi
├── config.py                 # Konfigurasi & validasi
│
├── requirements.txt          # Python dependencies
├── Dockerfile                # Docker image
├── docker-compose.yml        # Docker orchestration
├── .dockerignore             # Docker build exclusions
│
├── tuyabot.service           # Systemd service file
├── ecosystem.config.js       # PM2 config (opsional)
│
├── .env.example              # Template environment
├── .gitignore                # Git exclusions
└── README.md                 # Dokumentasi ini
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
python test_connection.py
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

---

<div align="center">

**Dibuat dengan ❤️ untuk smart home Indonesia**

</div>
