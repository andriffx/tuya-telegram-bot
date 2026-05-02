"""
Rate Limiter — proteksi bot dari spam & abuse.

Menggunakan sliding window:
  • Catat timestamp setiap request per user
  • Hapus timestamp yang sudah lewat window
  • Jika jumlah dalam window > limit → tolak

ENV:
    RATE_LIMIT_PUBLIC=10   # request per menit
    RATE_LIMIT_USER=30
    RATE_LIMIT_ADMIN=60
    RATE_LIMIT_SUPERADMIN=120
    RATE_LIMIT_WINDOW=60   # detik
"""

import os
import time
import logging
from collections import defaultdict
from typing import Dict, List, Callable

logger = logging.getLogger(__name__)

# ── Konfigurasi ──
WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
LIMITS = {
    "public":    int(os.getenv("RATE_LIMIT_PUBLIC",    "10")),
    "user":      int(os.getenv("RATE_LIMIT_USER",      "30")),
    "admin":     int(os.getenv("RATE_LIMIT_ADMIN",     "60")),
    "superadmin":int(os.getenv("RATE_LIMIT_SUPERADMIN","120")),
}

# In-memory store: {user_id: [timestamp1, timestamp2, ...]}
_buckets: Dict[int, List[float]] = defaultdict(list)


def _cleanup(uid: int, now: float) -> int:
    """Hapus timestamp yang sudah lewat window, return count aktif."""
    cutoff = now - WINDOW
    active = [ts for ts in _buckets[uid] if ts > cutoff]
    _buckets[uid] = active
    return len(active)


def check_rate_limit(uid: int, role: str) -> tuple[bool, int, int]:
    """
    Cek apakah user masih dalam batas rate limit.

    Returns:
        (allowed: bool, current: int, limit: int)
    """
    now = time.time()
    limit = LIMITS.get(role.lower(), LIMITS["user"])
    current = _cleanup(uid, now)

    if current >= limit:
        logger.warning("Rate limit hit: uid=%s role=%s %d/%d", uid, role, current, limit)
        return False, current, limit

    _buckets[uid].append(now)
    return True, current + 1, limit


def rate_limit(func: Callable) -> Callable:
    """
    Decorator untuk menerapkan rate limit pada handler Telegram.

    Fungsi yang di-wrap harus menerima (update, context) dan
    bisa mengakses auth_manager untuk cek role.
    """
    from auth_manager import auth  # lazy import agar tidak circular

    async def wrapper(update, context):
        uid = update.effective_user.id
        role = auth.role_name(uid).lower()  # "publik", "user", "admin", "superadmin"
        allowed, current, limit = check_rate_limit(uid, role)

        if not allowed:
            retry_after = WINDOW - (time.time() - _buckets[uid][0])
            await update.message.reply_text(
                f"⏳ *Rate Limit*\n\n"
                f"Anda terlalu sering menggunakan command.\n"
                f"`{current}/{limit}` request dalam {WINDOW} detik.\n\n"
                f"Coba lagi dalam `{int(retry_after)}` detik.",
                parse_mode="Markdown"
            )
            return

        return await func(update, context)
    return wrapper
