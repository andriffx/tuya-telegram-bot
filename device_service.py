"""
Shared device layer — dipakai bot Telegram dan REST API dashboard.
Satu instance TuyaDeviceController agar lock I/O konsisten.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from tuya_controller import TuyaDeviceController

tuya = TuyaDeviceController()
_executor = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tuya")
    return _executor


async def run_tuya(fn, *args, **kwargs):
    """Jalankan operasi Tuya blocking di thread terpisah."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _get_executor(),
        partial(fn, *args, **kwargs),
    )
