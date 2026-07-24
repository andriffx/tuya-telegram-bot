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
from config import validate_config

logger = logging.getLogger(__name__)

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))


async def run_all():
    if not validate_config():
        logger.error("Konfigurasi tidak lengkap.")
        sys.exit(1)

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

        try:
            await server.serve()
        finally:
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
