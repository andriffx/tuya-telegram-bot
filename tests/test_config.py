import importlib


def test_sqlite_config_loaded(monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", "/srv/tuyabot/data/tuyabot.db")
    monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", "7500")
    monkeypatch.setenv("POWER_LOG_INTERVAL_MINUTES", "15")

    import config
    importlib.reload(config)

    assert config.SQLITE_PATH == "/srv/tuyabot/data/tuyabot.db"
    assert config.SQLITE_BUSY_TIMEOUT_MS == 7500
    assert config.POWER_LOG_INTERVAL_MINUTES == 15


def test_sqlite_defaults(monkeypatch):
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.delenv("SQLITE_BUSY_TIMEOUT_MS", raising=False)

    import config
    importlib.reload(config)

    assert config.SQLITE_PATH == "data/tuyabot.db"
    assert config.SQLITE_BUSY_TIMEOUT_MS == 5000
