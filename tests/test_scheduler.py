"""Test scheduler tunggal: interval, isolasi kegagalan, shutdown."""

import asyncio

import pytest

from tuyabot.infra.scheduler import Scheduler


@pytest.mark.asyncio
async def test_job_runs_repeatedly():
    scheduler = Scheduler()
    runs = []
    scheduler.add_job("tick", 0.02, lambda: runs.append(1), initial_delay=0)

    scheduler.start()
    await asyncio.sleep(0.13)
    await scheduler.stop()

    assert len(runs) >= 2


@pytest.mark.asyncio
async def test_failing_job_does_not_stop_other_jobs():
    scheduler = Scheduler()
    runs = []

    def boom():
        raise RuntimeError("device meledak")

    scheduler.add_job("boom", 0.02, boom, initial_delay=0)
    scheduler.add_job("ok", 0.02, lambda: runs.append(1), initial_delay=0)

    scheduler.start()
    await asyncio.sleep(0.13)
    await scheduler.stop()

    boom_job = next(j for j in scheduler.jobs if j.name == "boom")
    assert boom_job.failures >= 1
    assert runs, "job lain harus tetap jalan setelah job gagal"


@pytest.mark.asyncio
async def test_initial_delay_is_respected():
    scheduler = Scheduler()
    runs = []
    scheduler.add_job("later", 0.02, lambda: runs.append(1), initial_delay=10)

    scheduler.start()
    await asyncio.sleep(0.08)
    await scheduler.stop()

    assert runs == []


@pytest.mark.asyncio
async def test_stop_cancels_task():
    scheduler = Scheduler()
    scheduler.add_job("tick", 0.02, lambda: None, initial_delay=0)
    task = scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()
    assert task.done()


def test_rejects_bad_jobs():
    scheduler = Scheduler()
    with pytest.raises(ValueError):
        scheduler.add_job("bad", 0, lambda: None)
    scheduler.add_job("dup", 1, lambda: None)
    with pytest.raises(ValueError):
        scheduler.add_job("dup", 1, lambda: None)


@pytest.mark.asyncio
async def test_async_and_sync_jobs_both_supported():
    scheduler = Scheduler()
    seen = []

    async def async_job():
        seen.append("async")

    scheduler.add_job("a", 0.02, async_job, initial_delay=0)
    scheduler.add_job("b", 0.02, lambda: seen.append("sync"), initial_delay=0)

    scheduler.start()
    await asyncio.sleep(0.08)
    await scheduler.stop()

    assert "async" in seen
    assert "sync" in seen
