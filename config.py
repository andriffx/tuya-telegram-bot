"""
Konfigurasi perangkat Tuya untuk bot Telegram.

SEMUA data sensitif dibaca dari environment variables (file .env).
JANGAN menulis credential langsung di file ini.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ── Telegram ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


def _parse_version(env_key: str, default: float = 3.5):
    """Parse versi dari env, fallback ke default jika kosong/invalid."""
    val = os.getenv(env_key, "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── Perangkat Tuya (baca dari .env) ──
# Jangan isi default sensitif di sini — semua nilai aktual di .env
DEVICES = {
    "lampu": {
        "id": os.getenv("DEVICE_LAMPU_ID", ""),
        "ip": os.getenv("DEVICE_LAMPU_IP", ""),
        "local_key": os.getenv("DEVICE_LAMPU_KEY", ""),
        "version": _parse_version("DEVICE_LAMPU_VER", 3.5),
        "type": "bulb",
        "dps_switch": 20,
        "dps_brightness": 22,
        "dps_temp": 23,
        "dps_colour": 24
    },
    "air": {
        "id": os.getenv("DEVICE_AIR_ID", ""),
        "ip": os.getenv("DEVICE_AIR_IP", ""),
        "local_key": os.getenv("DEVICE_AIR_KEY", ""),
        "version": _parse_version("DEVICE_AIR_VER", 3.5),
        "type": "plug",
        "dps_switch": 1,
        "dps_current": 18,
        "dps_power": 19,
        "dps_voltage": 20
    }
}


# ── Validasi config ──
def validate_config() -> bool:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    for name, dev in DEVICES.items():
        if not dev["id"]:
            missing.append(f"DEVICE_{name.upper()}_ID")
        if not dev["local_key"]:
            missing.append(f"DEVICE_{name.upper()}_KEY")
    if missing:
        logger.warning("ENV MISSING: %s", ", ".join(missing))
    return not missing


# ── Auth ──
# Format: ALLOWED_USERS=123456789,987654321
_allowed_raw = os.getenv("ALLOWED_USERS", "").strip()
if _allowed_raw:
    ALLOWED_USERS = [int(x.strip()) for x in _allowed_raw.split(",") if x.strip().isdigit()]
else:
    ALLOWED_USERS = []


# ── MySQL Config (External) ──
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "tuyabot"),
    "pool_size": int(os.getenv("MYSQL_POOL_SIZE", "5")),
    "connect_timeout": int(os.getenv("MYSQL_CONNECT_TIMEOUT", "5")),
}

POWER_LOG_INTERVAL_MINUTES = int(os.getenv("POWER_LOG_INTERVAL_MINUTES", "5"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "60"))

# ── Air Auto-Off Watchdog (Role User) ──
AIR_AUTO_OFF_IDLE_WATT = float(os.getenv("AIR_AUTO_OFF_IDLE_WATT", "200.0"))
AIR_AUTO_OFF_CHECK_MINUTES = int(os.getenv("AIR_AUTO_OFF_CHECK_MINUTES", "3"))
AIR_AUTO_OFF_MAX_MINUTES = int(os.getenv("AIR_AUTO_OFF_MAX_MINUTES", "30"))
AIR_AUTO_OFF_SAMPLE_COUNT = int(os.getenv("AIR_AUTO_OFF_SAMPLE_COUNT", "3"))
AIR_AUTO_OFF_SAMPLE_DELAY_SECONDS = float(os.getenv("AIR_AUTO_OFF_SAMPLE_DELAY_SECONDS", "2.0"))




