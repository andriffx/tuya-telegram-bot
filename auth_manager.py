"""
Role-based Access Control (RBAC) untuk bot Telegram.

Role:
    0 = PUBLIC   → /start, /help, /whoami (info saja)
    1 = USER     → + kontrol AIR (on/off)
    2 = ADMIN    → + kontrol LAMPU (on/off)
    3 = SUPERADMIN → + /users, /allowuser, /removeuser

ENV:
    SUPERADMIN_USERS=111,222
    ADMIN_USERS=333,444
    USER_USERS=555,666
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, Set

logger = logging.getLogger(__name__)

USERS_FILE = Path("users_db.json")

# ── Konstanta Role ──
PUBLIC = 0
USER = 1
ADMIN = 2
SUPERADMIN = 3

ROLE_NAMES = {
    PUBLIC: "Publik",
    USER: "User",
    ADMIN: "Admin",
    SUPERADMIN: "Superadmin"
}


def _parse_ids(key: str) -> Set[int]:
    raw = os.getenv(key, "").strip()
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


# ── Load dari ENV ──
ENV_SUPERADMIN = _parse_ids("SUPERADMIN_USERS")
ENV_ADMIN = _parse_ids("ADMIN_USERS")
ENV_USER = _parse_ids("USER_USERS")


def _env_role(uid: int) -> int:
    """Tentukan role dari ENV."""
    if uid in ENV_SUPERADMIN:
        return SUPERADMIN
    if uid in ENV_ADMIN:
        return ADMIN
    if uid in ENV_USER:
        return USER
    return PUBLIC


class AuthManager:
    """Kelola user dengan role."""

    def __init__(self):
        # runtime store: {user_id: role_int}
        self._db: Dict[int, int] = {}
        self._load()

    def _load(self):
        if USERS_FILE.exists() and USERS_FILE.stat().st_size > 0:
            try:
                data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
                for uid, role in data.get("users", {}).items():
                    self._db[int(uid)] = int(role)
                logger.info("Loaded %d user(s) from %s", len(self._db), USERS_FILE)
            except Exception as e:
                logger.warning("Gagal muat %s: %s", USERS_FILE, e)
        else:
            # Inisialisasi file kosong dengan struktur valid
            try:
                USERS_FILE.write_text(
                    json.dumps({"users": {}}, indent=2),
                    encoding="utf-8"
                )
                logger.info("Created empty %s", USERS_FILE)
            except Exception as e:
                logger.warning("Gagal buat %s: %s", USERS_FILE, e)

    def _save(self):
        try:
            # Jangan simpan yang berasal dari ENV (ENV adalah source of truth)
            runtime = {
                str(uid): role
                for uid, role in self._db.items()
                if _env_role(uid) == PUBLIC  # hanya runtime overrides
            }
            USERS_FILE.write_text(
                json.dumps({"users": runtime}, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Gagal simpan %s: %s", USERS_FILE, e)

    # ── API Publik ──

    def get_role(self, user_id: int) -> int:
        """Ambil role user (ENV override runtime)."""
        env = _env_role(user_id)
        if env != PUBLIC:
            return env
        return self._db.get(user_id, PUBLIC)

    def role_name(self, user_id: int) -> str:
        return ROLE_NAMES.get(self.get_role(user_id), "Publik")

    def is_public(self, user_id: int) -> bool:
        return self.get_role(user_id) == PUBLIC

    def is_user(self, user_id: int) -> bool:
        return self.get_role(user_id) >= USER

    def is_admin(self, user_id: int) -> bool:
        return self.get_role(user_id) >= ADMIN

    def is_superadmin(self, user_id: int) -> bool:
        return self.get_role(user_id) >= SUPERADMIN

    def set_role(self, target_id: int, role: int) -> bool:
        """Set role user. Tidak bisa override ENV user."""
        if _env_role(target_id) != PUBLIC:
            return False  # ENV user tidak bisa diubah runtime
        self._db[target_id] = role
        self._save()
        return True

    def remove_user(self, target_id: int) -> bool:
        """Hapus user dari runtime DB."""
        if _env_role(target_id) != PUBLIC:
            return False
        if target_id not in self._db:
            return False
        del self._db[target_id]
        self._save()
        return True

    def get_superadmin_ids(self) -> set:
        """Return semua user ID dengan role Superadmin (ENV + runtime)."""
        ids = set(ENV_SUPERADMIN)
        for uid, role in self._db.items():
            if role == SUPERADMIN:
                ids.add(uid)
        return ids

    def list_users(self) -> dict:
        env_map = {}
        for uid in ENV_SUPERADMIN:
            env_map[uid] = SUPERADMIN
        for uid in ENV_ADMIN:
            env_map[uid] = ADMIN
        for uid in ENV_USER:
            env_map[uid] = USER

        runtime_map = {
            uid: role
            for uid, role in self._db.items()
            if uid not in env_map
        }

        return {
            "env": env_map,
            "runtime": runtime_map
        }


# Singleton
auth = AuthManager()
