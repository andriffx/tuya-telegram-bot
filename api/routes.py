"""REST API routes untuk web dashboard."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

import database
from auth_manager import auth
from api.deps import get_device_names, verify_api_key

from api.schemas import (
    ControlResponse,
    DeviceListResponse,
    DeviceStatusResponse,
    HealthResponse,
    PowerInfoResponse,
)
from config import DEVICES
from device_service import run_tuya, tuya

router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


def _switch_from_dps(name: str, dps: dict) -> bool | None:
    if not isinstance(dps, dict):
        return None
    key = str(DEVICES[name].get("dps_switch", 1))
    if key not in dps:
        return None
    return bool(dps[key])


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices():
    return DeviceListResponse(devices=tuya.list_devices())


@router.get("/devices/{name}/status", response_model=DeviceStatusResponse)
async def device_status(name: str):
    if name not in get_device_names():
        raise HTTPException(status_code=404, detail=f"Perangkat '{name}' tidak ditemukan")

    result = await run_tuya(tuya.get_status, name)
    if not result.get("success"):
        return DeviceStatusResponse(
            success=False,
            name=name,
            online=False,
            message=result.get("message", "Gagal membaca status"),
        )

    dps = result.get("status", {})
    return DeviceStatusResponse(
        success=True,
        name=name,
        online=True,
        switch_on=_switch_from_dps(name, dps),
        dps=dps,
    )


@router.get("/devices/air/power", response_model=PowerInfoResponse)
async def air_power():
    result = await run_tuya(tuya.get_power_info, "air")
    if not result.get("success"):
        return PowerInfoResponse(
            success=False,
            message=result.get("message", "Gagal membaca daya"),
        )

    raw = result.get("raw", {})
    return PowerInfoResponse(
        success=True,
        power_w=result.get("power_w", 0),
        current_a=result.get("current_a", 0),
        voltage_v=result.get("voltage_v", 0),
        switch_on=_switch_from_dps("air", raw),
    )


@router.post("/devices/{name}/on", response_model=ControlResponse)
async def device_on(name: str):
    return await _control(name, True)


@router.post("/devices/{name}/off", response_model=ControlResponse)
async def device_off(name: str):
    return await _control(name, False)


async def _control(name: str, state: bool) -> ControlResponse:
    if name not in get_device_names():
        raise HTTPException(status_code=404, detail=f"Perangkat '{name}' tidak ditemukan")

    method = tuya.turn_on if state else tuya.turn_off
    result = await run_tuya(method, name)

    try:
        import database
        status_str = "success" if result.get("success") else "failed"
        database.log_activity(
            user_id=0,
            user_role="api",
            device_name=name,
            action="turn_on" if state else "turn_off",
            status=status_str,
            message=result.get("message", ""),
        )
    except Exception:
        pass

    return ControlResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        no_op=result.get("no_op", False),
    )


# ── Database & Telemetry Endpoints ──


@router.get("/db/stats")
async def get_database_stats():
    """Statistik ringkas database MySQL & retensi log."""
    return database.get_db_stats()


@router.get("/db/power-logs")
async def get_power_logs(limit: int = 50, device: Optional[str] = None):
    """Ambil data konsumsi daya terbaru dari device_power_logs."""
    limit = max(1, min(limit, 200))
    return database.get_recent_power_logs(device_name=device, limit=limit)


@router.get("/db/activities")
async def get_activity_logs(limit: int = 50):
    """Ambil riwayat aktivitas kontrol perangkat dari device_activity_logs."""
    limit = max(1, min(limit, 200))
    return database.get_recent_activities(limit=limit)


@router.get("/db/users")
async def get_users_list():
    """Daftar user ENV & MySQL serta daftar penerima notifikasi air."""
    details = auth.list_users_detailed()
    recipients = list(auth.get_air_notify_recipient_ids())
    return {
        "env": details.get("env", {}),
        "runtime": details.get("runtime", []),
        "air_recipients": recipients,
    }


@router.get("/db/errors")
async def get_error_logs(limit: int = 50):
    """Ambil log error aplikasi dari app_error_logs."""
    limit = max(1, min(limit, 200))
    return database.get_recent_app_errors(limit=limit)


@router.post("/db/cleanup")
async def cleanup_database(retention_days: Optional[int] = None):
    """Jalankan pembersihan log database (housekeeping) secara manual."""
    res = database.cleanup_old_logs(retention_days=retention_days)
    return {
        "success": True,
        "message": f"Pembersihan database selesai: {sum(res.values())} baris log dihapus",
        "details": res,
    }


