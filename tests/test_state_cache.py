"""Test cache status perangkat: TTL, single-flight, cache kegagalan."""

import asyncio

import pytest

import tuyabot.infra.state_cache as state_cache
from tuyabot.infra.state_cache import DeviceStateCache


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_single_flight_only_calls_device_once():
    clock = FakeClock()
    cache = DeviceStateCache(ttl_seconds=60, clock=clock)
    calls = []

    async def loader():
        calls.append(1)
        await asyncio.sleep(0.02)
        return {"success": True, "status": {"1": True}}

    results = await asyncio.gather(
        *(cache.get(("air", "status"), loader) for _ in range(10))
    )

    assert len(calls) == 1, f"perangkat dihubungi {len(calls)}x, seharusnya 1x"
    assert all(r["success"] for r in results)


@pytest.mark.asyncio
async def test_cache_hit_within_ttl_and_reload_after_expiry():
    clock = FakeClock()
    cache = DeviceStateCache(ttl_seconds=5, clock=clock)
    calls = []

    async def loader():
        calls.append(1)
        return {"success": True, "n": len(calls)}

    first = await cache.get(("lampu", "status"), loader)
    clock.advance(3)
    second = await cache.get(("lampu", "status"), loader)

    assert len(calls) == 1
    assert second is first

    clock.advance(3)  # total 6 detik > TTL 5 detik
    third = await cache.get(("lampu", "status"), loader)

    assert len(calls) == 2
    assert third["n"] == 2


@pytest.mark.asyncio
async def test_force_always_hits_device():
    clock = FakeClock()
    cache = DeviceStateCache(ttl_seconds=60, clock=clock)
    calls = []

    async def loader():
        calls.append(1)
        return {"success": True}

    await cache.get(("air", "power"), loader)
    await cache.get(("air", "power"), loader, force=True)
    await cache.get(("air", "power"), loader, force=True)

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_failure_cached_briefly_to_stop_hammering():
    clock = FakeClock()
    cache = DeviceStateCache(ttl_seconds=60, error_ttl_seconds=2, clock=clock)
    calls = []

    async def loader():
        calls.append(1)
        return {"success": False, "message": "offline"}

    await cache.get(("air", "status"), loader)
    clock.advance(1)
    await cache.get(("air", "status"), loader)
    assert len(calls) == 1, "kegagalan tidak boleh memicu retry bertubi-tubi"

    clock.advance(2)  # lewat error TTL
    await cache.get(("air", "status"), loader)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_wrappers_route_through_run_tuya(monkeypatch):
    calls = []

    async def fake_run_tuya(fn, *args, **kwargs):
        calls.append(getattr(fn, "__name__", str(fn)))
        return {"success": True, "status": {}, "power_w": 1.0}

    monkeypatch.setattr(state_cache, "run_tuya", fake_run_tuya)
    monkeypatch.setattr(state_cache, "cache", DeviceStateCache(ttl_seconds=60))

    await state_cache.get_status("lampu")
    await state_cache.get_status("lampu")
    await state_cache.get_power("air")

    assert calls == ["get_status", "get_power_info"]


def test_snapshot_reports_age_and_success():
    clock = FakeClock()
    cache = DeviceStateCache(ttl_seconds=60, clock=clock)

    async def run():
        async def loader():
            return {"success": True}

        await cache.get(("air", "status"), loader)
        clock.advance(4)
        snap = cache.snapshot()
        assert snap["air.status"]["success"] is True
        assert snap["air.status"]["age_s"] == pytest.approx(4.0, abs=0.01)

    asyncio.run(run())


def test_invalidate_single_device():
    clock = FakeClock()
    cache = DeviceStateCache(ttl_seconds=60, clock=clock)
    cache._entries[("air", "status")] = (0.0, {"success": True})
    cache._entries[("lampu", "status")] = (0.0, {"success": True})

    cache.invalidate("air")

    assert cache.last_result(("air", "status")) is None
    assert cache.last_result(("lampu", "status")) is not None
