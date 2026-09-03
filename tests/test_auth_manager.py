from unittest.mock import patch
import auth_manager

def test_auth_manager_env_override(monkeypatch):
    monkeypatch.setattr(auth_manager, "ENV_SUPERADMIN", {999})
    assert auth_manager.auth.get_role(999) == auth_manager.SUPERADMIN

def test_auth_manager_direct_query():
    with patch("database.get_user_role") as mock_db_get:
        mock_db_get.return_value = auth_manager.ADMIN
        assert auth_manager.auth.get_role(12345) == auth_manager.ADMIN
        mock_db_get.assert_called_with(12345)

def test_auth_manager_db_down_fallback():
    with patch("database.get_user_role") as mock_db_get:
        mock_db_get.return_value = None  # DB down / not found
        # Fallback to PUBLIC
        assert auth_manager.auth.get_role(88888) == auth_manager.PUBLIC

def test_auth_manager_set_and_remove_user():
    with patch("database.set_user_role", return_value=True) as mock_set, \
         patch("database.remove_user", return_value=True) as mock_remove:
        
        # Non-env user can be set
        assert auth_manager.auth.set_role(55555, auth_manager.USER) is True
        mock_set.assert_called_with(55555, auth_manager.USER)

        # Non-env user can be removed
        assert auth_manager.auth.remove_user(55555) is True
        mock_remove.assert_called_with(55555)

def test_auth_manager_air_recipients():
    with patch("database.get_air_recipients", return_value={101}) as mock_get_recipients, \
         patch("database.add_air_recipient", return_value=True) as mock_add_recipient, \
         patch("database.get_user_role", return_value=auth_manager.ADMIN):
        
        recipients = auth_manager.auth.get_air_notify_recipient_ids()
        assert recipients == {101}

        # Add admin
        ok, msg = auth_manager.auth.add_air_notify_recipient(102)
        assert ok is True
        assert "ditambahkan" in msg
