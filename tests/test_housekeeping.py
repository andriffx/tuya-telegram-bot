import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

@pytest.mark.asyncio
async def test_housekeeping_loop_single_iteration():
    with patch("database.cleanup_old_logs", return_value={"power_logs_deleted": 5}) as mock_cleanup:
        from run import housekeeping_loop
        # Run housekeeping_loop with cancellation after brief time
        task = asyncio.create_task(housekeeping_loop(interval_hours=1))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Loop was canceled gracefully without error

@pytest.mark.asyncio
async def test_cleanlogs_command():
    with patch("database.cleanup_old_logs") as mock_cleanup, \
         patch("auth_manager.auth.get_role", return_value=3):
        mock_cleanup.return_value = {
            "power_logs_deleted": 10,
            "activity_logs_deleted": 2,
            "error_logs_deleted": 1,
        }

        import bot
        fake_update = MagicMock()
        fake_context = MagicMock()
        fake_user = MagicMock()
        fake_user.id = 999
        fake_update.effective_user = fake_user
        fake_update.message.reply_text = AsyncMock()

        # Run command
        await bot.cleanlogs_command(fake_update, fake_context)

        assert fake_update.message.reply_text.call_count == 2
        last_reply = fake_update.message.reply_text.call_args[0][0]
        assert "Pembersihan Database Selesai" in last_reply
        assert "Total: *13* baris log berhasil dibersihkan" in last_reply


@pytest.mark.asyncio
async def test_cleanlogs_callback():
    with patch("database.cleanup_old_logs") as mock_cleanup:
        mock_cleanup.return_value = {
            "power_logs_deleted": 5,
            "activity_logs_deleted": 1,
            "error_logs_deleted": 0,
        }

        import bot
        fake_query = MagicMock()
        fake_query.message.reply_text = AsyncMock()
        fake_context = MagicMock()

        await bot._callback_users(fake_query, fake_context, "cleanlogs", bot.SUPERADMIN)

        assert fake_query.message.reply_text.call_count == 2
        last_reply = fake_query.message.reply_text.call_args[0][0]
        assert "Pembersihan Database Selesai" in last_reply
        assert "Total: *6* baris log berhasil dibersihkan" in last_reply


@pytest.mark.asyncio
async def test_clean_chat_command():
    import bot
    fake_update = MagicMock()
    fake_context = MagicMock()
    fake_update.effective_chat.id = 12345
    fake_update.effective_message.message_id = 100
    fake_update.effective_user.id = 12345
    fake_context.bot.delete_messages = AsyncMock()
    fake_context.bot.send_message = AsyncMock()

    await bot.clean_chat_command(fake_update, fake_context)

    fake_context.bot.delete_messages.assert_called_once()
    fake_context.bot.send_message.assert_called_once()
    sent_text = fake_context.bot.send_message.call_args[1]["text"]
    assert "Pesan berhasil dibersihkan" in sent_text


@pytest.mark.asyncio
async def test_clean_chat_command_fallback_parallel():
    import bot
    fake_update = MagicMock()
    fake_context = MagicMock()
    fake_update.effective_chat.id = 12345
    fake_update.effective_message.message_id = 10
    fake_update.effective_user.id = 12345
    fake_context.bot.delete_messages = AsyncMock(side_effect=Exception("BadRequest"))
    fake_context.bot.delete_message = AsyncMock()
    fake_context.bot.send_message = AsyncMock()
    fake_context.user_data = {}

    await bot.clean_chat_command(fake_update, fake_context)

    assert fake_context.bot.delete_message.call_count > 0
    fake_context.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_callback_users_list():

    import bot
    fake_query = MagicMock()
    fake_query.message.reply_text = AsyncMock()
    fake_context = MagicMock()

    await bot._callback_users(fake_query, fake_context, "list", bot.SUPERADMIN)

    fake_query.message.reply_text.assert_called_once()
    reply = fake_query.message.reply_text.call_args[0][0]
    assert "Daftar User" in reply


@pytest.mark.asyncio
async def test_help_command_roles():
    import bot
    fake_update = MagicMock()
    fake_context = MagicMock()
    fake_update.message.reply_text = AsyncMock()

    # 1. Test PUBLIC role
    with patch("auth_manager.auth.get_role", return_value=bot.PUBLIC):
        await bot.help_command(fake_update, fake_context)
        public_text = fake_update.message.reply_text.call_args[0][0]
        assert "belum memiliki izin kontrol perangkat" in public_text
        assert "Air —" not in public_text
        assert "Lampu —" not in public_text

    # 2. Test USER role
    with patch("auth_manager.auth.get_role", return_value=bot.USER):
        await bot.help_command(fake_update, fake_context)
        user_text = fake_update.message.reply_text.call_args[0][0]
        assert "Air" in user_text
        assert "Lampu" not in user_text
        assert "Manajemen Tuyabot" not in user_text

    # 3. Test SUPERADMIN role
    with patch("auth_manager.auth.get_role", return_value=bot.SUPERADMIN):
        await bot.help_command(fake_update, fake_context)
        admin_text = fake_update.message.reply_text.call_args[0][0]
        assert "Manajemen Tuyabot" in admin_text





