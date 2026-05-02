"""
Telegram Bot — Tuya Smart Home (BARDI) dengan Role-Based Access Control.

Role:
  Publik   → /start, /help, /whoami
  User     → + kontrol AIR (on/off)
  Admin    → + kontrol LAMPU (on/off)
  Superadmin → + manajemen user (/users, /allowuser, /removeuser)
"""

import asyncio
import logging
import os
import signal
import sys
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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
logger = logging.getLogger(__name__)

tuya = TuyaDeviceController()


# ── Decorator Role-Based ──

def require_role(min_role: int, action_name: str = "command ini"):
    """Decorator: minimal role tertentu."""
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            uid = update.effective_user.id
            role = auth.get_role(uid)
            if role >= min_role:
                return await func(update, context)

            # Pesan penolakan sesuai role
            if role == PUBLIC:
                await update.message.reply_text(
                    f"🚫 *Akses ditolak*\n\n"
                    f"Anda belum memiliki akses.\n"
                    f"`User ID: {uid}`\n\n"
                    f"Hubungi superadmin untuk mendapatkan akses.",
                    parse_mode="Markdown"
                )
            elif role == USER and min_role == ADMIN:
                await update.message.reply_text(
                    f"⛔ *Admin only*\n\n"
                    f"Anda adalah *User* — hanya bisa kontrol **AIR**.\n"
                    f"Kontrol lampu memerlukan role **Admin**.",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"⛔ *Akses ditolak*\n\n"
                    f"Anda tidak memiliki izin untuk {action_name}.",
                    parse_mode="Markdown"
                )
            logger.warning("User %s (role=%s) ditolak untuk %s", uid, ROLE_NAMES.get(role), action_name)
            return
        return wrapper
    return decorator


# Alias decorator
def public_only(func):   return require_role(PUBLIC)(func)
def user_only(func):     return require_role(USER)(func)
def admin_only(func):    return require_role(ADMIN)(func)
def superadmin_only(func): return require_role(SUPERADMIN)(func)


# ── Helper ──

def _is_network_error(result: dict) -> bool:
    msg = result.get("message", "").lower()
    return any(k in msg for k in ["unable to connect", "network error", "timeout", "connection refused"])


async def _send_control_result(update: Update, result: dict, device_name: str):
    if result["success"]:
        await update.message.reply_text(result["message"])
        return
    if _is_network_error(result):
        await update.message.reply_text(
            f"❌ *{device_name.upper()} tidak terhubung*\n\n"
            f"_Error:_ `{result.get('message', 'Network Error')}`\n\n"
            f"🔍 *Cek:*\n"
            f"• Bot & perangkat di jaringan WiFi yang sama?\n"
            f"• Perangkat masih nyala & terhubung WiFi?\n"
            f"• IP perangkat sudah benar?",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(result["message"])


# ──── PUBLIC Commands ────

@rate_limit
@public_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — semua orang."""
    user = update.effective_user.first_name
    uid = update.effective_user.id
    role = auth.role_name(uid)

    # Build command list sesuai role
    cmds = "/help  — Panduan 📖\n/whoami — Cek ID & role 🪪"
    if role == "User":
        cmds += "\n/airon  — Nyalakan air 💧"
    elif role in ("Admin", "Superadmin"):
        cmds += "\n/airon  — Nyalakan air 💧\n/airoff — Matikan air 🔌\n/lampuon — Nyalakan lampu 💡\n/lampuoff — Matikan lampu 🌑"
    if role == "Superadmin":
        cmds += "\n/users  — Manajemen user 👑"

    await update.message.reply_text(
        f"👋 Halo {user}!\n\n"
        f"🤖 *Bot Smart Home BARDI*\n"
        f"Role Anda: *{role}*\n\n"
        f"📋 *Command untuk Anda:*\n{cmds}\n\n"
        f"_Ketik /help untuk bantuan lengkap._",
        parse_mode="Markdown"
    )


@rate_limit
@public_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — tampilkan hanya command yang bisa diakses oleh role user."""
    uid = update.effective_user.id
    role = auth.get_role(uid)
    icon = {PUBLIC: "🌐", USER: "💧", ADMIN: "💡", SUPERADMIN: "👑"}.get(role, "🌐")

    lines = [f"📖 *Panduan — {icon} {ROLE_NAMES[role]}*\n"]

    # Publik
    lines.extend([
        "*ℹ️ Informasi*",
        "`/start`  — Halaman utama",
        "`/help`   — Panduan ini",
        "`/whoami` — Cek User ID & role",
    ])

    # Monitoring (semua role)
    lines.extend([
        "\n*📊 Monitoring*",
        "`/status`  — Status perangkat",
        "`/airinfo` — Daya, arus, voltase",
        "`/devices` — Info perangkat",
    ])

    # User: hanya bisa nyalakan air
    if role >= USER:
        lines.extend([
            "\n*💧 Kontrol Air*",
            "`/airon`  — Nyalakan smart plug",
        ])

    # Admin & di atasnya: bisa matikan air
    if role >= ADMIN:
        lines.extend([
            "`/airoff` — Matikan smart plug",
        ])

    # Admin & di atasnya
    if role >= ADMIN:
        lines.extend([
            "\n*💡 Kontrol Lampu*",
            "`/lampuon`  — Nyalakan lampu",
            "`/lampuoff` — Matikan lampu",
        ])

    # Superadmin saja
    if role >= SUPERADMIN:
        lines.extend([
            "\n*👑 Manajemen User*",
            "`/users`                   — Daftar semua user",
            "`/allowuser <id> <role>`   — Tambah/ubah role user",
            "`/removeuser <id>`         — Hapus user",
            "\n*📋 Kode Role:*",
            "`1` → 💧 User (nyalakan air)",
            "`2` → 💡 Admin (kontrol lampu + air)",
        ])

    # Footer untuk publik
    if role == PUBLIC:
        lines.extend([
            "\n_💡 Anda belum memiliki akses kontrol._",
            "_Kirim User ID ke superadmin untuk minta akses._",
        ])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@rate_limit
@public_only
async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/whoami — semua orang."""
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
        parse_mode="Markdown"
    )


# ──── USER Commands — hanya bisa NYALAKAN air ────

@rate_limit
@user_only
async def air_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💧 Menyalakan air...")
    result = tuya.turn_on("air")
    await _send_control_result(update, result, "air")


# ──── ADMIN Commands — bisa MATIKAN air + kontrol lampu ────

@rate_limit
@admin_only
async def air_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔌 Mematikan air...")
    result = tuya.turn_off("air")
    await _send_control_result(update, result, "air")


@rate_limit
@admin_only
async def lampu_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💡 Menyalakan lampu...")
    result = tuya.turn_on("lampu")
    await _send_control_result(update, result, "lampu")


@rate_limit
@admin_only
async def lampu_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌑 Mematikan lampu...")
    result = tuya.turn_off("lampu")
    await _send_control_result(update, result, "lampu")


# ──── SHARED Monitoring (semua role yang login) ────

@public_only
async def air_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Membaca data meteran smart plug...")
    result = tuya.get_power_info("air")
    if result["success"]:
        await update.message.reply_text(
            f"⚡ *COK AIR - Power Monitor*\n\n"
            f"🔌 *Daya*    : `{result['power_w']}` W\n"
            f"⚡ *Arus*    : `{result['current_a']}` A\n"
            f"🔋 *Voltase* : `{result['voltage_v']}` V",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Gagal membaca:\n`{result.get('message', 'Unknown')}`",
            parse_mode="Markdown"
        )


@rate_limit
@public_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — tampilkan ON/OFF saja, tanpa DPS detail."""
    await update.message.reply_text("📊 Mengecek status perangkat...")
    lines = ["📊 *Status Perangkat*\n"]

    for name, label, emoji in [("lampu", "Lampu", "💡"), ("air", "Air", "💧")]:
        result = tuya.get_status(name)
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
@public_only
async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/devices — list perangkat: nama & tipe saja."""
    devices = tuya.list_devices()
    lines = ["📱 *Perangkat Tersedia*\n"]

    for dev in devices:
        icon = "💡" if dev["type"] == "bulb" else "🔌"
        tipe = "Lampu" if dev["type"] == "bulb" else "Smart Plug"
        lines.append(f"{icon} *{dev['name'].title()}* — {tipe}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──── SUPERADMIN Commands ────

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
            "`/allowuser <user_id> 1` — Jadikan 💧 User (bisa nyalakan air)\n"
            "`/allowuser <user_id> 2` — Jadikan 💡 Admin (kontrol lampu + air)\n\n"
            "_User bisa cek ID mereka via `/whoami`_",
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
            "❌ Role tidak valid.\n\n"
            "`1` = 💧 User (nyalakan air)\n"
            "`2` = 💡 Admin (kontrol lampu + air)",
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
            "❌ Gagal. User mungkin sudah di-set via ENV (tidak bisa diubah runtime).",
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


# ──── Unknown Message Handler ────

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Balas jika user kirim teks/command yang tidak dikenal."""
    text = update.message.text.strip() if update.message.text else ""

    # Jika diawali / tapi tidak cocok handler di atas
    if text.startswith("/"):
        await update.message.reply_text(
            f"❓ *Command tidak dikenal:* `{text.split()[0]}`\n\n"
            f"Ketik `/help` untuk melihat command yang tersedia.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"👋 Hai {update.effective_user.first_name}!\n\n"
            f"Saya tidak mengerti pesan itu.\n"
            f"Ketik `/help` untuk melihat command yang bisa digunakan.",
            parse_mode="Markdown"
        )


# ──── Error Handler ────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update %s caused error %s", update, context.error)
    if update and update.message:
        await update.message.reply_text("⚠️ Terjadi kesalahan. Coba lagi nanti.")


# ──── Main ────

def main():
    from config import validate_config

    if not validate_config():
        logger.error("❌ Konfigurasi tidak lengkap.")
        return
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN belum di-set!")
        return

    logger.info("Memulai bot Telegram...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── Publik ──
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("whoami", whoami_command))

    # ── User (kontrol air) ──
    application.add_handler(CommandHandler("airon", air_on))
    application.add_handler(CommandHandler("airoff", air_off))

    # ── Admin (kontrol lampu + air) ──
    application.add_handler(CommandHandler("lampuon", lampu_on))
    application.add_handler(CommandHandler("lampuoff", lampu_off))

    # ── Monitoring (semua) ──
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("airinfo", air_info))
    application.add_handler(CommandHandler("devices", devices_command))

    # ── Superadmin (manajemen) ──
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("allowuser", allowuser_command))
    application.add_handler(CommandHandler("removeuser", removeuser_command))

    # Catch-all: teks atau command yang tidak dikenal
    application.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, unknown_message))

    application.add_error_handler(error_handler)

    # ── Graceful shutdown untuk Docker ──
    async def _run():
        await application.initialize()
        await application.start()
        logger.info("🤖 Bot siap! Menunggu pesan...")

        stop_event = asyncio.Event()

        def _signal_handler(signum, frame):
            logger.info("🛑 Menerima signal %s, shutdown gracefully...", signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        try:
            await stop_event.wait()
        finally:
            await application.stop()
            await application.shutdown()
            logger.info("✅ Bot berhasil dihentikan.")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
