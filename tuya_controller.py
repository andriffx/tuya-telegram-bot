"""
Controller untuk perangkat Tuya menggunakan tinytuya.
"""

import time
import tinytuya
import logging
from config import DEVICES

logger = logging.getLogger(__name__)

# Retry config
RETRIES = 3
RETRY_DELAY = 1.5  # detik


class TuyaDeviceController:
    """Kontrol perangkat Tuya via tinytuya."""

    def __init__(self):
        self.devices = {}
        self._initialize_devices()

    def _initialize_devices(self):
        """Inisialisasi koneksi ke semua perangkat."""
        for name, info in DEVICES.items():
            try:
                device = tinytuya.Device(
                    dev_id=info["id"],
                    address=info.get("ip", ""),
                    local_key=info["local_key"],
                    version=info.get("version", 3.3)
                )
                # Jika IP kosong, coba set address ke auto
                if not info.get("ip"):
                    device.set_address("Auto")

                # Timeout lebih pendek — kontrol on/off butuh respons cepat
                device.set_socketTimeout(4)
                device.set_socketRetryLimit(2)
                device.set_socketRetryDelay(0.5)
                device.set_socketPersistent(True)
                
                self.devices[name] = {
                    "device": device,
                    "info": info,
                    "status": "initialized"
                }
                logger.info(f"Perangkat '{name}' diinisialisasi (ID: {info['id']})")
            except Exception as e:
                logger.error(f"Gagal inisialisasi perangkat '{name}': {e}")
                self.devices[name] = {
                    "device": None,
                    "info": info,
                    "status": f"error: {e}"
                }

    def turn_on(self, device_name: str) -> dict:
        """Nyalakan perangkat."""
        return self._set_device_state(device_name, True)

    def turn_off(self, device_name: str) -> dict:
        """Matikan perangkat."""
        return self._set_device_state(device_name, False)

    def _set_device_state(self, device_name: str, state: bool) -> dict:
        """Set status perangkat (on/off) — langsung set_dps tanpa cek status dulu."""
        if device_name not in self.devices:
            return {
                "success": False,
                "message": f"Perangkat '{device_name}' tidak ditemukan di konfigurasi."
            }

        device_data = self.devices[device_name]
        device = device_data["device"]
        dps_switch = device_data["info"].get("dps_switch", 1)

        if device is None:
            return {
                "success": False,
                "message": f"Perangkat '{device_name}' gagal diinisialisasi."
            }

        # ── Set state langsung (1 round-trip ke perangkat) ──
        last_error = None
        for attempt in range(1, RETRIES + 1):
            try:
                if not device_data["info"].get("ip"):
                    device.set_address("Auto")

                dps_payload = {str(dps_switch): state}

                try:
                    result = device.set_dps(dps_payload)
                except AttributeError:
                    payload = device.generate_payload(tinytuya.CONTROL, dps_payload)
                    result = device.send(payload)

                status_text = "dinyalakan" if state else "dimatikan"
                logger.info("[%s] DPS %s=%s (attempt %d/%d)", device_name, dps_switch, state, attempt, RETRIES)
                return {
                    "success": True,
                    "message": f"✅ {device_name.upper()} berhasil {status_text}",
                    "raw": result
                }

            except Exception as e:
                last_error = e
                logger.warning("[%s] Attempt %d/%d gagal: %s", device_name, attempt, RETRIES, e)
                if attempt < RETRIES:
                    time.sleep(RETRY_DELAY)

        logger.error("[%s] Semua retry gagal: %s", device_name, last_error)
        return {
            "success": False,
            "message": f"❌ Gagal mengontrol {device_name}: {str(last_error)}"
        }

    def _extract_dps(self, raw_status) -> dict:
        """Ekstrak DPS dari respon device.status() — handle berbagai format."""
        if isinstance(raw_status, dict):
            # tinytuya sering return {"dps": {...}, "t": ...}
            if "dps" in raw_status:
                return raw_status["dps"]
            # Kadang return langsung DPS dict
            return raw_status
        return {}

    def _device_call(self, device_name: str, call_fn, extract_fn=None):
        """Helper: panggil device method dengan retry."""
        if device_name not in self.devices:
            return {"success": False, "message": f"Perangkat '{device_name}' tidak ditemukan."}

        device_data = self.devices[device_name]
        device = device_data["device"]
        if device is None:
            return {"success": False, "message": f"Perangkat '{device_name}' belum diinisialisasi."}

        last_error = None
        for attempt in range(1, RETRIES + 1):
            try:
                raw = call_fn(device)
                return extract_fn(raw) if extract_fn else {"success": True, "result": raw}
            except Exception as e:
                last_error = e
                logger.warning("[%s] Attempt %d/%d: %s", device_name, attempt, RETRIES, e)
                if attempt < RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": str(last_error)}

    def get_status(self, device_name: str) -> dict:
        """Ambil status perangkat."""
        result = self._device_call(device_name, lambda d: d.status())
        if not result["success"]:
            return result
        dps = self._extract_dps(result.get("result"))
        return {"success": True, "status": dps}

    def get_power_info(self, device_name: str = "air") -> dict:
        """Ambil data monitoring daya (arus, voltase, watt) dari smart plug."""
        result = self._device_call(device_name, lambda d: d.status())
        if not result["success"]:
            return result

        dps = self._extract_dps(result.get("result"))
        if not dps:
            return {"success": False, "message": "Respon tidak valid dari perangkat."}

        info = self.devices[device_name]["info"]
        dps_current = str(info.get("dps_current", 18))
        dps_power = str(info.get("dps_power", 19))
        dps_voltage = str(info.get("dps_voltage", 20))

        current_ma = dps.get(dps_current, 0)
        power_w = dps.get(dps_power, 0)
        voltage_v = dps.get(dps_voltage, 0)

        if isinstance(power_w, int):
            power_w = power_w / 10
        if isinstance(voltage_v, int):
            voltage_v = voltage_v / 10

        return {
            "success": True,
            "current_a": round(current_ma / 1000, 2) if isinstance(current_ma, (int, float)) else 0,
            "power_w": round(power_w, 1) if isinstance(power_w, (int, float)) else 0,
            "voltage_v": round(voltage_v, 1) if isinstance(voltage_v, (int, float)) else 0,
            "raw": dps
        }

    def list_devices(self) -> list:
        """Daftar semua perangkat yang tersedia."""
        return [
            {
                "name": name,
                "id": data["info"]["id"],
                "type": data["info"].get("type", "unknown"),
                "status": data["status"],
                "dps_switch": data["info"].get("dps_switch", 1)
            }
            for name, data in self.devices.items()
        ]
