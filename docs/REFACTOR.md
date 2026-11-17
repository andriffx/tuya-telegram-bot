# Rencana Refactor — tuya-telegram-bot

Dokumen ini adalah peta kerja refactor. Ditulis supaya bisa direview per fase dan
dihentikan kapan saja tanpa meninggalkan repo dalam kondisi setengah jadi.

Keputusan yang sudah diambil:

- **Tetap Python.** Tidak port ke Rust. Alasan utama: `tinytuya` (Python) mendukung
  protokol 3.1–3.5 termasuk AES-GCM untuk 3.5, sedangkan crate Rust yang ada berhenti
  di 3.1/3.3 (`rust-async-tuyapi`) atau masih 0.x dengan satu maintainer (`rustuya`).
  Port akan memindahkan risiko ke library protokol, bukan ke kode aplikasi.
- **MySQL → SQLite.** Satu penulis, ±300 baris/hari, satu proses: MySQL memang overkill.
  Lihat Fase 2b.
- **Bot jalan di VPS**, device di rumah. `network_mode: host` hanya dipakai untuk
  discovery UDP; data device sudah lengkap dan statis, jadi host networking bisa dilepas
  (lihat Fase 4 + checklist verifikasi rute).

---

## Status

| Fase | Isi | Status |
|---|---|---|
| 1 | Bug + CI + higiene | **selesai di branch ini** |
| 2 | Event loop, scheduler, timeout, health | belum |
| 2b | MySQL → SQLite + migrasi data | belum (menunggu review) |
| 3 | Struktur modular (`src/tuyabot/`) | belum |
| 4 | Dockerfile & compose produksi | belum |
| 5 | UI | belum |
| 6 | Ops & dokumentasi | belum |

---

## Fase 1 — selesai

### Bug yang diperbaiki

`run.py` hanya meng-import nama fungsi dari `database`, lalu memakai `database.cleanup_old_logs`
di dalam loop 24 jam. `NameError`-nya tertelan `except Exception`, jadi:

- housekeeping tidak pernah jalan sejak awal,
- tidak ada test yang gagal,
- satu-satunya jejaknya satu baris ERROR tiap 24 jam di log.

Perbaikan: `import database` dan semua pemanggilan lewat modul. Ditambah
`tests/test_run_wiring.py` yang menguji **perilaku** (satu siklus housekeeping harus
memanggil cleanup), bukan sekadar teks. Test ini terbukti gagal pada kode lama.

### Koreksi terhadap review awal

`run.py` error_callback yang memanggil `process_error(error=exc, update=None)` **bukan bug**.
`python-telegram-bot` memakai pola persis itu di `Application.run_polling`
(`telegram/ext/_application.py:836`), dan `process_error` membangun context di dalam
`try/except` sehingga `update=None` ditangani. Tidak diubah.

### Higiene

- `requirements.txt` (runtime) dipisah dari `requirements-dev.txt` (pytest, ruff, httpx).
  Image produksi berhenti mengangkut test runner.
- `pyproject.toml`: konfigurasi ruff + pytest. `pytest.ini` dihapus.
- `ruff check .` bersih (133 temuan otomatis diperbaiki: import tak terpakai, urutan import,
  f-string tanpa placeholder, anotasi `typing.*` → builtin).
- `.github/workflows/ci.yml`: ruff + pytest pada push dan PR. Ini yang mencegah kelas bug
  Fase 1 terulang.
- `tuyabot.service` dan `ecosystem.config.js` dihapus: keduanya menjalankan `bot.py`,
  bukan `run.py`, sehingga siapa pun yang memakainya kehilangan API, power monitor, dan
  housekeeping. Docker/compose adalah satu-satunya jalur deploy.
  (Kalau nanti butuh systemd lagi, harus menunjuk `run.py`.)
- `config.py`: `load_dotenv(".env.dockhand", override=True)` dihapus. Satu sumber
  konfigurasi: environment proses menang atas `.env`. Artinya `.env.dockhand` harus
  di-rename jadi `.env` di server (compose sudah menyebut keduanya, jadi tidak putus).
- `.gitignore`/`.dockerignore`: entri untuk artefak SQLite (`*.db`, `*.db-wal`, `data/`).

### Verifikasi yang dijalankan

```
ruff check .        -> All checks passed
pytest -q           -> 35 passed (30 lama + 5 baru)
```

Baseline sebelum perubahan: `30 passed`. Tidak ada test lama yang dilonggarkan, kecuali
`test_power_monitor.py` yang mem-patch `run.log_power` → sekarang `run.database.log_power`
mengikuti perubahan import (perilaku yang diuji tetap sama).

---

## Fase 2 — event loop & scheduler (belum)

Masalah: panggilan MySQL sinkron di dalam `async def` memblokir satu-satunya event loop,
sehingga bot berhenti merespons saat dashboard memuat log. Ditambah dua scheduler
(power monitor 5 menit, watchdog air 3 menit) mem-polling device yang sama di balik satu
lock global, dengan `socketTimeout(4) × retry 3`.

Rencana:

1. `infra/asyncdb.py`: helper `run_db(fn, *args)` berbasis `asyncio.to_thread`.
   Dipakai di `bot.py` (log_activity, log_power) dan `api/routes.py` (semua endpoint `/db/*`,
   `/api/devices/*`).
2. Satu scheduler (`infra/scheduler.py`): polling tiap device sekali per interval →
   tulis ke `StateCache` (nilai + timestamp). Konsumen:
   - power monitor (5 menit) membaca cache,
   - watchdog air (3 menit) membaca cache,
   - `GET /api/devices/{name}/status` membaca cache (fallback: polling langsung bila basi).
3. `asyncio.Lock` per device menggantikan satu lock global; `asyncio.wait_for` untuk setiap
   panggilan Tuya (batas pasti, bukan hanya socket timeout); executor 2 → 4 worker.
4. `GET /healthz` tanpa auth (liveness, untuk Uptime Kuma) + `GET /api/health` readiness
   (cek DB + device terakhir diketahui).
5. `rate_limiter.py`: prune bucket uid yang tidak aktif > 2× window.

Efek yang bisa diukur setelah fase ini: request dashboard tidak lagi menahan bot, dan
jumlah koneksi TCP ke device turun (satu polling, banyak pembaca).

---

## Fase 2b — MySQL → SQLite (menunggu review)

Kenapa SQLite cocok di sini: satu proses, satu penulis, ±288 baris/hari untuk power log.
MySQL menambah satu service, satu kredensial, satu titik gagal, dan `pool_reset_session`
yang tidak ada gunanya.

### Skema

Sama persis dengan sekarang, hanya portabel:

| MySQL | SQLite |
|---|---|
| `BIGINT PRIMARY KEY` (user_id) | `INTEGER PRIMARY KEY` |
| `TINYINT` | `INTEGER` + `CHECK (role BETWEEN 0 AND 3)` |
| `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | `TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))` |
| `ON UPDATE CURRENT_TIMESTAMP` | tidak ada — di-set di aplikasi |
| `AUTO_INCREMENT` | `INTEGER PRIMARY KEY AUTOINCREMENT` |

Pragma wajib saat koneksi dibuka:

```sql
PRAGMA journal_mode=WAL;      -- pembaca tidak memblokir penulis
PRAGMA synchronous=NORMAL;    -- aman dengan WAL, jauh lebih cepat dari FULL
PRAGMA busy_timeout=5000;     -- hindari SQLITE_BUSY saat dua thread menulis
PRAGMA foreign_keys=ON;
```

Akses: satu koneksi per thread (bukan pool), karena `asyncio.to_thread` memakai beberapa
thread. `check_same_thread=False` tidak dipakai — lebih aman satu koneksi per thread lewat
`threading.local()`.

### Lokasi file

`./data/tuyabot.db` di-bind-mount ke container (`/app/data`). Di VPS, `data/` masuk
`.gitignore`, dan backup harian:

```
sqlite3 data/tuyabot.db "VACUUM INTO 'backup/tuyabot-$(date +%F).db'"
```

`VACUUM INTO` menghasilkan salinan konsisten tanpa menghentikan bot.

### Migrasi (dijalankan sekali, di VPS, saat bot berhenti)

1. `docker compose stop tuyabot`
2. `python scripts/migrate_mysql_to_sqlite.py` — membaca MySQL lewat env `MYSQL_*` yang ada,
   membuat `data/tuyabot.db`, menyalin kelima tabel, lalu mencetak jumlah baris
   sumber vs tujuan.
3. Verifikasi: bandingkan `SELECT COUNT(*)` per tabel dan 10 baris terakhir `device_power_logs`.
4. `docker compose up -d`, cek `/api/db/stats` dan satu perintah `/status` di bot.
5. Simpan `mysqldump` sebelum langkah 2 — rollback = restore dump + jalankan image lama.

Dampak downtime: ±2 menit. Tidak ada perubahan skema data, jadi rollback bersih.

---

## Fase 3 — struktur modular (belum)

```
src/tuyabot/
  domain/        device.py (DPS mapping), events.py, ports.py (Protocol)
  app/           control.py, watchdog.py, roles.py, ratelimit.py
  adapters/      tuya_local.py, sqlite.py
                 telegram/  handlers/{devices,admin,monitoring,flows}.py, keyboards.py
                 web/       routes/{devices,db,health}.py, auth.py, static/
  infra/         config.py (pydantic-settings), logging.py, scheduler.py, state_cache.py, asyncdb.py
  main.py        asyncio: bot + api + scheduler dalam satu proses
```

Yang tidak dilakukan: memecah `bot.py` per handler tanpa alasan, atau memperkenalkan
framework baru. `database.py` tetap satu modul; yang ditambah hanya batas tanggung jawab.

`init_db` tetap `CREATE TABLE IF NOT EXISTS` + migrasi kolom manual. Alembic tidak dipakai:
tidak ada kebutuhan migrasi berganda, dan menambah dependensi tanpa masalah nyata bukan
perbaikan.

---

## Fase 4 — Docker & compose (belum)

- Dockerfile multi-stage, `python:3.11-slim` tetap, user non-root (`app`, uid 10001),
  tanpa `gcc` di layer akhir, `HEALTHCHECK` memanggil `/healthz`.
- Compose: `read_only: true` + `tmpfs: /tmp`, `cap_drop: [ALL]`, `security_opt:
  no-new-privileges`, logging `max-size: 10m`, `max-file: 3`, healthcheck.
- `network_mode: host` dilepas, ganti `ports: ["127.0.0.1:8080:8080"]` — API tidak lagi
  mendengarkan di IP publik VPS.
- Secret hanya dari `environment`/`env_file: .env` di compose; tidak ada file yang
  menimpa environment.

### Checklist sebelum melepas host networking

Bot di VPS (Singapura), device di rumah. Container harus bisa mencapai IP LAN device:

1. IP device statis (sudah: data lengkap, tidak pakai discovery).
2. Rute VPS → subnet device lewat WireGuard `wg0` ada di tabel routing host.
3. `AllowedIPs` di kedua sisi WireGuard mencakup subnet device.
4. Firewall OPNsense mengizinkan wg1 → subnet device, port TCP 6668.
5. Subnet device tidak bertabrakan dengan subnet Docker (`172.17.0.0/16`,
   `172.18.0.0/16`, …). Kalau bertabrakan, pakai `--network` dengan subnet lain.

Uji: `docker compose exec tuyabot python -c "import socket;socket.create_connection(('<ip-device>',6668),3);print('ok')"`

---

## Fase 5 — UI (belum)

Struktur:
- `static/index.html` (1643 baris) dipecah: `index.html`, `css/app.css`, `js/app.js` (ES module).
- `onclick=` inline dihapus → `addEventListener`.
- `innerHTML` berisi data API → `textContent` / helper `el()`; hanya template statis yang
  boleh pakai `innerHTML`.

Tampilan:
- palette dark sekarang dipertahankan; hierarki dirapikan (header tipis, strip status,
  kartu device dominan, tabel jadi sekunder).
- tab Power: grafik konsumsi (uPlot ±40 KB, di-vendor, tanpa CDN) + rentang 1 jam / 24 jam / 7 hari.
- keadaan: skeleton loading, empty state, banner error yang bisa ditutup, konfirmasi untuk
  aksi mematikan air.
- responsif sampai 360 px, `aria-live` untuk perubahan status, focus ring terlihat,
  `prefers-reduced-motion`.

Real-time: `GET /api/stream` (SSE) mengirim status device + daya; dashboard berhenti polling.

Auth: `POST /api/login` → session cookie `HttpOnly; SameSite=Strict` (ditandatangani,
tanpa database sesi). API key tetap diterima lewat header untuk skrip. Ini menggantikan
API key di `localStorage`, yang berarti XSS di dashboard tidak lagi otomatis membocorkan
kredensial.

---

## Fase 6 — ops (belum)

- Uptime Kuma → `http://127.0.0.1:8080/healthz` (tanpa auth).
- README ditulis ulang: arsitektur, env var, deploy, rollback, cara menambah device baru
  (termasuk kapan `scan_devices.py` masih dipakai).
- Jadwal backup SQLite harian + retensi 14 hari.
