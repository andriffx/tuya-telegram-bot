from unittest.mock import MagicMock, patch
import pytest

def test_database_crud_operations():
    with patch("database.get_db_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = (mock_conn, mock_cursor)

        import database

        # Test get_user_role found
        mock_cursor.fetchone.return_value = (2,)
        role = database.get_user_role(12345)
        assert role == 2

        # Test get_user_role not found
        mock_cursor.fetchone.return_value = None
        role = database.get_user_role(99999)
        assert role is None

        # Test set_user_role with added_by
        res = database.set_user_role(12345, 1, added_by=999, added_by_name="Superadmin")
        assert res is True
        mock_cursor.execute.assert_called()

        # Test get_all_runtime_users_details
        mock_cursor.fetchall.return_value = [(12345, 1, 999, "Superadmin", "2026-09-03 10:00:00", "2026-09-03 10:00:00")]
        details = database.get_all_runtime_users_details()
        assert len(details) == 1
        assert details[0]["user_id"] == 12345
        assert details[0]["added_by"] == 999
        assert details[0]["added_by_name"] == "Superadmin"

        # Test remove_user
        mock_cursor.rowcount = 1
        res = database.remove_user(12345)
        assert res is True


        # Test get_air_recipients
        mock_cursor.fetchall.return_value = [(111,), (222,)]
        recipients = database.get_air_recipients()
        assert recipients == {111, 222}

        # Test add_air_recipient
        res = database.add_air_recipient(333)
        assert res is True

        # Test remove_air_recipient
        mock_cursor.rowcount = 1
        res = database.remove_air_recipient(333)
        assert res is True

        # Test log_activity
        res = database.log_activity(123, "Admin", "lampu", "turn_on", "success", "Lampu ON")
        assert res is True

        # Test log_power
        res = database.log_power("air", 120.5, 220.0, 0.55, True, "periodic")
        assert res is True

def test_database_error_logging(caplog):
    with patch("database.get_db_connection") as mock_get_conn:
        # Simulate connection error
        mock_get_conn.side_effect = Exception("Connection refused to external MySQL")

        import database
        # Gracefully returns None or False and logs error
        role = database.get_user_role(12345)
        assert role is None
        assert "[DATABASE ERROR]" in caplog.text

        caplog.clear()
        res = database.set_user_role(12345, 2)
        assert res is False
        assert "[DATABASE ERROR]" in caplog.text

        caplog.clear()
        res = database.log_activity(123, "Admin", "air", "turn_off", "success")
        assert res is False
        assert "[DATABASE ERROR]" in caplog.text

        caplog.clear()
        res = database.log_power("air", 0.0, 220.0, 0.0, False, "periodic")
        assert res is False
        assert "[DATABASE ERROR]" in caplog.text


def test_app_error_logging_and_handler():
    with patch("database.get_db_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = (mock_conn, mock_cursor)

        import database
        import logging

        # 1. Test direct log_app_error
        res = database.log_app_error(
            level="ERROR",
            logger_name="test_logger",
            message="Test error message",
            exception_trace="Traceback...",
            file_name="test.py",
            line_number=42,
        )
        assert res is True
        mock_cursor.execute.assert_called()

        # 2. Test get_recent_app_errors
        mock_cursor.fetchall.return_value = [
            (1, "ERROR", "test_logger", "Test message", "Traceback...", "test.py", 42, "2026-09-03 12:00:00")
        ]
        errors = database.get_recent_app_errors(5)
        assert len(errors) == 1
        assert errors[0]["id"] == 1
        assert errors[0]["message"] == "Test message"

        # 3. Test MySQLDatabaseLogHandler
        handler = database.MySQLDatabaseLogHandler(level=logging.ERROR)
        record = logging.LogRecord(
            name="app_module",
            level=logging.ERROR,
            pathname="app.py",
            lineno=10,
            msg="App crashed!",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        # Verify execute was called for the emitted log record
        mock_cursor.execute.assert_called()


def test_database_cleanup_old_logs():
    with patch("database.get_db_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = (mock_conn, mock_cursor)

        import database

        mock_cursor.rowcount = 15
        res = database.cleanup_old_logs(retention_days=30)
        assert res["power_logs_deleted"] == 15
        assert res["activity_logs_deleted"] == 15
        assert res["error_logs_deleted"] == 15
        assert mock_cursor.execute.call_count == 3


