"""Test endpoint kesehatan dan pemisahan liveness vs readiness."""

import pytest
from fastapi.testclient import TestClient

import api.deps as deps
import api.routes as routes
from api.app import app

KEY = "test-key-fase-2"
HEADERS = {"X-API-Key": KEY}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(deps, "DASHBOARD_API_KEY", KEY)


@pytest.fixture
def client():
    return TestClient(app)


class FakeCache:
    def __init__(self, states):
        self._states = states

    def snapshot(self):
        return self._states


def test_healthz_is_open_and_does_not_touch_database(client, monkeypatch):
    def boom():
        raise AssertionError("/healthz tidak boleh menyentuh database")

    monkeypatch.setattr(routes.database, "ping", boom)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_health_requires_api_key(client):
    assert client.get("/api/health").status_code == 401


def test_api_health_ok_when_db_and_devices_up(client, monkeypatch):
    monkeypatch.setattr(routes.database, "ping", lambda: True)
    monkeypatch.setattr(routes, "cache", FakeCache({"air.status": {"age_s": 1.0, "success": True}}))

    body = client.get("/api/health", headers=HEADERS).json()

    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["devices"] is True


def test_api_health_degraded_when_devices_unreachable(client, monkeypatch):
    monkeypatch.setattr(routes.database, "ping", lambda: True)
    monkeypatch.setattr(routes, "cache", FakeCache({"air.status": {"age_s": 90.0, "success": False}}))

    body = client.get("/api/health", headers=HEADERS).json()

    assert body["status"] == "degraded"
    assert body["database"] is True
    assert body["devices"] is False


def test_api_health_down_when_database_unreachable(client, monkeypatch):
    monkeypatch.setattr(routes.database, "ping", lambda: False)
    monkeypatch.setattr(routes, "cache", FakeCache({"air.status": {"age_s": 1.0, "success": True}}))

    body = client.get("/api/health", headers=HEADERS).json()

    assert body["status"] == "down"
    assert body["database"] is False


def test_device_status_uses_cache(client, monkeypatch):
    calls = []

    async def fake_get_status(name):
        calls.append(name)
        return {"success": True, "status": {"1": True}}

    monkeypatch.setattr(routes, "get_status", fake_get_status)

    first = client.get("/api/devices/air/status", headers=HEADERS).json()
    second = client.get("/api/devices/air/status", headers=HEADERS).json()

    assert first["switch_on"] is True
    assert second["success"] is True
    assert calls == ["air", "air"]


def test_control_invalidates_cache(client, monkeypatch):
    """Setelah kontrol, cache perangkat itu harus dibuang agar status tidak basi."""
    invalidated = []

    class RecordingCache:
        def snapshot(self):
            return {}

        def invalidate(self, device_name=None):
            invalidated.append(device_name)

    async def fake_run_tuya(method, name):
        return {"success": True, "message": "ok"}

    monkeypatch.setattr(routes, "cache", RecordingCache())
    monkeypatch.setattr(routes, "run_tuya", fake_run_tuya)
    monkeypatch.setattr(routes.database, "log_activity", lambda **kwargs: True)

    response = client.post("/api/devices/air/on", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert invalidated == ["air"]
