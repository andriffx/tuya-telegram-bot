"""
Telegram Bot — Tuya Smart Home (BARDI) dengan Role-Based Access Control.
UI: ReplyKeyboardMarkup + InlineKeyboardMarkup (command / tetap tersedia sebagai fallback)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from functools import partial
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from tuya_controller import TuyaDeviceController
from auth_manager import auth, ROLE_NAMES, PUBLIC, USER, ADMIN, SUPERADMIN
from rate_limiter import rate_limit

# ── Logging ke file + console ──
handlers: list[logging.Handler] = [logging.StreamHandler()]
try:
    os.makedirs("logs", exist_ok=True)
    handlers.append(logging.FileHandler("logs/bot.log", encoding="utf-8"))
except (PermissionError, OSError) as e:
    print(f"[WARN] Tidak bisa buat file log: {e}. Logging ke console saja.", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=handlers
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

tuya = TuyaDeviceController()

# Thread pool untuk operasi Tuya (blocking I/O) — jangan block event loop asyncio
_tuya_executor = None


def _get_tuya_executor():
    global _tuya_executor
    if _tuya_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _tuya_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tuya")
    return _tuya_executor


async def _run_tuya(fn, *args, **kwargs):
    """Jalankan operasi Tuya di thread terpisah agar polling Telegram tetap responsif."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _get_tuya_executor(),
        partial(fn, *args, **kwargs),
    )

# ═══════════════════════════════════════════════════════
#  KEYBOARD BUILDERS
# ═══════════════════════════════════════════════════════

def _main_keyboard(role: int) -> ReplyKeyboardMarkup:
    """Menu utama sesuai role."""
    if role == PUBLIC:
        kb = [["🪪 Akun Saya"], ["📖 Bantuan"]]
    elif role == USER:
        kb = [["💧 Air"], ["📊 Monitoring"], ["🪪 Akun Saya"]]
    elif role == ADMIN:
        kb = [["💧 Air", "💡 Lampu"], ["📊 Monitoring"], ["🪪 Akun Saya"]]
    else:  # SUPERADMIN
        kb = [
            ["💧 Air", "💡 Lampu"],
            ["📊 Monitoring"],
            ["👑 Manajemen User"],
            ["🪪 Akun Saya"],
        ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def _air_inline(role: int) -> InlineKeyboardMarkup:
    btns = []
    if role >= USER:
        btns.append(InlineKeyboardButton("🟢 Nyalakan", callback_data="air|on"))
    if role >= ADMIN:
        btns.append(InlineKeyboardButton("🔴 Matikan", callback_data="air|off"))
    rows = [btns] if btns else []
    rows.append([InlineKeyboardButton("ℹ️ Status", callback_data="air|status")])
    return InlineKeyboardMarkup(rows)


def _lampu_inline(role: int) -> InlineKeyboardMarkup:
    if role < ADMIN:
        return InlineKeyboardMarkup([])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Nyalakan", callback_data="lampu|on"),
            InlineKeyboardButton("🔴 Matikan", callback_data="lampu|off"),
        ],
        [InlineKeyboardButton("ℹ️ Status", callback_data="lampu|status")],
    ])


def _monitoring_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Status Perangkat IOT", callback_data="mon|status")],
        [InlineKeyboardButton("📱 Daftar Perangkat", callback_data="mon|devices")],
    ])


def _users_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Daftar User", callback_data="users|list")],
        [
            InlineKeyboardButton("➕ Tambah User", callback_data="users|add"),
            InlineKeyboardButton("➖ Hapus User", callback_data="users|remove"),
        ],
    ])


def _role_select_inline(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💧 User", callback_data=f"role|{target_id}|1"),
            InlineKeyboardButton("💡 Admin", callback_data=f"role|{target_id}|2"),
        ],
    ])


# ═══════════════════════════════════════════════════════
#  DECORATORS
# ═══════════════════════════════════════════════════════

def require_role(min_role: int, action_name: str = "command ini"):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            uid = update.effective_user.id
            role = auth.get_role(uid)
            if role >= min_role:
                return await func(update, context)
            if role == PUBLIC:
                await update.message.reply_text(
                    f"🚫 *Akses ditolak*\n\n"
                    f"Anda belum memiliki akses.\n"
                    f"`User ID: {uid}`\n\n"
                    f"Hubungi superadmin untuk mendapatkan akses.",
                    parse_mode="Markdown",
                    reply_markup=_main_keyboard(role),
                )
            elif role == USER and min_role == ADMIN:
                await update.message.reply_text(
                    f"⛔ *Admin only*\n\n"
                    f"Anda adalah *User* — hanya bisa kontrol **AIR**.\n"
                    f"Kontrol lampu memerlukan role **Admin**.",
                    parse_mode="Markdown",
                    reply_markup=_main_keyboard(role),
                )
            else:
                await update.message.reply_text(
                    f"⛔ *Akses ditolak*\n\n"
                    f"Anda tidak memiliki izin untuk {action_name}.",
                    parse_mode="Markdown",
                    reply_markup=_main_keyboard(role),
                )
            logger.warning("User %s (role=%s) ditolak untuk %s", uid, ROLE_NAMES.get(role), action_name)
            return
        return wrapper
    return decorator


public_only   = lambda f: require_role(PUBLIC)(f)
user_only     = lambda f: require_role(USER)(f)
admin_only    = lambda f: require_role(ADMIN)(f)
superadmin_only = lambda f: require_role(SUPERADMIN)(f)


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def _is_network_error(result: dict) -> bool:
    msg = result.get("message", "").lower()
    return any(k in msg for k in ["unable to connect", "network error", "timeout", "connection refused"])


def _control_result_text(result: dict, device_name: str) -> tuple[str, str | None]:
    """Return (text, parse_mode) untuk pesan hasil kontrol perangkat."""
    if result["success"]:
        return result["message"], None
    if _is_network_error(result):
        return (
            f"❌ *{device_name.upper()} tidak terhubung*\n\n"
            f"_Error:_ `{result.get('message', 'Network Error')}`\n\n"
            f"🔍 *Cek:*\n"
            f"• Bot & perangkat di jaringan WiFi yang sama?\n"
            f"• Perangkat masih nyala & terhubung WiFi?\n"
            f"• IP perangkat sudah benar?",
            "Markdown",
        )
    return result["message"], None


async def _finalize_control_message(message, result: dict, device_name: str, fallback_chat=None):
    """Edit pesan pending jadi hasil akhir; fallback kirim pesan baru jika edit gagal."""
    text, parse_mode = _control_result_text(result, device_name)
    try:
        await message.edit_text(text, parse_mode=parse_mode)
    except Exception as e:
        logger.warning("Gagal edit pesan kontrol: %s", e)
        if fallback_chat:
            await fallback_chat.reply_text(text, parse_mode=parse_mode)


async def _notify_superadmins(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    device_name: str,
    action: str,
    result: dict
):
    """Kirim notifikasi ke semua superadmin (skip jika superadmin yang kontrol)."""
    superadmin_ids = auth.get_superadmin_ids()
    if not superadmin_ids:
        return

    role = auth.get_role(user.id)
    if role == SUPERADMIN:
        return

    role_icon = {0: "🌐", 1: "💧", 2: "💡", 3: "👑"}.get(role, "🌐")
    role_name = ROLE_NAMES.get(role, "Publik")

    device_icon = "💧" if device_name == "air" else "💡"
    action_label = "NYALA" if action == "on" else "MATI"
    action_emoji = "🟢" if action == "on" else "🔴"

    if result.get("no_op"):
        status = "ℹ️ Sudah Menyala (tidak ada perubahan)" if action == "on" else "ℹ️ Sudah Mati (tidak ada perubahan)"
    elif result["success"]:
        status = "✅ Berhasil Dinyalakan" if action == "on" else "✅ Berhasil Dimatikan"
    else:
        action_word = "Menyalakan" if action == "on" else "Mematikan"
        status = f"❌ Gagal {action_word} — `{result.get('message', 'Unknown error')}`"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"🚨 *Notifikasi Kontrol Perangkat*\n\n"
        f"👤 *User*   : `{user.full_name}` (@{user.username or 'none'})\n"
        f"🆔 *ID*     : `{user.id}`\n"
        f"🏷️ *Role*   : {role_icon} {role_name}\n\n"
        f"🔧 *Aksi*   : {device_icon} {device_name.upper()} → {action_emoji} {action_label}\n"
        f"⏰ *Waktu*  : `{timestamp}`\n"
        f"📌 *Status* : {status}"
    )

    for admin_id in superadmin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Gagal kirim notifikasi ke superadmin %s: %s", admin_id, e)


async def _control_device_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    device_name: str,
    action: str,
    pending_msg: str,
    method,
):
    """Kontrol via inline button: kirim pending → Tuya → edit pesan jadi hasil."""
    status_msg = await query.message.reply_text(pending_msg)
    result = await _run_tuya(method, device_name)
    await _finalize_control_message(status_msg, result, device_name, query.message)
    asyncio.create_task(
        _notify_superadmins(context, query.from_user, device_name, action, result)
    )


async def _control_device_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    device_name: str,
    action: str,
    pending_msg: str,
    method,
):
    """Kontrol via command: kirim pending → Tuya → edit pesan jadi hasil."""
    status_msg = await update.message.reply_text(pending_msg)
    result = await _run_tuya(method, device_name)
    await _finalize_control_message(status_msg, result, device_name, update.message)
    asyncio.create_task(
        _notify_superadmins(context, update.effective_user, device_name, action, result)
    )


# ═══════════════════════════════════════════════════════
#  COMMANDS (fallback)
# ═══════════════════════════════════════════════════════

@rate_limit
@public_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — bersihkan pending state dan tampilkan menu utama."""
    context.user_data.clear()
    user = update.effective_user.first_name
    uid = update.effective_user.id
    role = auth.get_role(uid)

    await update.message.reply_text(
        f"👋 Halo {user}!\n\n"
        f"🤖 *Bot Smart Home BARDI*\n"
        f"Role Anda: *{ROLE_NAMES[role]}*\n\n"
        f"Pilih menu di bawah untuk mulai:",
        parse_mode="Markdown",
        reply_markup=_main_keyboard(role),
    )


@rate_limit
@public_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    role = auth.get_role(uid)
    icon = {PUBLIC: "🌐", USER: "💧", ADMIN: "💡", SUPERADMIN: "👑"}.get(role, "🌐")

    lines = [
        f"📖 *Panduan — {icon} {ROLE_NAMES[role]}*\n",
        "Gunakan tombol menu di bawah untuk mengakses fitur bot.\n",
        "*📋 Menu Utama:*",
        "• 💧 Air — Kontrol smart plug",
        "• 💡 Lampu — Kontrol lampu",
        "• 📊 Monitoring — Cek status perangkat",
        "• 🪪 Akun Saya — Lihat ID & role Anda",
    ]
    if role == SUPERADMIN:
        lines.append("• 👑 Manajemen User — Kelola akses user")

    lines.extend([
        "\n*💡 Tips:*",
        "Ketik `/start` kapan saja untuk kembali ke menu utama.",
    ])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=_main_keyboard(role),
    )


@rate_limit
@public_only
async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    role = auth.get_role(user.id)
    role_icon = {PUBLIC: "🌐", USER: "💧", ADMIN: "💡", SUPERADMIN: "👑"}.get(role, "🌐")

    await update.message.reply_text(
        f"🪪 *Informasi Akun Anda*\n\n"
        f"*Nama*    : `{user.full_name}`\n"
        f"*User ID* : `{user.id}`\n"
        f"*Username*: `@{user.username or 'none'}`\n\n"
        f"*Role*    : {role_icon} *{ROLE_NAMES[role]}*\n\n"
        f"_User ID di atas bisa Anda kirim ke superadmin untuk minta akses._",
        parse_mode="Markdown",
        reply_markup=_main_keyboard(role),
    )


# ═══════════════════════════════════════════════════════
#  LEGACY DEVICE COMMANDS (fallback)
# ═══════════════════════════════════════════════════════

@rate_limit
@user_only
async def air_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _control_device_command(
        update, context, "air", "on", "💧 Menyalakan air...", tuya.turn_on
    )


@rate_limit
@admin_only
async def air_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _control_device_command(
        update, context, "air", "off", "🔌 Mematikan air...", tuya.turn_off
    )


@rate_limit
@admin_only
async def lampu_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _control_device_command(
        update, context, "lampu", "on", "💡 Menyalakan lampu...", tuya.turn_on
    )


@rate_limit
@admin_only
async def lampu_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _control_device_command(
        update, context, "lampu", "off", "🌑 Mematikan lampu...", tuya.turn_off
    )


@rate_limit
@user_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Mengecek status perangkat...")
    lines = ["📊 *Status Perangkat*\n"]
    for name, label, emoji in [("lampu", "Lampu", "💡"), ("air", "Air", "💧")]:
        result = await _run_tuya(tuya.get_status, name)
        if result["success"]:
            dps = result.get("status", {})
            if isinstance(dps, dict):
                switch_val = dps.get("20") if name == "lampu" else dps.get("1")
                state = "🟢 NYALA" if switch_val else "🔴 MATI"
            else:
                state = "⚪ Tidak diketahui"
        else:
            state = "⚪ Offline"
        lines.append(f"{emoji} *{label}*: {state}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@rate_limit
@user_only
async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    devices = tuya.list_devices()
    lines = ["📱 *Perangkat Tersedia*\n"]
    for dev in devices:
        icon = "💡" if dev["type"] == "bulb" else "🔌"
        tipe = "Lampu" if dev["type"] == "bulb" else "Smart Plug"
        lines.append(f"{icon} *{dev['name'].title()}* — {tipe}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════
#  SUPERADMIN COMMANDS (fallback)
# ═══════════════════════════════════════════════════════

@rate_limit
@superadmin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = auth.list_users()
    lines = ["👥 *Daftar User*\n"]

    lines.append("*👑 Superadmin (ENV):*")
    for uid in sorted(data["env"].keys()):
        if data["env"][uid] == SUPERADMIN:
            lines.append(f"  • `{uid}`")
    if not any(r == SUPERADMIN for r in data["env"].values()):
        lines.append("  _(kosong)_")

    lines.append("\n*💡 Admin (ENV):*")
    for uid in sorted(data["env"].keys()):
        if data["env"][uid] == ADMIN:
            lines.append(f"  • `{uid}`")
    if not any(r == ADMIN for r in data["env"].values()):
        lines.append("  _(kosong)_")

    lines.append("\n*💧 User (ENV):*")
    for uid in sorted(data["env"].keys()):
        if data["env"][uid] == USER:
            lines.append(f"  • `{uid}`")
    if not any(r == USER for r in data["env"].values()):
        lines.append("  _(kosong)_")

    lines.append("\n*➕ Runtime (database):*")
    if data["runtime"]:
        for uid, role in sorted(data["runtime"].items()):
            lines.append(f"  • `{uid}` → {ROLE_NAMES.get(role, '?')}")
    else:
        lines.append("  _(kosong)_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@rate_limit
@superadmin_only
async def allowuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "ℹ️ *Cara pakai:*\n"
            "`/allowuser <user_id> 1` — Jadikan 💧 User\n"
            "`/allowuser <user_id> 2` — Jadikan 💡 Admin\n\n"
            "_User bisa cek ID mereka via 🪪 Akun Saya_",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(context.args[0].strip())
        role_input = int(context.args[1].strip()) if len(context.args) > 1 else USER
    except ValueError:
        await update.message.reply_text("❌ User ID dan role harus angka.")
        return
    if role_input not in (USER, ADMIN):
        await update.message.reply_text(
            "❌ Role tidak valid.\n\n`1` = 💧 User\n`2` = 💡 Admin",
            parse_mode="Markdown"
        )
        return
    if auth.set_role(target_id, role_input):
        rname = ROLE_NAMES[role_input]
        await update.message.reply_text(
            f"✅ User `{target_id}` berhasil di-set sebagai *{rname}*.",
            parse_mode="Markdown"
        )
        logger.info("Superadmin %s set user %s as %s", update.effective_user.id, target_id, rname)
    else:
        await update.message.reply_text(
            "❌ Gagal. User mungkin sudah di-set via ENV.",
            parse_mode="Markdown"
        )


@rate_limit
@superadmin_only
async def removeuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ℹ️ *Cara pakai:* `/removeuser <user_id>`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("❌ User ID harus angka.")
        return
    if auth.remove_user(target_id):
        await update.message.reply_text(f"✅ User `{target_id}` dihapus.", parse_mode="Markdown")
        logger.info("Superadmin %s hapus user %s", update.effective_user.id, target_id)
    else:
        await update.message.reply_text(
            "❌ Gagal. User mungkin tidak ada, atau berasal dari ENV.",
            parse_mode="Markdown"
        )


# ═══════════════════════════════════════════════════════
#  MENU HANDLER (ReplyKeyboard)
# ═══════════════════════════════════════════════════════

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle tombol menu utama."""
    text = update.message.text.strip()
    uid = update.effective_user.id
    role = auth.get_role(uid)

    # ── Interactive flow: tambah user ──
    if context.user_data.get("awaiting_add_user_id"):
        await _flow_add_user_id(update, context)
        return

    # ── Interactive flow: hapus user ──
    if context.user_data.get("awaiting_remove_user_id"):
        await _flow_remove_user_id(update, context)
        return

    # ── 💧 Air ──
    if text == "💧 Air":
        if role < USER:
            await update.message.reply_text(
                "🚫 Anda belum memiliki akses kontrol air.",
                reply_markup=_main_keyboard(role),
            )
            return
        await update.message.reply_text(
            "💧 *Kontrol Air*\nPilih aksi:",
            parse_mode="Markdown",
            reply_markup=_air_inline(role),
        )

    # ── 💡 Lampu ──
    elif text == "💡 Lampu":
        if role < ADMIN:
            await update.message.reply_text(
                "⛔ Anda tidak memiliki akses kontrol lampu.",
                reply_markup=_main_keyboard(role),
            )
            return
        await update.message.reply_text(
            "💡 *Kontrol Lampu*\nPilih aksi:",
            parse_mode="Markdown",
            reply_markup=_lampu_inline(role),
        )

    # ── 📊 Monitoring ──
    elif text == "📊 Monitoring":
        await update.message.reply_text(
            "📊 *Monitoring*\nPilih informasi:",
            parse_mode="Markdown",
            reply_markup=_monitoring_inline(),
        )

    # ── 🪪 Akun Saya ──
    elif text == "🪪 Akun Saya":
        await whoami_command(update, context)

    # ── 👑 Manajemen User ──
    elif text == "👑 Manajemen User":
        if role < SUPERADMIN:
            await update.message.reply_text(
                "⛔ Akses ditolak.",
                reply_markup=_main_keyboard(role),
            )
            return
        await update.message.reply_text(
            "👑 *Manajemen User*\nPilih aksi:",
            parse_mode="Markdown",
            reply_markup=_users_inline(),
        )

    # ── 📖 Bantuan ──
    elif text == "📖 Bantuan":
        await help_command(update, context)

    # ── Unknown text ──
    else:
        await unknown_message(update, context)


# ═══════════════════════════════════════════════════════
#  CALLBACK HANDLER (InlineKeyboard)
# ═══════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Jawab segera agar tombol tidak loading — hanya boleh answer() sekali per callback
    try:
        await query.answer()
    except Exception as e:
        logger.warning("Gagal answer callback %s: %s", query.data, e)

    data = query.data
    uid = update.effective_user.id
    role = auth.get_role(uid)

    try:
        if data.startswith("air|"):
            await _callback_air(query, context, data.split("|")[1], role)
        elif data.startswith("lampu|"):
            await _callback_lampu(query, context, data.split("|")[1], role)
        elif data.startswith("mon|"):
            await _callback_mon(query, context, data.split("|")[1])
        elif data.startswith("users|"):
            await _callback_users(query, context, data.split("|")[1], role)
        elif data.startswith("role|"):
            _, target_id, role_input = data.split("|")
            await _callback_role_confirm(query, context, int(target_id), int(role_input))
        elif data == "back|main":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.edit_message_text(
                    "🏠 *Menu Utama*\nPilih menu di bawah:",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
    except Exception as e:
        logger.error("Error callback %s: %s", data, e)
        try:
            await query.message.reply_text("⚠️ Terjadi kesalahan. Coba lagi.")
        except Exception:
            pass


# ── Callback: Air ──
async def _callback_air(query, context, action: str, role: int):
    if action == "on" and role >= USER:
        await _control_device_callback(
            query, context, "air", "on", "💧 Menyalakan air...", tuya.turn_on
        )
    elif action == "off" and role >= ADMIN:
        await _control_device_callback(
            query, context, "air", "off", "🔌 Mematikan air...", tuya.turn_off
        )
    elif action == "status":
        result = await _run_tuya(tuya.get_power_info, "air")
        if result["success"]:
            dps = result.get("raw", {})
            switch_val = dps.get("1") if isinstance(dps, dict) else None
            state = "🟢 NYALA" if switch_val else "🔴 MATI"
            await query.message.reply_text(
                f"💧 *Status Air*: {state}\n"
                f"⚡ *COK AIR - Power Monitor*\n\n"
                f"🔌 *Daya*    : `{result['power_w']}` W\n"
                f"⚡ *Arus*    : `{result['current_a']}` A\n"
                f"🔋 *Voltase* : `{result['voltage_v']}` V",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text("❌ Gagal membaca status air.")
    else:
        await query.message.reply_text("⛔ Akses ditolak.")


# ── Callback: Lampu ──
async def _callback_lampu(query, context, action: str, role: int):
    if role < ADMIN:
        await query.message.reply_text("⛔ Admin only.")
        return
    if action == "on":
        await _control_device_callback(
            query, context, "lampu", "on", "💡 Menyalakan lampu...", tuya.turn_on
        )
    elif action == "off":
        await _control_device_callback(
            query, context, "lampu", "off", "🌑 Mematikan lampu...", tuya.turn_off
        )
    elif action == "status":
        result = await _run_tuya(tuya.get_status, "lampu")
        if result["success"]:
            dps = result.get("status", {})
            switch_val = dps.get("20") if isinstance(dps, dict) else None
            state = "🟢 NYALA" if switch_val else "🔴 MATI"
            await query.message.reply_text(f"💡 *Status Lampu*: {state}", parse_mode="Markdown")
        else:
            await query.message.reply_text("❌ Gagal membaca status lampu.")


# ── Callback: Monitoring ──
async def _callback_mon(query, context, action: str):
    if action == "status":
        lines = ["📊 *Status Perangkat*\n"]
        for name, label, emoji in [("lampu", "Lampu", "💡"), ("air", "Air", "💧")]:
            result = await _run_tuya(tuya.get_status, name)
            if result["success"]:
                dps = result.get("status", {})
                if isinstance(dps, dict):
                    switch_val = dps.get("20") if name == "lampu" else dps.get("1")
                    state = "🟢 NYALA" if switch_val else "🔴 MATI"
                else:
                    state = "⚪ Tidak diketahui"
            else:
                state = "⚪ Offline"
            lines.append(f"{emoji} *{label}*: {state}")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif action == "devices":
        devices = tuya.list_devices()
        lines = ["📱 *Perangkat Tersedia*\n"]
        for dev in devices:
            icon = "💡" if dev["type"] == "bulb" else "🔌"
            tipe = "Lampu" if dev["type"] == "bulb" else "Smart Plug"
            lines.append(f"{icon} *{dev['name'].title()}* — {tipe}")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Callback: Users ──
async def _callback_users(query, context, action: str, role: int):
    if role < SUPERADMIN:
        await query.message.reply_text("⛔ Superadmin only.")
        return

    if action == "list":
        data = auth.list_users()
        lines = ["👥 *Daftar User*\n"]
        lines.append("*👑 Superadmin (ENV):*")
        for uid in sorted(data["env"].keys()):
            if data["env"][uid] == SUPERADMIN:
                lines.append(f"  • `{uid}`")
        if not any(r == SUPERADMIN for r in data["env"].values()):
            lines.append("  _(kosong)_")

        lines.append("\n*💡 Admin (ENV):*")
        for uid in sorted(data["env"].keys()):
            if data["env"][uid] == ADMIN:
                lines.append(f"  • `{uid}`")
        if not any(r == ADMIN for r in data["env"].values()):
            lines.append("  _(kosong)_")

        lines.append("\n*💧 User (ENV):*")
        for uid in sorted(data["env"].keys()):
            if data["env"][uid] == USER:
                lines.append(f"  • `{uid}`")
        if not any(r == USER for r in data["env"].values()):
            lines.append("  _(kosong)_")

        lines.append("\n*➕ Runtime (database):*")
        if data["runtime"]:
            for uid, role_val in sorted(data["runtime"].items()):
                lines.append(f"  • `{uid}` → {ROLE_NAMES.get(role_val, '?')}")
        else:
            lines.append("  _(kosong)_")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif action == "add":
        await query.message.reply_text(
            "➕ *Tambah User*\n\n"
            "Kirimkan *User ID* yang ingin ditambahkan.\n"
            "User bisa cek ID mereka via menu 🪪 Akun Saya.\n\n"
            "_Ketik ID sebagai angka, contoh: `8559106318`_",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_add_user_id"] = True

    elif action == "remove":
        await query.message.reply_text(
            "➖ *Hapus User*\n\n"
            "Kirimkan *User ID* yang ingin dihapus.\n\n"
            "_Ketik ID sebagai angka._",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_remove_user_id"] = True


async def _callback_role_confirm(query, context, target_id: int, role_input: int):
    if role_input not in (USER, ADMIN):
        await query.message.reply_text("❌ Role tidak valid.")
        return
    if auth.set_role(target_id, role_input):
        rname = ROLE_NAMES[role_input]
        await query.edit_message_text(
            f"✅ User `{target_id}` berhasil di-set sebagai *{rname}*.",
            parse_mode="Markdown",
        )
        logger.info("Superadmin %s set user %s as %s", query.from_user.id, target_id, rname)
    else:
        await query.edit_message_text(
            "❌ Gagal. User mungkin sudah di-set via ENV.",
            parse_mode="Markdown",
        )


# ═══════════════════════════════════════════════════════
#  INTERACTIVE FLOWS (text input setelah tombol inline)
# ═══════════════════════════════════════════════════════

async def _flow_add_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop("awaiting_add_user_id", None)
    role = auth.get_role(update.effective_user.id)

    try:
        target_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "❌ ID harus berupa angka. Coba lagi.",
            reply_markup=_users_inline(),
        )
        return

    if auth.get_role(target_id) != PUBLIC:
        await update.message.reply_text(
            f"⚠️ User `{target_id}` sudah terdaftar.",
            parse_mode="Markdown",
            reply_markup=_users_inline(),
        )
        return

    await update.message.reply_text(
        f"👤 User ID: `{target_id}`\n\nPilih role:",
        parse_mode="Markdown",
        reply_markup=_role_select_inline(target_id),
    )


async def _flow_remove_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop("awaiting_remove_user_id", None)

    try:
        target_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "❌ ID harus berupa angka. Coba lagi.",
            reply_markup=_users_inline(),
        )
        return

    if auth.remove_user(target_id):
        await update.message.reply_text(
            f"✅ User `{target_id}` berhasil dihapus.",
            parse_mode="Markdown",
            reply_markup=_users_inline(),
        )
        logger.info("Superadmin %s hapus user %s", update.effective_user.id, target_id)
    else:
        await update.message.reply_text(
            "❌ Gagal. User tidak ada atau berasal dari ENV.",
            reply_markup=_users_inline(),
        )


# ═══════════════════════════════════════════════════════
#  UNKNOWN MESSAGE
# ═══════════════════════════════════════════════════════

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message.text else ""
    role = auth.get_role(update.effective_user.id)

    if text.startswith("/"):
        await update.message.reply_text(
            f"❓ *Command tidak dikenal:* `{text.split()[0]}`\n\n"
            f"Gunakan tombol menu atau ketik `/help`.",
            parse_mode="Markdown",
            reply_markup=_main_keyboard(role),
        )
    else:
        await update.message.reply_text(
            f"👋 Hai {update.effective_user.first_name}!\n\n"
            f"Saya tidak mengerti pesan itu.\n"
            f"Gunakan tombol menu di bawah atau ketik `/help`.",
            parse_mode="Markdown",
            reply_markup=_main_keyboard(role),
        )


# ═══════════════════════════════════════════════════════
#  ERROR HANDLER
# ═══════════════════════════════════════════════════════

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    logger.error("Update %s caused error %s", update, error)

    if not update:
        return

    msg = "⚠️ Terjadi kesalahan. Coba lagi nanti."
    try:
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        elif update.message:
            await update.message.reply_text(msg)
    except Exception as e:
        logger.warning("Gagal kirim pesan error ke user: %s", e)


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    from config import validate_config

    if not validate_config():
        logger.error("❌ Konfigurasi tidak lengkap.")
        return
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN belum di-set!")
        return

    logger.info("Memulai bot Telegram...")

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .build()
    )

    # ── Commands ──
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("whoami", whoami_command))

    # Legacy device commands
    application.add_handler(CommandHandler("airon", air_on))
    application.add_handler(CommandHandler("airoff", air_off))
    application.add_handler(CommandHandler("lampuon", lampu_on))
    application.add_handler(CommandHandler("lampuoff", lampu_off))

    # Legacy monitoring commands
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("devices", devices_command))

    # Legacy superadmin commands
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("allowuser", allowuser_command))
    application.add_handler(CommandHandler("removeuser", removeuser_command))

    # ── Callback Queries (inline buttons) ──
    application.add_handler(CallbackQueryHandler(callback_handler))

    # ── Text menu (ReplyKeyboard) ──
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

    # ── Fallback ──
    application.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, unknown_message))

    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
