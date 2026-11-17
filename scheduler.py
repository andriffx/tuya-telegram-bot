"""Scheduler tunggal untuk semua pekerjaan periodik.

Menggantikan beberapa `while True` terpisah (power monitor, housekeeping, dan
nanti cache warmer) dengan satu loop. Manfaatnya:

- satu tempat untuk melihat/menambah pekerjaan berkala,
- urutan eksekusi bisa ditebak (job yang due dijalankan berurutan, tidak saling
  menabrak koneksi perangkat),
- shutdown bersih: satu task dibatalkan, semua job berhenti.

Job dijalankan berurutan. Karena semuanya ringan dan sudah dibatasi timeout di
`device_service.run_tuya` / `asyncdb.run_db`, ini cukup. Kalau nanti ada job berat,
pecah ke task terpisah dengan `asyncio.create_task` di dalam fungsinya.
"""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Job:
    name: str
    interval: float
    func: Callable[[], Awaitable[Any] | Any]
    initial_delay: float = 0.0
    next_run: float = 0.0
    runs: int = 0
    failures: int = 0


class Scheduler:
    """Loop tunggal berbasis interval, tanpa dependensi eksternal."""

    def __init__(self) -> None:
        self._jobs: list[Job] = []
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def jobs(self) -> list[Job]:
        return list(self._jobs)

    def add_job(
        self,
        name: str,
        interval: float,
        func: Callable[[], Awaitable[Any] | Any],
        initial_delay: float = 0.0,
    ) -> Job:
        if interval <= 0:
            raise ValueError(f"interval job '{name}' harus > 0")
        if any(job.name == name for job in self._jobs):
            raise ValueError(f"job '{name}' sudah terdaftar")
        job = Job(name=name, interval=float(interval), func=func, initial_delay=float(initial_delay))
        self._jobs.append(job)
        return job

    def start(self) -> asyncio.Task[None]:
        """Mulai scheduler sebagai task di event loop yang sedang berjalan."""
        loop = asyncio.get_running_loop()
        now = loop.time()
        for job in self._jobs:
            job.next_run = now + job.initial_delay
        self._stop.clear()
        self._task = loop.create_task(self._main(), name="scheduler")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def run_due(self) -> None:
        """Jalankan semua job yang sudah jatuh tempo (dipakai juga oleh test)."""
        loop = asyncio.get_running_loop()
        now = loop.time()
        for job in [j for j in self._jobs if j.next_run <= now]:
            await self._execute(job)
            job.next_run = loop.time() + job.interval

    async def _execute(self, job: Job) -> None:
        try:
            result = job.func()
            if inspect.isawaitable(result):
                await result
            job.runs += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            job.failures += 1
            logger.exception("[SCHEDULER] Job '%s' gagal", job.name)

    async def _main(self) -> None:
        logger.info(
            "Scheduler aktif: %s",
            ", ".join(f"{j.name}/{j.interval:g}s" for j in self._jobs) or "(tanpa job)",
        )
        loop = asyncio.get_running_loop()
        try:
            while not self._stop.is_set():
                await self.run_due()
                sleep_for = min((job.next_run for job in self._jobs), default=loop.time() + 60) - loop.time()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=max(0.05, sleep_for))
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.info("Scheduler dibatalkan (shutdown).")
            raise
