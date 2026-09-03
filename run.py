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

from api.app import app as fastapi_app
from bot import build_application
from config import validate_config, POWER_LOG_INTERVAL_MINUTES
from database import init_db, log_power
from device_service import run_tuya, tuya

logger = logging.getLogger(__name__)

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))


async def record_power_snapshot() -> bool:
    """Membaca snapshot daya Tuya untuk smart plug air dan menyimpannya ke MySQL."""
    try:
        res = await run_tuya(tuya.get_power_info, "air")
        if not res.get("success"):
            logger.warning("[TUYA WARNING] Gagal membaca konsumsi daya plug air: %s", res.get("message"))
            return False

        raw = res.get("raw", {})
        # DP 1 adalah relay status (on/off) untuk plug air
        switch_state = bool(raw.get("1", False)) if isinstance(raw, dict) and "1" in raw else None

        ok = log_power(
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


async def power_monitor_loop():
    """Loop background untuk mencatat konsumsi daya secara periodik."""
    interval_secs = max(60, POWER_LOG_INTERVAL_MINUTES * 60)
    logger.info("Periodic power monitor dimulai (interval: %d menit)", POWER_LOG_INTERVAL_MINUTES)

    # Jeda awal 10 detik agar bot dan API siap sepenuhnya sebelum polling pertama
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        return

    while True:
        try:
            await record_power_snapshot()
        except asyncio.CancelledError:
            logger.info("Power monitor worker dibatalkan (shutdown).")
            break
        except Exception as e:
            logger.error("Error pada siklus power monitor worker: %s", e)

        try:
            await asyncio.sleep(interval_secs)
        except asyncio.CancelledError:
            logger.info("Power monitor worker dibatalkan (shutdown).")
            break


async def run_all():
    if not validate_config():
        logger.error("Konfigurasi tidak lengkap.")
        sys.exit(1)

    # Inisialisasi database MySQL eksternal dan migrasi jika diperlukan
    db_ok = init_db(migrate_json=True)
    if not db_ok:
        logger.critical(
            "[DATABASE CRITICAL] Inisialisasi MySQL eksternal gagal. Bot tetap berjalan dengan keterbatasan koneksi database."
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
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot Telegram aktif")
        logger.info("Dashboard API: http://%s:%s/", API_HOST, API_PORT)

        # Jalankan background periodic power monitor
        power_task = asyncio.create_task(power_monitor_loop())

        try:
            await server.serve()
        finally:
            power_task.cancel()
            try:
                await power_task
            except asyncio.CancelledError:
                pass

            await application.updater.stop()
            await application.stop()
            await application.shutdown()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
