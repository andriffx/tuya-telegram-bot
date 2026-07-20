"""Dependency injection untuk REST API."""

import os
import secrets

from fastapi import Header, HTTPException

from config import DEVICES

DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")


async def verify_api_key(x_api_key: str = Header(default="", alias="X-API-Key")):
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="Layanan belum dikonfigurasi")
    if not x_api_key or not secrets.compare_digest(x_api_key, DASHBOARD_API_KEY):
        raise HTTPException(status_code=401, detail="API key tidak valid")


def get_device_names() -> set[str]:
    return set(DEVICES.keys())
