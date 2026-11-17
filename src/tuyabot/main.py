"""
Entry point — jalankan bot Telegram + REST API dashboard bersamaan.
Satu proses = satu lock Tuya (hindari race condition).
"""

import asyncio
import logging
import os
import sys

import uvicorn
from telegram import Update

from .config import (
    BACKUP_DIR,
    BACKUP_INTERVAL_HOURS,
    BACKUP_RETENTION_DAYS,
    POWER_LOG_INTERVAL_MINUTES,
    validate_config,
)
from .devices.service import run_tuya, tuya
from .devices.service import shutdown as device_shutdown
from .infra.asyncdb import run_db
from .infra.asyncdb import shutdown as asyncdb_shutdown
from .infra.scheduler import Scheduler
from .infra.state_cache import warm as warm_state_cache
from .storage import sqlite_store as database
from .telegram.handlers import build_application
from .web.app import app as fastapi_app

logger = logging.getLogger(__name__)

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))
# Seberapa sering cache status perangkat dihangatkan (detik).
STATE_WARM_INTERVAL_SECONDS = max(15, int(os.getenv("STATE_WARM_INTERVAL_SECONDS", "60")))
HOUSEKEEPING_INTERVAL_HOURS = max(1, int(os.getenv("HOUSEKEEPING_INTERVAL_HOURS", "24")))


async def record_power_snapshot() -> bool:
    """Membaca snapshot daya Tuya untuk smart plug air dan menyimpannya ke database."""
    try:
        res = await run_tuya(tuya.get_power_info, "air")
        if not res.get("success"):
            logger.warning("[TUYA WARNING] Gagal membaca konsumsi daya plug air: %s", res.get("message"))
            return False

        raw = res.get("raw", {})
        # DP 1 adalah relay status (on/off) untuk plug air
        switch_state = bool(raw.get("1", False)) if isinstance(raw, dict) and "1" in raw else None

        ok = await run_db(
            database.log_power,
            device_name="air",
            power_w=float(res.get("power_w", 0)),
            voltage_v=float(res.get("voltage_v", 0)),
            current_a=float(res.get("current_a", 0)),
            switch_state=switch_state,
            source="periodic",
        )
        if ok:
            logger.info(
                "Periodic power snapshot tercatat: %.1fW, %.1fV, %.2fA (switch=%s)",
                float(res.get("power_w", 0)),
                float(res.get("voltage_v", 0)),
                float(res.get("current_a", 0)),
                switch_state,
            )
        return ok
    except Exception as e:
        logger.error("[DATABASE ERROR] Gagal menjalankan periodic power snapshot: %s", e)
        return False


async def run_housekeeping() -> dict:
    """Bersihkan log lawas; dipanggil scheduler (bukan loop sendiri)."""
    logger.info("Menjalankan periodic database housekeeping...")
    result = await run_db(database.cleanup_old_logs)
    logger.info("Housekeeping selesai: %s", result)
    return result


async def warm_cache() -> None:
    """Isi cache status perangkat supaya dashboard tidak memicu polling sendiri."""
    await warm_state_cache()


async def run_backup() -> dict:
    """Salinan SQLite (VACUUM INTO) + buang salinan lebih tua dari retensi."""
    result = await run_db(database.backup_to, BACKUP_DIR, BACKUP_RETENTION_DAYS)
    logger.info("[BACKUP] Selesai: %s", result["path"])
    return result


def build_scheduler() -> Scheduler:
    """Satu scheduler untuk semua pekerjaan berkala.

    Dulu ada dua loop terpisah (power monitor dan housekeeping) yang masing-masing
    memegang `asyncio.sleep` sendiri. Sekarang semuanya di satu tempat, berurutan,
    dan berhenti bersama saat shutdown.
    """
    scheduler = Scheduler()
    scheduler.add_job(
        "cache-warm",
        STATE_WARM_INTERVAL_SECONDS,
        warm_cache,
        initial_delay=5,
    )
    scheduler.add_job(
        "power-snapshot",
        max(60, POWER_LOG_INTERVAL_MINUTES * 60),
        record_power_snapshot,
        initial_delay=20,
    )
    scheduler.add_job(
        "housekeeping",
        HOUSEKEEPING_INTERVAL_HOURS * 3600,
        run_housekeeping,
        initial_delay=HOUSEKEEPING_INTERVAL_HOURS * 3600,
    )
    scheduler.add_job(
        "backup",
        BACKUP_INTERVAL_HOURS * 3600,
        run_backup,
        # Backup pertama 15 menit setelah start, bukan menunggu 24 jam.
        initial_delay=900,
    )
    return scheduler


async def run_all():
    if not validate_config():
        logger.error("Konfigurasi tidak lengkap.")
        sys.exit(1)

    # Inisialisasi database SQLite dan migrasi jika diperlukan
    db_ok = database.init_db(migrate_json=True)
    if not db_ok:
        logger.critical(
            "[DATABASE CRITICAL] Inisialisasi database gagal. Bot tetap berjalan dengan keterbatasan penyimpanan log."
        )

    application = build_application()

    config = uvicorn.Config(
        fastapi_app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async with application:
        await application.initialize()
        await application.start()
        def polling_error_callback(exc):
            application.create_task(application.process_error(error=exc, update=None))

        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            timeout=20,
            poll_interval=0.0,
            drop_pending_updates=True,
            error_callback=polling_error_callback,
        )
        logger.info("Bot Telegram aktif")
        logger.info("Dashboard API: http://%s:%s/", API_HOST, API_PORT)

        # Satu scheduler: cache warmer, power snapshot, housekeeping
        scheduler = build_scheduler()
        scheduler.start()

        try:
            await server.serve()
        finally:
            await scheduler.stop()

            await application.updater.stop()
            await application.stop()
            await application.shutdown()

            asyncdb_shutdown()
            device_shutdown()



def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
