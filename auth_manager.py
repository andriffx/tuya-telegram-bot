"""
Role-based Access Control (RBAC) untuk bot Telegram.
Menggunakan Pure Direct Query ke database MySQL eksternal (tanpa memory cache).

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

import os
import logging
from typing import Dict, List, Optional, Set, Tuple

import database

logger = logging.getLogger(__name__)

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


# ── Load dari ENV (Hanya Superadmin) ──
ENV_SUPERADMIN = _parse_ids("SUPERADMIN_USERS")


def _env_role(uid: int) -> int:
    """Tentukan role dari ENV (hanya superadmin)."""
    if uid in ENV_SUPERADMIN:
        return SUPERADMIN
    return PUBLIC



class AuthManager:
    """Kelola user dan role menggunakan query langsung ke MySQL eksternal."""

    def __init__(self):
        logger.info("AuthManager diinisialisasi dengan mode Pure Direct Query ke MySQL.")

    # ── API Publik ──

    def get_role(self, user_id: int) -> int:
        """Ambil role user (ENV override MySQL runtime)."""
        env = _env_role(user_id)
        if env != PUBLIC:
            return env

        try:
            role = database.get_user_role(user_id)
            if role is not None:
                return role
        except Exception as e:
            logger.error("[DATABASE ERROR] Gagal memeriksa role user %s dari MySQL: %s", user_id, e)

        return PUBLIC

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

    def set_role(
        self,
        target_id: int,
        role: int,
        added_by: Optional[int] = None,
        added_by_name: Optional[str] = None,
    ) -> bool:
        """Set role user di MySQL. Tidak bisa override ENV superadmin."""
        if _env_role(target_id) != PUBLIC:
            return False  # ENV superadmin tidak bisa diubah runtime
        return database.set_user_role(target_id, role, added_by=added_by, added_by_name=added_by_name)

    def remove_user(self, target_id: int) -> bool:
        """Hapus user dari runtime DB MySQL."""
        if _env_role(target_id) != PUBLIC:
            return False
        return database.remove_user(target_id)

    def get_superadmin_ids(self) -> Set[int]:
        """Return semua user ID dengan role Superadmin (ENV + runtime MySQL)."""
        ids = set(ENV_SUPERADMIN)
        try:
            runtime_users = database.get_all_runtime_users()
            for uid, role in runtime_users.items():
                if role == SUPERADMIN:
                    ids.add(uid)
        except Exception as e:
            logger.error("[DATABASE ERROR] Gagal mengambil superadmin IDs dari MySQL: %s", e)
        return ids

    def get_air_notify_recipient_ids(self) -> Set[int]:
        """Admin yang menerima notif saat role User kontrol air (MySQL runtime)."""
        return database.get_air_recipients()

    def list_air_notify_recipients(self) -> List[dict]:
        """Daftar penerima notif air dengan info role."""
        recipients = database.get_air_recipients()
        rows = []
        for uid in sorted(recipients):
            role = self.get_role(uid)
            rows.append({
                "id": uid,
                "role": role,
                "role_name": ROLE_NAMES.get(role, "?"),
            })
        return rows

    def list_all_admins(self) -> List[dict]:
        """Semua admin terdaftar (runtime MySQL), untuk referensi saat assign notif."""
        rows = []
        recipients = database.get_air_recipients()
        runtime_users = database.get_all_runtime_users()

        for uid, role in sorted(runtime_users.items()):
            if role == ADMIN:
                rows.append({
                    "id": uid,
                    "role_name": ROLE_NAMES[ADMIN],
                    "source": "runtime",
                    "is_recipient": uid in recipients,
                })
        return rows


    def add_air_notify_recipient(self, target_id: int) -> Tuple[bool, str]:
        """
        Tambah admin ke daftar penerima notif air (aksi role User).
        Hanya role Admin yang bisa ditambahkan.
        """
        role = self.get_role(target_id)
        if role != ADMIN:
            if role == SUPERADMIN:
                return False, "Superadmin sudah otomatis dapat semua notifikasi."
            if role == USER:
                return False, "User tidak bisa jadi penerima. Hanya role Admin."
            return False, "ID tidak ditemukan atau bukan Admin."

        recipients = database.get_air_recipients()
        if target_id in recipients:
            return False, "Admin sudah ada di daftar penerima."

        ok = database.add_air_recipient(target_id)
        if ok:
            return True, f"Admin `{target_id}` ditambahkan ke notif air."
        return False, "Gagal menambahkan admin ke database MySQL eksternal."

    def remove_air_notify_recipient(self, target_id: int) -> Tuple[bool, str]:
        """Hapus admin dari daftar penerima notif air."""
        recipients = database.get_air_recipients()
        if target_id not in recipients:
            return False, "ID tidak ada di daftar penerima notif air."

        ok = database.remove_air_recipient(target_id)
        if ok:
            return True, f"Admin `{target_id}` dihapus dari notif air."
        return False, "Gagal menghapus admin dari database MySQL eksternal."

    def list_users(self) -> dict:
        env_map = {uid: SUPERADMIN for uid in ENV_SUPERADMIN}
        runtime_users = database.get_all_runtime_users()
        runtime_map = {
            uid: role
            for uid, role in runtime_users.items()
            if uid not in env_map
        }

        return {
            "env": env_map,
            "runtime": runtime_map
        }

    def list_users_detailed(self) -> dict:
        env_map = {uid: SUPERADMIN for uid in ENV_SUPERADMIN}
        details = database.get_all_runtime_users_details()
        return {
            "env": env_map,
            "runtime": details
        }



# Singleton
auth = AuthManager()
