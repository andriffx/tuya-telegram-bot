"""Cache status perangkat dengan TTL dan single-flight.

Tujuan:
1. Dashboard, watchdog, power monitor, dan bot tidak lagi mem-polling perangkat
   yang sama secara terpisah. Satu pembacaan dipakai bersama selama TTL.
2. Single-flight: walau sepuluh request datang bersamaan saat cache kedaluwarsa,
   perangkat hanya dihubungi sekali.

Hasil gagal juga di-cache sebentar (ERROR_TTL) supaya perangkat yang sedang mati
tidak dibanjiri retry oleh banyak pembaca.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..devices.service import run_tuya, tuya

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = float(os.getenv("STATE_CACHE_TTL_SECONDS", "5"))
ERROR_TTL_SECONDS = float(os.getenv("STATE_ERROR_TTL_SECONDS", "2"))

Key = tuple[str, str]


class DeviceStateCache:
    """Cache sederhana: satu entri per (device, jenis data)."""

    def __init__(
        self,
        ttl_seconds: float = STATE_TTL_SECONDS,
        error_ttl_seconds: float = ERROR_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._error_ttl = error_ttl_seconds
        self._clock = clock
        self._entries: dict[Key, tuple[float, dict[str, Any]]] = {}
        self._locks: dict[Key, asyncio.Lock] = {}

    def _lock_for(self, key: Key) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _fresh(self, key: Key, now: float) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stamp, value = entry
        ttl = self._ttl if value.get("success") else self._error_ttl
        if now - stamp <= ttl:
            return value
        return None

    async def get(
        self,
        key: Key,
        loader: Callable[[], Awaitable[dict[str, Any]]],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Ambil dari cache; panggil `loader` hanya bila basi atau `force=True`."""
        now = self._clock()
        if not force:
            cached = self._fresh(key, now)
            if cached is not None:
                return cached

        async with self._lock_for(key):
            # Pemanggil lain mungkin sudah mengisi cache saat kita menunggu lock.
            now = self._clock()
            if not force:
                cached = self._fresh(key, now)
                if cached is not None:
                    return cached

            result = await loader()
            if isinstance(result, dict):
                self._entries[key] = (self._clock(), result)
            return result

    def age(self, key: Key) -> float | None:
        """Umur data di cache dalam detik, atau None kalau belum ada."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        return self._clock() - entry[0]

    def last_result(self, key: Key) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        return entry[1] if entry else None

    def invalidate(self, device_name: str | None = None) -> None:
        if device_name is None:
            self._entries.clear()
            return
        for key in [k for k in self._entries if k[0] == device_name]:
            self._entries.pop(key, None)

    def snapshot(self) -> dict[str, Any]:
        """Ringkasan isi cache untuk endpoint readiness."""
        return {
            f"{device}.{kind}": {
                "age_s": round(self.age((device, kind)) or 0, 2),
                "success": bool(value.get("success")),
            }
            for (device, kind), (_, value) in self._entries.items()
        }


cache = DeviceStateCache()


async def get_status(device_name: str, *, force: bool = False) -> dict[str, Any]:
    """Status DPS perangkat, lewat cache."""
    return await cache.get(
        (device_name, "status"),
        lambda: run_tuya(tuya.get_status, device_name),
        force=force,
    )


async def get_power(device_name: str = "air", *, force: bool = False) -> dict[str, Any]:
    """Data daya smart plug, lewat cache."""
    return await cache.get(
        (device_name, "power"),
        lambda: run_tuya(tuya.get_power_info, device_name),
        force=force,
    )


async def warm(device_names: list[str] | None = None) -> None:
    """Isi cache untuk semua perangkat (dipanggil scheduler)."""
    names = device_names or list(getattr(tuya, "devices", {}).keys())
    for name in names:
        await get_status(name)
        if name == "air":
            await get_power(name)
