import os
import importlib

def test_mysql_config_loaded(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "192.168.1.100")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_USER", "remote_user")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret123")
    monkeypatch.setenv("MYSQL_DATABASE", "smarthome")
    monkeypatch.setenv("MYSQL_POOL_SIZE", "10")
    monkeypatch.setenv("POWER_LOG_INTERVAL_MINUTES", "15")

    import config
    importlib.reload(config)

    assert config.MYSQL_CONFIG["host"] == "192.168.1.100"
    assert config.MYSQL_CONFIG["port"] == 3307
    assert config.MYSQL_CONFIG["user"] == "remote_user"
    assert config.MYSQL_CONFIG["password"] == "secret123"
    assert config.MYSQL_CONFIG["database"] == "smarthome"
    assert config.MYSQL_CONFIG["pool_size"] == 10
    assert config.POWER_LOG_INTERVAL_MINUTES == 15
