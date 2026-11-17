"""Test endpoint SSE /api/stream: autentikasi, format, dan tanpa I/O perangkat."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import tuyabot.infra.state_cache as state_cache
import tuyabot.web.deps as deps
import tuyabot.web.routes as routes
from tuyabot.web.app import app

API_KEY = "kunci-stream"


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
    now = time.monotonic()
    state_cache.cache._entries[("air", "status")] = (now, {"success": True, "status": {"1": True}})
    state_cache.cache._entries[("air", "power")] = (
        now,
        {"success": True, "power_w": 412.5, "voltage_v": 221.0, "current_a": 1.87},
    )
    state_cache.cache._entries[("lampu", "status")] = (now, {"success": True, "status": {"20": False}})


def test_stream_requires_auth(client):
    assert client.get("/api/stream").status_code == 401


def test_stream_sends_snapshot_from_cache(client, monkeypatch):
    client.post("/api/login", json={"api_key": API_KEY})
    _seed_cache()

    # Kalau SSE sampai memanggil perangkat, test ini gagal — SSE harus murni baca cache.
    async def forbidden(*args, **kwargs):
        raise AssertionError("SSE tidak boleh memicu pembacaan perangkat")

    monkeypatch.setattr(routes, "get_status", forbidden)
    monkeypatch.setattr(routes, "get_power", forbidden)

    with client.stream("GET", "/api/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first_line = next(response.iter_lines())
        assert first_line.startswith("data: ")
        payload = json.loads(first_line[len("data: "):])

    assert payload["devices"]["air"]["switch_on"] is True
    assert payload["devices"]["air"]["power_w"] == 412.5
    assert payload["devices"]["lampu"]["switch_on"] is False
    assert isinstance(payload["ts"], float)


def test_stream_reports_offline_when_cache_empty(client):
    client.post("/api/login", json={"api_key": API_KEY})

    with client.stream("GET", "/api/stream") as response:
        first_line = next(response.iter_lines())
        payload = json.loads(first_line[len("data: "):])

    assert payload["devices"]["air"]["online"] is False
    assert payload["devices"]["air"]["switch_on"] is None
