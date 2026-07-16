"""
Controller untuk perangkat Tuya menggunakan tinytuya.
"""

import threading
import time
import tinytuya
import logging
from config import DEVICES

logger = logging.getLogger(__name__)

# Retry config
RETRIES = 3
RETRY_DELAY = 1.5  # detik
VERIFY_DELAY = 0.3  # jeda singkat setelah set_status agar perangkat sempat apply


class TuyaDeviceController:
    """Kontrol perangkat Tuya via tinytuya."""

    def __init__(self):
        self.devices = {}
        # Semua I/O Tuya diserialkan — hindari race saat air+lampu diklik bersamaan
        self._io_lock = threading.Lock()
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
                if not info.get("ip"):
                    device.set_address("Auto")

                device.set_socketTimeout(4)
                device.set_socketRetryLimit(2)
                device.set_socketRetryDelay(0.5)
                # Jangan pakai persistent — bisa return status cache/stale
                device.set_socketPersistent(False)

                self.devices[name] = {
                    "device": device,
                    "info": info,
                    "status": "initialized"
                }
                logger.info("Perangkat '%s' diinisialisasi (ID: %s)", name, info["id"])
            except Exception as e:
                logger.error("Gagal inisialisasi perangkat '%s': %s", name, e)
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

    def _extract_dps(self, raw_status) -> dict:
        """Ekstrak DPS dari respon device.status()."""
        if isinstance(raw_status, dict):
            if "dps" in raw_status:
                return raw_status["dps"]
            return raw_status
        return {}

    def _is_valid_response(self, raw) -> bool:
        if not isinstance(raw, dict):
            return False
        if raw.get("Err"):
            return False
        dps = self._extract_dps(raw)
        return isinstance(dps, dict) and len(dps) > 0

    def _get_switch_state(self, device_name: str):
        """
        Baca status switch perangkat.
        Return True/False jika berhasil, None jika tidak bisa dibaca.
        """
        device_data = self.devices[device_name]
        device = device_data["device"]
        dps_switch = str(device_data["info"].get("dps_switch", 1))

        raw = device.status()
        if not self._is_valid_response(raw):
            logger.warning("[%s] Respon status tidak valid: %r", device_name, raw)
            return None

        dps = self._extract_dps(raw)
        if dps_switch not in dps:
            logger.warning(
                "[%s] DPS %s tidak ada di response: %r",
                device_name, dps_switch, dps
            )
            return None

        value = dps[dps_switch]
        logger.info("[%s] DPS %s=%r", device_name, dps_switch, value)
        return bool(value)

    def _apply_switch(self, device_name: str, state: bool):
        """Kirim perintah on/off dan tunggu respons (bukan fire-and-forget)."""
        device_data = self.devices[device_name]
        device = device_data["device"]
        dps_switch = device_data["info"].get("dps_switch", 1)

        if not device_data["info"].get("ip"):
            device.set_address("Auto")

        result = device.set_status(state, switch=dps_switch)
        if isinstance(result, dict) and result.get("Err"):
            raise RuntimeError(f"Tuya Err: {result['Err']}")
        return result

    def _set_device_state(self, device_name: str, state: bool) -> dict:
        """Set status perangkat dengan lock, cek status valid, dan verifikasi setelah set."""
        if device_name not in self.devices:
            return {
                "success": False,
                "message": f"Perangkat '{device_name}' tidak ditemukan di konfigurasi."
            }

        device_data = self.devices[device_name]
        if device_data["device"] is None:
            return {
                "success": False,
                "message": f"Perangkat '{device_name}' gagal diinisialisasi."
            }

        dps_switch = device_data["info"].get("dps_switch", 1)
        icon = "💧" if device_name == "air" else "💡"

        with self._io_lock:
            # ── Cek status — hanya no-op jika DPS switch terbaca dengan valid ──
            current = self._get_switch_state(device_name)
            if current is not None and current == state:
                label = "menyala" if state else "mati"
                return {
                    "success": True,
                    "message": f"{icon} {device_name.upper()} sudah {label}",
                    "no_op": True
                }

            # ── Set state + verifikasi ulang ──
            last_error = None
            for attempt in range(1, RETRIES + 1):
                try:
                    self._apply_switch(device_name, state)
                    time.sleep(VERIFY_DELAY)
                    verified = self._get_switch_state(device_name)

                    if verified is not None and verified == state:
                        status_text = "dinyalakan" if state else "dimatikan"
                        logger.info(
                            "[%s] DPS %s=%s verified (attempt %d/%d)",
                            device_name, dps_switch, state, attempt, RETRIES
                        )
                        return {
                            "success": True,
                            "message": f"✅ {device_name.upper()} berhasil {status_text}",
                        }

                    last_error = (
                        f"verifikasi gagal: harapnya {state}, "
                        f"dibaca {verified}"
                    )
                    logger.warning(
                        "[%s] Attempt %d/%d: %s",
                        device_name, attempt, RETRIES, last_error
                    )

                except Exception as e:
                    last_error = e
                    logger.warning(
                        "[%s] Attempt %d/%d gagal: %s",
                        device_name, attempt, RETRIES, e
                    )

                if attempt < RETRIES:
                    time.sleep(RETRY_DELAY)

        logger.error("[%s] Semua retry gagal: %s", device_name, last_error)
        return {
            "success": False,
            "message": f"❌ Gagal mengontrol {device_name}: {last_error}"
        }

    def _device_call(self, device_name: str, call_fn, extract_fn=None):
        """Helper: panggil device method dengan retry (terkunci)."""
        if device_name not in self.devices:
            return {"success": False, "message": f"Perangkat '{device_name}' tidak ditemukan."}

        device_data = self.devices[device_name]
        device = device_data["device"]
        if device is None:
            return {"success": False, "message": f"Perangkat '{device_name}' belum diinisialisasi."}

        with self._io_lock:
            last_error = None
            for attempt in range(1, RETRIES + 1):
                try:
                    raw = call_fn(device)
                    if extract_fn:
                        return extract_fn(raw)
                    return {"success": True, "result": raw}
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
