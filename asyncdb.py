"""Menjalankan panggilan database sinkron di luar event loop.

Driver database yang dipakai bersifat blocking. Kalau dipanggil langsung dari `async def`,
seluruh event loop (bot polling + REST API + scheduler) berhenti sampai query selesai.
Semua akses database dari kode async harus lewat `run_db`.

Executor terpisah dari executor Tuya supaya query lambat tidak pernah memakan slot
yang dipakai untuk komunikasi perangkat (dan sebaliknya).
"""

import asyncio
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)

DB_CALL_TIMEOUT_SECONDS = float(os.getenv("DB_CALL_TIMEOUT_SECONDS", "15"))
DB_THREADS = max(1, int(os.getenv("DB_THREADS", "4")))

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=DB_THREADS, thread_name_prefix="db")
    return _executor


async def run_db(
    fn: Callable[..., Any],
    *args: Any,
    timeout: float | None = None,
    **kwargs: Any,
) -> Any:
    """Jalankan `fn(*args, **kwargs)` di thread, batasi waktu tunggunya.

    Timeout membatasi *pemanggil*, bukan query: thread yang sudah jalan tetap
    menyelesaikan query-nya sendiri (koneksi database tidak bisa dibatalkan dari sini).
    """
    loop = asyncio.get_running_loop()
    limit = DB_CALL_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_get_executor(), partial(fn, *args, **kwargs)),
            timeout=limit,
        )
    except TimeoutError:
        logger.error(
            "[DATABASE] %s melewati batas %.1fs (query tetap berjalan di thread)",
            getattr(fn, "__name__", repr(fn)),
            limit,
        )
        raise


def shutdown(wait: bool = True) -> None:
    """Hentikan executor saat aplikasi berhenti."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
