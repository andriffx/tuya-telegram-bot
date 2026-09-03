import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import pytest

import bot
import config


@pytest.mark.asyncio
async def test_air_watchdog_starts_only_for_user():
    bot.cancel_air_watchdog()
    fake_context = MagicMock()
    fake_user = MagicMock()
    fake_user.id = 12345
    fake_user.full_name = "User Budi"
    fake_user.username = "budi"

    # 1. Role USER -> watchdog must start
    with patch("auth_manager.auth.get_role", return_value=bot.USER):
        bot._handle_air_watchdog_trigger(
            fake_context, fake_user, "air", "on", {"success": True}
        )
        assert bot._active_air_watchdog is not None
        assert not bot._active_air_watchdog.done()
        bot.cancel_air_watchdog()
        assert bot._active_air_watchdog is None

    # 2. Role ADMIN -> watchdog should NOT start
    with patch("auth_manager.auth.get_role", return_value=bot.ADMIN):
        bot._handle_air_watchdog_trigger(
            fake_context, fake_user, "air", "on", {"success": True}
        )
        assert bot._active_air_watchdog is None

    # 3. Role SUPERADMIN -> watchdog should NOT start
    with patch("auth_manager.auth.get_role", return_value=bot.SUPERADMIN):
        bot._handle_air_watchdog_trigger(
            fake_context, fake_user, "air", "on", {"success": True}
        )
        assert bot._active_air_watchdog is None


@pytest.mark.asyncio
async def test_air_watchdog_cancels_on_turn_off():
    bot.cancel_air_watchdog()
    fake_context = MagicMock()
    fake_user = MagicMock()
    fake_user.id = 12345

    with patch("auth_manager.auth.get_role", return_value=bot.USER):
        bot._handle_air_watchdog_trigger(
            fake_context, fake_user, "air", "on", {"success": True}
        )
        assert bot._active_air_watchdog is not None

        # Turn off -> must cancel
        bot._handle_air_watchdog_trigger(
            fake_context, fake_user, "air", "off", {"success": True}
        )
        assert bot._active_air_watchdog is None


@pytest.mark.asyncio
async def test_execute_air_auto_off_notifications_and_logging():
    fake_context = MagicMock()
    fake_context.bot = MagicMock()
    fake_context.bot.send_message = AsyncMock()

    fake_user = MagicMock()
    fake_user.id = 777
    fake_user.full_name = "User Budi"
    fake_user.username = "budi"

    with patch("bot.run_tuya", new_callable=AsyncMock) as mock_tuya, \
         patch("database.log_activity") as mock_log_act, \
         patch("database.log_power") as mock_log_pwr, \
         patch("auth_manager.auth.get_superadmin_ids", return_value={999}), \
         patch("auth_manager.auth.get_air_notify_recipient_ids", return_value={888}):

        mock_tuya.return_value = {"success": True}

        await bot._execute_air_auto_off(
            fake_context, fake_user, reason="idle", power_w=125.0
        )

        # Verify Tuya turn_off called
        mock_tuya.assert_called_once()

        # Verify Database activity & power logged
        mock_log_act.assert_called_once_with(
            user_id=777,
            user_role="User",
            device_name="air",
            action="turn_off",
            status="auto_off",
            message="Auto-off: Pompa terdeteksi idle/tidak digunakan (daya 125.0W)",
        )
        mock_log_pwr.assert_called_once_with(
            device_name="air",
            power_w=125.0,
            voltage_v=0.0,
            current_a=0.0,
            switch_state=False,
            source="auto_off",
        )

        # Verify Telegram notifications sent to: User (777), Superadmin (999), Admin (888)
        assert fake_context.bot.send_message.call_count == 3
        sent_chats = {call[1]["chat_id"] for call in fake_context.bot.send_message.call_args_list}
        assert sent_chats == {777, 888, 999}


@pytest.mark.asyncio
async def test_air_watchdog_detects_idle_and_auto_shuts_off():
    fake_context = MagicMock()
    fake_user = MagicMock()
    fake_user.id = 12345
    fake_user.full_name = "User Test"
    fake_user.username = "test"

    # Status shows pump is on, but power samples are low (< 200W)
    status_response = {"success": True, "status": {"1": True}}
    power_response = {"success": True, "power_w": 120.0}  # idle / leak cycling

    with patch("bot.run_tuya", new_callable=AsyncMock) as mock_tuya, \
         patch("bot._execute_air_auto_off", new_callable=AsyncMock) as mock_auto_off, \
         patch.object(config, "AIR_AUTO_OFF_SAMPLE_COUNT", 3), \
         patch.object(config, "AIR_AUTO_OFF_CHECK_MINUTES", 0.0005):

        mock_tuya.side_effect = [
            status_response,  # get_status
            power_response,   # sample 1
            power_response,   # sample 2
            power_response,   # sample 3
        ]


        task = asyncio.create_task(bot._air_watchdog_loop(fake_context, fake_user))
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


        mock_auto_off.assert_called_once()
        call_kwargs = mock_auto_off.call_args[1]
        assert call_kwargs["reason"] == "idle"
        assert call_kwargs["power_w"] == 120.0
