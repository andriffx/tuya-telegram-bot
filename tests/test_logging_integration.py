from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_action_logging_helper():
    with patch("tuyabot.storage.sqlite_store.log_activity") as mock_log_act, \
         patch("tuyabot.storage.sqlite_store.log_power") as mock_log_pwr, \
         patch("tuyabot.telegram.handlers.get_power", new_callable=AsyncMock) as mock_power:

        mock_power.return_value = {
            "success": True,
            "power_w": 250.0,
            "voltage_v": 220.0,
            "current_a": 1.13,
            "raw": {"1": True}
        }


        import tuyabot.telegram.handlers as bot
        fake_user = MagicMock()
        fake_user.id = 12345
        fake_user.full_name = "Test User"
        fake_user.username = "testuser"

        # Test air on
        await bot._log_control_event(
            user=fake_user,
            device_name="air",
            action="on",
            result={"success": True, "message": "Success"}
        )

        mock_log_act.assert_called_once_with(
            user_id=12345,
            user_role="Publik",
            device_name="air",
            action="turn_on",
            status="success",
            message="Success"
        )
        mock_log_pwr.assert_called_once_with(
            device_name="air",
            power_w=250.0,
            voltage_v=220.0,
            current_a=1.13,
            switch_state=True,
            source="action_switch"
        )
