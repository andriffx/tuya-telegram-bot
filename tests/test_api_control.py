"""Regresi endpoint kontrol: setelah relay diubah, dashboard tidak boleh "offline".

Bug yang dijaga: `cache.invalidate(name)` dulu menghapus entry cache, sehingga
snapshot SSE/dashboard berikutnya melihat cache kosong dan melaporkan perangkat
"offline" padahal relay baru saja dinyalakan. Sekarang invalidate menandai basi
(nilai terakhir tetap terbaca) dan endpoint kontrol langsung memuat ulang status.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

import tuyabot.infra.state_cache as state_cache
import tuyabot.web.deps as deps
import tuyabot.web.routes as routes
from tuyabot.web.app import app

API_KEY = "kunci-kontrol-uji"


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(deps, "DASHBOARD_API_KEY", API_KEY)
    state_cache.cache._entries.clear()
    yield
    state_cache.cache._entries.clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _seed_cache():
    import time

    now = time.monotonic()
    state_cache.cache._entries[("lampu", "status")] = (
        now,
        {"success": True, "status": {"20": False}},
    )


def _fake_device(monkeypatch, *, control_ok=True, status_ok=True, seen=None):
    """Ganti panggilan perangkat & DB dengan versi palsu."""

    async def fake_run_tuya(func, *args, **kwargs):
        if seen is not None:
            seen.append("control")
        if not control_ok:
            return {"success": False, "message": "perangkat tidak merespons"}
        return {"success": True, "message": "✅ LAMPU berhasil dinyalakan"}

    async def fake_get_status(name, *, force=False):
        if seen is not None:
            seen.append(("status", force))
        if not status_ok:
            return {"success": False, "message": "timeout"}
        result = {"success": True, "status": {"20": True}}
        state_cache.cache._entries[(name, "status")] = (time.monotonic(), result)
        return result

    async def fake_run_db(func, *args, **kwargs):
        return True

    monkeypatch.setattr(routes, "run_tuya", fake_run_tuya)
    monkeypatch.setattr(routes, "get_status", fake_get_status)
    monkeypatch.setattr(routes, "run_db", fake_run_db)


def test_control_refreshes_cache_so_live_is_not_offline(client, monkeypatch):
    client.post("/api/login", json={"api_key": API_KEY})
    _seed_cache()
    seen = []
    _fake_device(monkeypatch, seen=seen)

    response = client.post("/api/devices/lampu/on")
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Endpoint kontrol wajib memuat ulang status dengan force=True.
    assert ("status", True) in seen, "status perangkat harus dibaca ulang setelah kontrol"

    with client.stream("GET", "/api/stream") as stream:
        payload = json.loads(next(stream.iter_lines())[len("data: "):])

    lampu = payload["devices"]["lampu"]
    assert lampu["online"] is True, "dashboard melaporkan offline padahal relay menyala"
    assert lampu["switch_on"] is True


def test_control_failure_keeps_last_known_state_visible(client, monkeypatch):
    """Kontrol gagal tidak boleh mengosongkan cache sampai perangkat tampak offline."""
    client.post("/api/login", json={"api_key": API_KEY})
    _seed_cache()
    _fake_device(monkeypatch, control_ok=False)

    response = client.post("/api/devices/lampu/on")
    assert response.status_code == 200
    assert response.json()["success"] is False

    with client.stream("GET", "/api/stream") as stream:
        payload = json.loads(next(stream.iter_lines())[len("data: "):])

    lampu = payload["devices"]["lampu"]
    # Nilai terakhir masih tersaji (data lama), bukan None/offline mendadak.
    assert lampu["switch_on"] is False
    assert lampu["status_age_s"] is not None
