"""Autentikasi dashboard: API key lewat header atau session cookie.

Kenapa cookie: `EventSource` (SSE) tidak bisa mengirim header kustom, dan API key
yang disimpan di `localStorage` otomatis bocor kalau ada XSS di dashboard. Cookie
ditandatangani (HMAC) dan tanpa state — tidak ada tabel sesi yang perlu dirawat.

API key tetap diterima lewat `X-API-Key` untuk skrip/curl dan untuk halaman login.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Cookie, Header, HTTPException, Response

SESSION_COOKIE = "tuyabot_session"
SESSION_TTL_SECONDS = max(300, int(float(os.getenv("SESSION_TTL_HOURS", "12")) * 3600))
COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def _secret() -> bytes:
    """Kunci tanda tangan sesi: SESSION_SECRET bila ada, kalau tidak turunan API key."""
    from .deps import DASHBOARD_API_KEY

    raw = os.getenv("SESSION_SECRET") or DASHBOARD_API_KEY
    if not raw:
        raise HTTPException(status_code=503, detail="Layanan belum dikonfigurasi")
    return hashlib.sha256(raw.encode()).digest()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(ttl: int = SESSION_TTL_SECONDS) -> str:
    payload = json.dumps({"exp": int(time.time()) + ttl}).encode()
    signature = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return f"{_b64e(payload)}.{_b64e(signature)}"


def verify_session_token(token: str | None) -> bool:
    if not token or token.count(".") != 1:
        return False
    payload_b64, signature_b64 = token.split(".")
    try:
        payload = _b64d(payload_b64)
        signature = _b64d(signature_b64)
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        data = json.loads(payload)
        return int(data.get("exp", 0)) > int(time.time())
    except Exception:
        return False


def check_api_key(candidate: str) -> bool:
    from .deps import DASHBOARD_API_KEY

    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="Layanan belum dikonfigurasi")
    return bool(candidate) and secrets.compare_digest(candidate, DASHBOARD_API_KEY)


async def require_auth(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    tuyabot_session: str | None = Cookie(default=None),
) -> None:
    """Dependency: lolos bila API key valid ATAU cookie sesi valid."""
    from .deps import DASHBOARD_API_KEY

    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="Layanan belum dikonfigurasi")
    if x_api_key and secrets.compare_digest(x_api_key, DASHBOARD_API_KEY):
        return
    if verify_session_token(tuyabot_session):
        return
    raise HTTPException(status_code=401, detail="Tidak terautentikasi")


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
