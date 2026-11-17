"""
Shared device layer — dipakai bot Telegram, REST API dashboard, dan scheduler.
Satu instance TuyaDeviceController agar lock I/O per perangkat konsisten.
"""

import asyncio
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from .local import TuyaDeviceController

logger = logging.getLogger(__name__)

TUYA_CALL_TIMEOUT_SECONDS = float(os.getenv("TUYA_CALL_TIMEOUT_SECONDS", "25"))
TUYA_THREADS = max(1, int(os.getenv("TUYA_THREADS", "4")))

tuya = TuyaDeviceController()
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=TUYA_THREADS, thread_name_prefix="tuya")
    return _executor


async def run_tuya(
    fn: Callable[..., dict[str, Any]],
    *args: Any,
    timeout: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Jalankan operasi Tuya blocking di thread terpisah, dengan batas waktu.

    Timeout membatasi pemanggil. Kalau habis, hasilnya `success=False` sehingga bot
    atau dashboard tidak ikut menggantung menunggu socket Tuya. Thread yang sudah
    berjalan tetap menyelesaikan percobaannya sendiri — karena itu batas ini dibuat
    lebih longgar daripada socket timeout tinytuya (4s x 2 retry).
    """
    loop = asyncio.get_running_loop()
    limit = TUYA_CALL_TIMEOUT_SECONDS if timeout is None else timeout
    future = loop.run_in_executor(_get_executor(), partial(fn, *args, **kwargs))
    try:
        return await asyncio.wait_for(future, timeout=limit)
    except TimeoutError:
        logger.warning(
            "[TUYA] %s melewati batas %.1fs",
            getattr(fn, "__name__", repr(fn)),
            limit,
        )
        return {"success": False, "message": f"Timeout {limit:.0f}s saat menghubungi perangkat"}


def shutdown(wait: bool = True) -> None:
    """Hentikan executor Tuya saat aplikasi berhenti."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
