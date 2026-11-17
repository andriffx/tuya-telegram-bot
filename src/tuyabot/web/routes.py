"""REST API routes untuk web dashboard."""

import asyncio
import json
import logging
import os
import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ..access.roles import auth
from ..config import DEVICES
from ..devices.service import run_tuya, tuya
from ..infra.asyncdb import run_db
from ..infra.state_cache import cache, get_power, get_status
from ..storage import sqlite_store as database
from .auth import (
    check_api_key,
    clear_session_cookie,
    require_auth,
    set_session_cookie,
    verify_session_token,
)
from .deps import get_device_names
from .schemas import (
    ControlResponse,
    DeviceListResponse,
    DeviceStatusResponse,
    HealthResponse,
    PowerInfoResponse,
)

# Seberapa sering SSE mengirim snapshot (detik).
STREAM_INTERVAL_SECONDS = max(1.0, float(os.getenv("STREAM_INTERVAL_SECONDS", "3")))

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

# Endpoint autentikasi sengaja tanpa dependency autentikasi.
auth_router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)

# ── Autentikasi dashboard ──


@auth_router.post("/login")
async def login(payload: dict, response: Response):
    """Tukar API key dengan session cookie (HttpOnly, SameSite=Strict)."""
    key = str(payload.get("api_key", ""))
    if not check_api_key(key):
        raise HTTPException(status_code=401, detail="API key tidak valid")
    set_session_cookie(response)
    return {"authenticated": True}


@auth_router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"authenticated": False}


@auth_router.get("/session")
async def session_status(tuyabot_session: str | None = Cookie(default=None)):
    """Dipakai halaman untuk memutuskan tampil login atau dashboard."""
    return {"authenticated": verify_session_token(tuyabot_session)}


@router.get("/stream")
async def stream(request: Request):
    """SSE: kirim status perangkat dari cache, tanpa memicu I/O perangkat.

    Pengambilan data dari perangkat tetap tugas scheduler (cache-warm). Endpoint
    ini hanya membaca `state_cache`, jadi sepuluh tab dashboard tidak menambah
    beban apa pun ke perangkat.
    """

    async def event_generator():
        last_payload = None
        while True:
            if await request.is_disconnected():
                break
            payload = _live_snapshot()
            serialized = json.dumps(payload, separators=(",", ":"))
            if serialized != last_payload:
                last_payload = serialized
                yield f"data: {serialized}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _live_snapshot() -> dict:
    """Susun snapshot dari cache: status, daya, dan umur datanya."""
    devices: dict[str, dict] = {}
    for name in DEVICES:
        status = cache.read(name, "status") or {}
        power = cache.read(name, "power") or {}
        raw_dps = status.get("status")
        dps: dict = raw_dps if isinstance(raw_dps, dict) else {}
        switch_key = str(DEVICES[name].get("dps_switch", 1))
        devices[name] = {
            "online": bool(status.get("success")),
            "message": status.get("message"),
            "switch_on": bool(dps.get(switch_key)) if switch_key in dps else None,
            "status_age_s": round(cache.age((name, "status")) or 0, 1),
            "power_w": power.get("power_w") if power.get("success") else None,
            "voltage_v": power.get("voltage_v") if power.get("success") else None,
            "current_a": power.get("current_a") if power.get("success") else None,
            "power_age_s": round(cache.age((name, "power")) or 0, 1),
        }
    return {"ts": time.time(), "devices": devices}


def _switch_from_dps(name: str, dps: dict) -> bool | None:
    if not isinstance(dps, dict):
        return None
    key = str(DEVICES[name].get("dps_switch", 1))
    if key not in dps:
        return None
    return bool(dps[key])


@router.get("/health", response_model=HealthResponse)
async def health():
    """Readiness: database bisa dihubungi + ada data perangkat yang belum basi."""
    db_ok = await run_db(database.ping)
    states = cache.snapshot()
    devices_ok = any(item["success"] for item in states.values()) if states else False
    if db_ok and devices_ok:
        status = "ok"
    elif db_ok:
        status = "degraded"
    else:
        status = "down"
    return HealthResponse(status=status, database=db_ok, devices=devices_ok, cache=states)


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices():
    return DeviceListResponse(devices=tuya.list_devices())


@router.get("/devices/{name}/status", response_model=DeviceStatusResponse)
async def device_status(name: str):
    if name not in get_device_names():
        raise HTTPException(status_code=404, detail=f"Perangkat '{name}' tidak ditemukan")

    result = await get_status(name)
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
    result = await get_power("air")
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
    cache.invalidate(name)
    if result.get("success"):
        # Isi cache lagi segera: tanpa ini dashboard menampilkan status lama
        # (atau "offline") sampai job cache-warm berikutnya berjalan.
        await get_status(name, force=True)

    try:
        status_str = "success" if result.get("success") else "failed"
        await run_db(
            database.log_activity,
            user_id=0,
            user_role="api",
            device_name=name,
            action="turn_on" if state else "turn_off",
            status=status_str,
            message=result.get("message", ""),
        )
    except Exception as e:
        logger.warning("[API] Gagal mencatat aktivitas kontrol ke database: %s", e)

    return ControlResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        no_op=result.get("no_op", False),
    )


# ── Database & Telemetry Endpoints ──


@router.get("/db/stats")
async def get_database_stats():
    """Statistik ringkas database & retensi log."""
    return await run_db(database.get_db_stats)


@router.get("/db/power-logs")
async def get_power_logs(limit: int = 50, device: str | None = None):
    """Ambil data konsumsi daya terbaru dari device_power_logs."""
    limit = max(1, min(limit, 200))
    return await run_db(database.get_recent_power_logs, device_name=device, limit=limit)


@router.get("/db/activities")
async def get_activity_logs(limit: int = 50):
    """Ambil riwayat aktivitas kontrol perangkat dari device_activity_logs."""
    limit = max(1, min(limit, 200))
    return await run_db(database.get_recent_activities, limit=limit)


@router.get("/db/users")
async def get_users_list():
    """Daftar user ENV & runtime serta daftar penerima notifikasi air."""
    details = await run_db(auth.list_users_detailed)
    recipients = list(await run_db(auth.get_air_notify_recipient_ids))
    return {
        "env": details.get("env", {}),
        "runtime": details.get("runtime", []),
        "air_recipients": recipients,
    }


@router.get("/db/errors")
async def get_error_logs(limit: int = 50):
    """Ambil log error aplikasi dari app_error_logs."""
    limit = max(1, min(limit, 200))
    return await run_db(database.get_recent_app_errors, limit=limit)


@router.post("/db/cleanup")
async def cleanup_database(retention_days: int | None = None):
    """Jalankan pembersihan log database (housekeeping) secara manual."""
    res = await run_db(database.cleanup_old_logs, retention_days=retention_days)
    return {
        "success": True,
        "message": f"Pembersihan database selesai: {sum(res.values())} baris log dihapus",
        "details": res,
    }


