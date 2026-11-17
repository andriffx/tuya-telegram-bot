from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_power_monitor_single_iteration():
    with patch("tuyabot.main.run_tuya", new_callable=AsyncMock) as mock_tuya, \
         patch("tuyabot.storage.sqlite_store.log_power") as mock_log_power:

        mock_tuya.return_value = {
            "success": True,
            "power_w": 150.5,
            "voltage_v": 220.0,
            "current_a": 0.68,
            "raw": {"1": True}
        }

        from tuyabot.main import record_power_snapshot
        ok = await record_power_snapshot()

        assert ok is True or ok is not None
        mock_tuya.assert_called_once()
        mock_log_power.assert_called_once_with(
            device_name="air",
            power_w=150.5,
            voltage_v=220.0,
            current_a=0.68,
            switch_state=True,
            source="periodic"
        )
