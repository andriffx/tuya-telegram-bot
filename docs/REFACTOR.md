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
| 2 | Event loop, scheduler, timeout, health | **selesai** |
| 2b | MySQL → SQLite + migrasi data | **selesai** |
| 3 | Struktur modular (`src/tuyabot/`) | **selesai** |
| 4 | Dockerfile & compose produksi | **selesai** |
| 5 | UI | **selesai** |
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

## Fase 2 — selesai

### Hasil implementasi

| File baru | Isi |
|---|---|
| `asyncdb.py` | `run_db()` — query MySQL dijalankan di executor sendiri (4 thread), batas waktu 15s, error tetap dilempar ke pemanggil |
| `state_cache.py` | cache `(device, jenis)` dengan TTL 5s, TTL kegagalan 2s, single-flight per key, `invalidate()` dipanggil setiap habis kontrol |
| `scheduler.py` | satu loop interval: `cache-warm` 60s, `power-snapshot` 5m, `housekeeping` 24h (tidak jalan saat startup) |
| `tests/test_asyncdb.py`, `tests/test_state_cache.py`, `tests/test_scheduler.py`, `tests/test_api_health.py`, `tests/test_rate_limiter.py` | 29 test baru |

Perubahan pada file lama:

- `device_service.run_tuya` — `asyncio.wait_for` dengan `TUYA_CALL_TIMEOUT_SECONDS` (25s),
  executor 2 → 4 thread. Timeout mengembalikan `{"success": False, ...}`, bukan exception,
  supaya bot dan dashboard tidak menggantung.
- `tuya_controller` — satu `threading.Lock` global diganti lock per perangkat. Kontrol air dan
  lampu tidak lagi saling menunggu; I/O ke perangkat yang sama tetap diserialkan.
- `bot.py` — `_log_control_event`, `_execute_air_auto_off` memakai `run_db`; status/power
  lewat cache (`get_status`/`get_power`); sampling watchdog memakai `force=True` karena
  butuh nilai nyata, bukan cache; cache di-invalidasi setelah setiap kontrol.
- `api/routes.py` — semua endpoint `/db/*` memakai `run_db`; status & daya lewat cache;
  kontrol meng-invalidasi cache; `/api/health` sekarang benar-benar membaca kondisi
  (`ok` / `degraded` / `down`) alih-alih selalu `ok`.
- `api/app.py` — `GET /healthz` tanpa autentikasi dan tanpa menyentuh database.
- `rate_limiter.py` — bucket user yang tidak aktif dibuang (maksimal sekali per 2 window).
- `run.py` — dua loop (`power_monitor_loop`, `housekeeping_loop`) dihapus, diganti
  `build_scheduler()` + `Scheduler`. Shutdown menutup scheduler dan kedua executor.

Dampak yang bisa dirasakan:

- Bot tidak berhenti menjawab saat dashboard memuat riwayat log (query pindah ke thread).
- Membuka dashboard dari beberapa tab/perangkat tidak lagi memicu pembacaan Tuya berlipat;
  dalam 5 detik hanya satu pembacaan per jenis data.
- Status yang dibaca bot/dashboard bisa tertinggal maksimal `STATE_CACHE_TTL_SECONDS` (5s),
  dan langsung dibuang setelah kontrol apa pun — termasuk auto-off watchdog.
- Satu-satunya jalur yang tetap menghubungi perangkat setiap kali adalah perintah kontrol
  dan sampling daya watchdog (`force=True`), karena keduanya butuh kepastian.

Verifikasi: `ruff check .` bersih, `pytest -q` **64 passed** (baseline Fase 1: 35).

### Rencana awal (untuk referensi)

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

## Fase 2b — MySQL → SQLite (selesai)

### Hasil implementasi

- `database.py` ditulis ulang dengan `sqlite3` (stdlib). API publik tidak berubah:
  `init_db`, `ping`, `get_user_role`, `set_user_role`, `log_activity`, `log_power`,
  `log_app_error`, `get_recent_*`, `get_db_stats`, `cleanup_old_logs`.
- Koneksi per thread (`threading.local`), karena `asyncio.to_thread` memakai beberapa thread
  dan SQLite tidak boleh berbagi satu koneksi antar thread.
- Pragma: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout`, `foreign_keys=ON`.
- Terjemahan SQL: `ON DUPLICATE KEY UPDATE` → `ON CONFLICT(user_id) DO UPDATE` (dengan
  `COALESCE` yang sama untuk `added_by`), `INSERT IGNORE` → `INSERT OR IGNORE`,
  `NOW() - INTERVAL n DAY` → `datetime('now','localtime', ?)`, `LIMIT %s` → `LIMIT ?`.
- `get_db_stats()` tetap mengirim `host`/`database` (dipakai dashboard) dan menambah
  `engine`, `path`, `size_bytes`.
- `scripts/migrate_mysql_to_sqlite.py`: menyalin 5 tabel, memverifikasi jumlah baris
  sumber vs tujuan, gagal (exit 1) bila ada yang beda, dan menolak menimpa database yang
  sudah berisi data tanpa `--force`.
- `docker-compose.yml`: tambah bind-mount `./data:/app/data`.
- `mysql-connector-python` keluar dari image produksi; hanya ada di `requirements-dev.txt`
  untuk skrip migrasi.
- `tests/test_database.py` ditulis ulang: sekarang memakai file SQLite sementara yang
  sungguhan, bukan mock koneksi. Semua SQL dieksekusi, termasuk jalur housekeeping.
- `tests/test_migrate_script.py`: menjaga daftar kolom di skrip migrasi tetap sama dengan
  skema di `database.py`.

### Langkah deploy (sekali, ±2 menit downtime)

```
# di host, dari direktori compose
mysqldump -u "$MYSQL_USER" -p "$MYSQL_DATABASE" > /root/tuyabot-pre-sqlite.sql   # rollback
mkdir -p data
docker compose build && docker compose up -d
docker exec -u app tuya-telegram-bot python scripts/migrate_mysql_to_sqlite.py
```

Setelah yakin, `MYSQL_*` boleh dihapus dari `.env` dan service MySQL lama boleh dimatikan.
Rollback: hentikan bot, pulihkan dump ke MySQL, jalankan image versi lama.

### Rencana awal (referensi)

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

Yang dibawa default: `bot_users` + `bot_air_recipients` (data akses). Log telemetri lama
tidak ikut — tetap ada di file dump, dan kalau perlu bisa dibawa dengan `--include-logs`.

1. `mysqldump` di host untuk rollback (bot boleh tetap jalan)
2. `docker compose build && docker compose up -d`
3. `docker exec -u app tuya-telegram-bot python scripts/migrate_mysql_to_sqlite.py`
   — dijalankan di container yang sama, tanpa image terpisah dan tanpa downtime.
   `-u app` wajib agar file DB tetap milik uid 10001
4. Verifikasi: bandingkan jumlah baris sumber vs tujuan yang dicetak skrip, plus jumlah user
   dan penerima notifikasi di akhir keluaran.
5. `docker compose up -d`, cek `/api/db/stats`, `/status` di bot, dan tab Pengguna di dashboard.
6. Simpan `mysqldump` sebelum langkah 3 — rollback = restore dump + jalankan image lama.

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

## Fase 3 — struktur modular (selesai)

### Hasil implementasi

```
src/tuyabot/
├── main.py                 # dulu run.py
├── config.py
├── infra/                  # asyncdb.py, scheduler.py, state_cache.py
├── devices/                # local.py (tinytuya), service.py (executor+timeout)
├── storage/                # sqlite_store.py (dulu database.py)
├── access/                 # roles.py (dulu auth_manager), rate_limit.py (dulu rate_limiter)
├── telegram/               # handlers.py (dulu bot.py)
├── web/                    # app.py, routes.py, deps.py, schemas.py
└── static/index.html
scripts/                    # scan_devices.py, test_connection.py, migrate_mysql_to_sqlite.py
```

- Semua perpindahan memakai `git mv`, jadi `git log --follow` tetap melacak riwayat tiap file.
- Import internal sekarang relatif (`from ..devices.service import run_tuya`), bukan nama modul
  datar. Nama modul lama tidak lagi bisa diimpor — ini disengaja, supaya tidak ada dua jalan.
- Entry point: `python -m tuyabot.main` (Docker: `ENV PYTHONPATH=/app/src` + `CMD ["python","-m","tuyabot.main"]`).
  `pytest` memakai `pythonpath = ["src", "."]`.
- `api/` dihapus sebagai paket, isinya menjadi `web/`.
- Test mengimpor modul dengan alias (`import tuyabot.telegram.handlers as bot`) supaya
  pembacaan test tetap sama, dan semua target `patch(...)` diperbarui ke path paket baru.
  Dua test yang memeriksa teks sumber (`inspect.getsource`) saya ubah menjadi pemeriksaan
  identitas fungsi — lebih tahan refactor dan tetap menangkap bug yang sama.

### Yang sengaja belum dipecah

`telegram/handlers.py` masih satu modul (~1.560 baris) berisi command handler, callback,
menu, dan watchdog air. Memecahnya per fitur adalah pekerjaan terpisah dengan risiko
tersendiri (banyak state modul global: `_active_air_watchdog`, keyboard, rate limit), dan
tidak memberi perbaikan perilaku apa pun. Urutan yang saya sarankan kalau nanti dikerjakan:
`keyboards.py` → `watchdog.py` → `handlers/devices.py` → `handlers/admin.py` → `handlers/menu.py`,
dengan test tetap hijau setelah tiap langkah.

### Verifikasi

- `ruff check .` bersih, `pytest -q` **75 passed** (jumlah test sama seperti sebelum fase ini —
  refactor tidak boleh mengubah cakupan).
- Smoke test di proses baru: `healthz 200 {'status': 'ok'}`, dashboard `/` 200 (55 KB HTML),
  `/static/index.html` 200 — membuktikan `STATIC_DIR` tetap benar setelah static ikut pindah.

---

## Fase 4 — Docker & compose (selesai)

### Hasil implementasi

`Dockerfile` dua stage:

- **builder** (`python:3.11-slim` + `build-essential`): install dependensi ke `/opt/venv`.
- **runtime** (`python:3.11-slim`, tanpa compiler): copy venv + `src/` + `scripts/`,
  `PYTHONPATH=/app/src`, user `app` (uid/gid 10001), `HEALTHCHECK` memanggil `/healthz`,
  `CMD ["python","-m","tuyabot.main"]`.

Kepemilikan volume tidak lagi jadi urusan operator. `entrypoint.sh` berjalan sebagai root
selama beberapa milidetik, memperbaiki pemilik `logs/`, `data/`, `backup/` ke uid 10001
(hanya kalau memang perlu), lalu `exec setpriv --reuid=10001 --regid=10001` sehingga proses
Python tetap non-root dan `SIGTERM` tetap sampai ke aplikasi. Itu sebabnya image tidak memakai
`USER app` dan compose memberi tiga capability minimum (`CHOWN`, `SETUID`, `SETGID`);
`cap_drop: ALL` tetap berlaku untuk sisanya.

`docker-compose.yml`:

| Setelan | Nilai | Alasan |
|---|---|---|
| `API_HOST` | dari `.env` (default `127.0.0.1`) | dengan host networking, API tidak boleh mendengar di IP publik |
| `SQLITE_PATH` | dari `.env` (`data/tuyabot.db` relatif ke `/app`) | file database ada di volume, bukan di layer image |
| `read_only` | `true` | container tidak bisa menulis ke filesystemnya sendiri |
| `tmpfs` | `/tmp` | satu-satunya area tulis sementara |
| `cap_drop` | `ALL` | tidak ada capability Linux yang dibutuhkan |
| `cap_add` | `CHOWN`, `SETUID`, `SETGID` | hanya untuk entrypoint: perbaiki kepemilikan volume lalu turun ke uid 10001 |
| `security_opt` | `no-new-privileges` | cegah eskalasi hak akses |
| `logging` | `json-file`, 10m × 3 | log container tidak menelan disk VPS |
| `volumes` | `logs/`, `data/`, `backup/` | persist log, database, hasil backup |
| `stop_grace_period` | `15s` | beri waktu shutdown scheduler + tutup SQLite |

Keputusan yang **tidak** diambil: melepas `network_mode: host`. Bot berjalan di VPS dan
mencapai perangkat lewat WireGuard; host networking memastikan rute `wg0` dipakai tanpa NAT
tambahan. Risiko "API terbuka ke internet" ditutup dengan `API_HOST=127.0.0.1`, bukan dengan
memindahkan network mode (yang berisiko memutus kontrol perangkat tanpa bisa diuji dari sini).
Kalau nanti mau bridge network, checklist verifikasi ada di bagian "Rencana awal" di bawah.

### Konfigurasi hanya dari `.env`

Compose **tidak** memuat nilai konfigurasi: blok `environment:` dihapus, semua variabel (TZ,
API_HOST, API_PORT, SQLITE_PATH, token, kredensial) datang dari `.env` lewat `env_file`.
Supaya tetap aman kalau `.env` lupa diisi, default di kode untuk `API_HOST` adalah `127.0.0.1`
(bukan `0.0.0.0` seperti sebelumnya).

### Guard regresi

`tests/test_deploy_config.py` mengunci: compose tidak punya blok `environment`, `.env.example`
mendokumentasikan `API_HOST`/`API_PORT`/`SQLITE_PATH`/`TZ`, default bind loopback,
`read_only`/`cap_drop`/`no-new-privileges`, ketiga volume ada, `HEALTHCHECK` membaca `API_HOST`,
`entrypoint` melakukan chown lalu `exec setpriv`, `build-essential` tidak bocor ke stage runtime,
`mysql-connector-python` ada di requirements runtime (agar migrasi bisa di-`exec`), dan runbook
tidak lagi menyuruh `docker run` image migrasi. Tanpa guard ini, satu perubahan
compose bisa membuka dashboard ke publik lagi tanpa ada yang gagal.

### Yang belum diverifikasi di sini

Image-nya belum benar-benar di-build di sesi ini — tidak ada Docker di mesin kerja ini.
Yang diverifikasi: sintaks YAML parse bersih, semua assert deploy lulus, aplikasi jalan lewat
`python -m tuyabot.main` dengan `PYTHONPATH=src` (healthz 200, dashboard 200). Build pertama
di VPS Anda adalah verifikasi terakhirnya.

---

## Rencana awal Fase 4 (referensi)

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

## Fase 5 — UI (selesai)

### Struktur baru

```
src/tuyabot/static/
├── index.html        # markup saja (~250 baris, dari 1.643 baris campur)
├── css/app.css       # seluruh gaya, pakai custom properties
└── js/
    ├── api.js        # fetch wrapper + error handling + login/logout
    ├── chart.js      # grafik canvas, tanpa library
    └── app.js        # state, render, SSE, aksi perangkat
```

### Perubahan yang berdampak, bukan cuma kosmetik

| Sebelum | Sesudah | Alasan |
|---|---|---|
| API key di `localStorage` | login sekali → cookie `HttpOnly; SameSite=Strict` (HMAC, tanpa tabel sesi) | XSS di dashboard tidak lagi otomatis membocorkan kredensial |
| Polling 30 detik per tab | SSE `/api/stream`, snapshot tiap 3 detik | status bergerak tanpa klik, dan SSE **tidak** memicu I/O perangkat (baca cache) |
| `innerHTML` diisi data API | `textContent` lewat helper `el()` | tidak ada jalur injeksi HTML dari data |
| `onclick=` inline | `addEventListener` di satu tempat | tidak ada kode JS di markup |
| 1 file 56 KB | HTML + CSS + 3 modul JS | bisa dirawat dan di-cache terpisah |
| Grafik tidak ada | grafik canvas (area + garis, penanda puncak, rentang 1j/24h/7h) | riwayat daya akhirnya terbaca sebagai tren |

Tambahan UX: konfirmasi khusus sebelum mematikan pompa air, toast hasil aksi, empty state
per tabel, `aria-live` pada strip ringkasan, tombol bisa dioperasikan keyboard, focus ring
terlihat, `prefers-reduced-motion`, dan layout 390 px dengan lima tab tanpa scroll.

### Endpoint baru

- `POST /api/login` `{api_key}` → set cookie sesi. `POST /api/logout` → hapus cookie.
  `GET /api/session` → `{authenticated: bool}` (tanpa auth) untuk memutuskan tampilan.
- `GET /api/stream` (SSE). Isinya: `{ts, devices:{<nama>:{online, switch_on, power_w,
  voltage_v, current_a, status_age_s, power_age_s}}}`. Butuh cookie sesi karena
  `EventSource` tidak bisa mengirim header.
- Autentikasi API tetap menerima `X-API-Key` untuk skrip/curl.

### Bug yang ketangkap saat verifikasi visual

Tiga hal ini tidak akan terlihat dari test unit, dan sudah diperbaiki:

1. `[hidden]` kalah oleh `display: grid` di kelas `.login`/`.app` → halaman login dan
   dashboard tampil bertumpuk. Diperbaiki dengan `[hidden] { display: none !important; }`.
2. Kartu "Database" di strip kosong sampai tab Sistem dibuka (datanya hanya diambil di
   `renderSystem`). Sekarang `loadDbStats()` dipanggil saat dashboard start.
3. Urutan baris memakai `ORDER BY id DESC` → salah untuk data hasil impor/migrasi yang
   id-nya tidak mengikuti waktu. Diubah ke `ORDER BY created_at DESC, id DESC`.

Selain itu, label waktu paling kanan di grafik terpotong (dirapatkan ke tepi), dan lima tab
tidak muat di 390 px (padding tab dikecilkan, jam disembunyikan di layar kecil).

### Verifikasi

- `ruff check .` bersih, `pytest -q` **101 passed** (sebelum fase ini 81).
- Test baru: `test_api_auth.py` (10), `test_api_stream.py` (3), `test_static_ui.py` (7).
  Guard statis memastikan: tidak ada `onclick=`, tidak ada `<style>` inline, tidak ada CDN,
  tidak ada `innerHTML`, tidak ada `localStorage`.
- Verifikasi visual nyata: aplikasi dijalankan dengan data demo di SQLite, dibuka di browser
  (desktop + emulasi 390 px), login, tab Daya, tab Sistem, lalu screenshot diperiksa.
  Itu yang menemukan tiga bug di atas.

---

## Fase 6 — Ops & dokumentasi (selesai)

### Backup otomatis

Job `backup` di scheduler (`BACKUP_INTERVAL_HOURS`, default 24 jam; jalan pertama 15 menit
setelah start) memanggil `storage.sqlite_store.backup_to()`:

- `VACUUM INTO backup/tuyabot-YYYY-MM-DD_HHMMSS.db` — konsisten tanpa menghentikan proses,
  tidak perlu menyentuh volume dari sisi host.
- Menghapus salinan lebih tua dari `BACKUP_RETENTION_DAYS` (default 14).
- `get_db_stats()` melaporkan `backup_dir`, `backup_count`, `last_backup`; dashboard
  menampilkannya di tab Sistem.

Alasannya dikerjakan di aplikasi, bukan cron host: tidak ada langkah deploy tambahan, ikut
berjalan di container yang sama, dan tidak bergantung pada zona waktu host.

### Monitoring

`/healthz` (tanpa auth, tanpa cek database) adalah target Uptime Kuma. `/api/health` tetap
ada untuk readiness yang lebih dalam (database + kesegaran cache) dan butuh autentikasi.
README memuat tabel setelan Uptime Kuma supaya tinggal diisi.

### Dokumentasi

README diperbarui: login & sesi, SSE, variabel env baru (cache, timeout, sesi, backup),
struktur paket, langkah deploy (termasuk entrypoint yang mengurus kepemilikan volume),
backup & restore, dan troubleshooting perangkat.

### Verifikasi

- `ruff check .` bersih, `pytest -q` **105 passed**.
- `tests/test_backup.py`: salinan bisa dibuka dan isinya sama (baris + nilai), retensi
  menghapus salinan 40 hari tapi mempertahankan yang masih dalam masa retensi, penulisan
  setelah backup tetap jalan, dan statistik melaporkan backup.
- `test_run_wiring.py`: job `backup` terdaftar dengan interval retensi benar dan
  `initial_delay=900` (bukan menunggu 24 jam).

### Yang menjadi tugas operator (bukan kode)

Membuat monitor di panel Uptime Kuma, dan memutuskan apakah dashboard akan diekspos lewat
reverse proxy. Keduanya ada di infrastruktur Anda, bukan di repo.

