"""Test helper `run_db`: tidak memblokir event loop dan punya batas waktu."""

import asyncio
import time

import pytest

import tuyabot.infra.asyncdb as asyncdb
from tuyabot.infra.asyncdb import run_db


@pytest.mark.asyncio
async def test_slow_db_call_does_not_block_loop():
    """Query 150ms tidak boleh menghentikan ticker 20ms di loop yang sama."""
    ticks = []

    async def ticker():
        for _ in range(5):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    task = asyncio.create_task(ticker())
    started = time.monotonic()
    await run_db(time.sleep, 0.15)
    elapsed = await asyncio.to_thread(lambda: time.monotonic() - started)
    await task

    assert len(ticks) == 5, "ticker terhenti: query memblokir event loop"
    assert elapsed >= 0.15


@pytest.mark.asyncio
async def test_timeout_is_enforced():
    with pytest.raises(TimeoutError):
        await run_db(time.sleep, 0.4, timeout=0.05)


@pytest.mark.asyncio
async def test_returns_value_and_passes_kwargs():
    def add(a, *, b):
        return a + b

    assert await run_db(add, 2, b=3) == 5


@pytest.mark.asyncio
async def test_exception_propagates():
    def boom():
        raise RuntimeError("db mati")

    with pytest.raises(RuntimeError):
        await run_db(boom)


def test_timeout_configurable_by_env(monkeypatch):
    monkeypatch.setenv("DB_CALL_TIMEOUT_SECONDS", "3")
    import importlib

    importlib.reload(asyncdb)
    assert asyncdb.DB_CALL_TIMEOUT_SECONDS == 3.0
    importlib.reload(asyncdb)  # kembalikan ke default untuk test lain
