from unittest.mock import patch, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport

from api.app import app


@pytest.mark.asyncio
async def test_db_api_requires_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/db/stats")
        assert res.status_code in (401, 503)


@pytest.mark.asyncio
async def test_db_api_stats_endpoint():
    transport = ASGITransport(app=app)
    mock_stats = {
        "connected": True,
        "database": "test_db",
        "host": "localhost",
        "retention_days": 60,
        "total_power_logs": 10,
        "total_activity_logs": 5,
        "total_error_logs": 2,
        "total_runtime_users": 3,
        "total_air_recipients": 1,
    }

    with patch("api.deps.DASHBOARD_API_KEY", "secret123"), \
         patch("database.get_db_stats", return_value=mock_stats):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/api/db/stats", headers={"X-API-Key": "secret123"})
            assert res.status_code == 200
            data = res.json()
            assert data["connected"] is True
            assert data["total_power_logs"] == 10


@pytest.mark.asyncio
async def test_db_api_power_logs_endpoint():
    transport = ASGITransport(app=app)
    mock_power = [
        {
            "id": 1,
            "device_name": "air",
            "power_w": 280.5,
            "voltage_v": 220.0,
            "current_a": 1.27,
            "switch_state": True,
            "source": "periodic",
            "created_at": "2026-09-03 18:00:00",
        }
    ]

    with patch("api.deps.DASHBOARD_API_KEY", "secret123"), \
         patch("database.get_recent_power_logs", return_value=mock_power):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/api/db/power-logs?limit=10", headers={"X-API-Key": "secret123"})
            assert res.status_code == 200
            data = res.json()
            assert len(data) == 1
            assert data[0]["power_w"] == 280.5


@pytest.mark.asyncio
async def test_db_api_activities_endpoint():
    transport = ASGITransport(app=app)
    mock_activities = [
        {
            "id": 1,
            "user_id": 12345,
            "user_role": "User",
            "device_name": "air",
            "action": "turn_on",
            "status": "success",
            "message": "Menyalakan pompa",
            "created_at": "2026-09-03 18:00:00",
        }
    ]

    with patch("api.deps.DASHBOARD_API_KEY", "secret123"), \
         patch("database.get_recent_activities", return_value=mock_activities):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/api/db/activities?limit=10", headers={"X-API-Key": "secret123"})
            assert res.status_code == 200
            data = res.json()
            assert len(data) == 1
            assert data[0]["action"] == "turn_on"


@pytest.mark.asyncio
async def test_db_api_users_endpoint():
    transport = ASGITransport(app=app)
    mock_details = {
        "env": {999: "Superadmin"},
        "runtime": [{"user_id": 12345, "role": 1, "added_by": 999, "added_by_name": "Admin", "created_at": "2026-09-03"}],
    }

    with patch("api.deps.DASHBOARD_API_KEY", "secret123"), \
         patch("auth_manager.auth.list_users_detailed", return_value=mock_details), \
         patch("auth_manager.auth.get_air_notify_recipient_ids", return_value={888}):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get("/api/db/users", headers={"X-API-Key": "secret123"})
            assert res.status_code == 200
            data = res.json()
            assert "999" in data["env"] or 999 in data["env"]
            assert len(data["runtime"]) == 1
            assert 888 in data["air_recipients"]


@pytest.mark.asyncio
async def test_db_api_cleanup_endpoint():
    transport = ASGITransport(app=app)
    mock_cleanup = {
        "power_logs_deleted": 12,
        "activity_logs_deleted": 4,
        "error_logs_deleted": 1,
    }

    with patch("api.deps.DASHBOARD_API_KEY", "secret123"), \
         patch("database.cleanup_old_logs", return_value=mock_cleanup):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/db/cleanup", headers={"X-API-Key": "secret123"})
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["details"]["power_logs_deleted"] == 12
