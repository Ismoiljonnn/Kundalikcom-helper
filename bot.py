"""
Kundalik.com Online Bot
Har bir o'qituvchi o'z login/paroli bilan kiradi va faqat o'z o'quvchilarini boshqaradi.
Render Web Service uchun webhook rejimida ishlaydi.
"""

import os
import sys
import asyncio
import logging
import threading

# ── Eng avval data/ papkasini yaratamiz (logging dan oldin!) ──────────────────
os.makedirs("data", exist_ok=True)

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

import database as db
import selenium_handler as sh

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
PORT        = int(os.environ.get("PORT", 8080))
USE_WEBHOOK = bool(RENDER_HOST)

_admin_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS  = {int(x) for x in _admin_env.split(",") if x.strip().isdigit()}

# ── BOT_TOKEN tekshiruvi ──────────────────────────────────────────────────────
if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN environment variable o'rnatilmagan!", flush=True)
    print("Render Dashboard > Environment > BOT_TOKEN ga tokeningizni kiriting.", flush=True)
    sys.exit(1)

logger.info(f"Bot ishga tushmoqda | Webhook: {USE_WEBHOOK} | Host: {RENDER_HOST} | Port: {PORT}")

# ── States ────────────────────────────────────────────────────────────────────
(
    AUTH_LOGIN, AUTH_PASS,
    ADD_FIO, ADD_LOGIN, ADD_PASS, ADD_PARENT_LOGIN, ADD_PARENT_PASS,
    EDIT_SELECT, EDIT_FIELD, EDIT_VALUE,
    DEL_SELECT,
    ADMIN_ADD_LOGIN, ADMIN_ADD_PASS, ADMIN_ADD_FIO,
    ADMIN_DEL_SELECT,
    CHANGE_PASS_NEW,
) = range(16)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def main_kb(admin: bool = False):
    if admin:
        return ReplyKeyboardMarkup([
            ["➕ O'quvchi qo'shish", "📋 Sinf ro'yxati"],
            ["⚡ HAMMANI ONLINE QILISH", "⚙️ Sozlamalar"],
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["➕ O'quvchi qo'shish", "📋 Sinf ro'yxati"],
        ["⚡ HAMMANI ONLINE QILISH", "⚙️ Sozlamalar"],
        ["🚪 Chiqish"],
    ], resize_keyboard=True)


def cancel_kb():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)


def settings_kb(is_admin: bool):
    rows = [
        [InlineKeyboardButton("✏️ O'quvchini tahrirlash", callback_data="edit")],
        [InlineKeyboardButton("🗑 O'quvchini o'chirish", callback_data="delete")],
        [InlineKeyboardButton("🔑 Parolimni o'zgartirish", callback_data="change_pass")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("👨‍💼 O'qituvchilarni boshqarish", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def get_teacher_login(ctx: ContextTypes.DEFAULT_TYPE):
    """Returns current teacher login from user_data, or None."""
    return ctx.user_data.get("teacher_login")


def is_admin(update: Update):
    return update.effective_user.id in ADMIN_IDS


async def require_auth(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if authenticated, else sends auth prompt and returns False."""
    if get_teacher_login(ctx):
        return True
    # Admin bo'lsa — avtomatik tizimga kirish
    if update.effective_user.id in ADMIN_IDS:
        linked = db.get_teacher_by_telegram(update.effective_user.id)
        if linked:
            ctx.user_data["teacher_login"] = linked
            return True
    await update.message.reply_text(
        "🔐 Iltimos avval tizimga kiring.\n/start buyrug'ini yuboring.",
        reply_markup=ReplyKeyboardRemove()
    )
    return False


# ── /start & Auth conversation ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Already linked?
    linked = db.get_teacher_by_telegram(user_id)
    if linked:
        teacher = db.get_teacher(linked)
        if teacher:
            ctx.user_data["teacher_login"] = linked
            _is_admin = update.effective_user.id in ADMIN_IDS
            await update.message.reply_text(
                f"👋 Xush kelibsiz, *{teacher['fio']}*!",
                parse_mode="Markdown",
                reply_markup=main_kb(admin=_is_admin)
            )
            return ConversationHandler.END

    # Admin bo'lsa — login so'ramasdan birinchi teacher sifatida kiradi
    if user_id in ADMIN_IDS:
        teachers = db.get_all_teachers()
        if not teachers:
            await update.message.reply_text(
                "🛠 Birinchi o'qituvchi qo'shish uchun /addteacher buyrug'ini yuboring.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        first_login, first_teacher = next(iter(teachers.items()))
        db.link_telegram(user_id, first_login)
        ctx.user_data["teacher_login"] = first_login
        await update.message.reply_text(
            f"👋 Xush kelibsiz, *{first_teacher['fio']}* (Admin)!",
            parse_mode="Markdown",
            reply_markup=main_kb(admin=True)
        )
        return ConversationHandler.END

    teachers = db.get_all_teachers()
    if not teachers:
        await update.message.reply_text("⛔ Hali hech qanday o'qituvchi yo'q. Admin kutilmoqda.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🔐 *Tizimga kirish*\n\nLoginizni kiriting:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return AUTH_LOGIN


async def auth_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["auth_login"] = update.message.text.strip()
    await update.message.reply_text("🔑 Parolingizni kiriting:")
    return AUTH_PASS


async def auth_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    login    = ctx.user_data.pop("auth_login", "")
    password = update.message.text.strip()

    if db.verify_teacher(login, password):
        teacher = db.get_teacher(login)
        db.link_telegram(update.effective_user.id, login)
        ctx.user_data["teacher_login"] = login
        _is_admin = update.effective_user.id in ADMIN_IDS
        await update.message.reply_text(
            f"✅ Xush kelibsiz, *{teacher['fio']}*!",
            parse_mode="Markdown",
            reply_markup=main_kb(admin=_is_admin)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ Login yoki parol noto'g'ri. Qayta urinib ko'ring.\n"
            "Loginizni kiriting:"
        )
        return AUTH_LOGIN


# ── Logout ────────────────────────────────────────────────────────────────────

async def logout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.unlink_telegram(update.effective_user.id)
    ctx.user_data.clear()
    await update.message.reply_text(
        "🚪 Tizimdan chiqdingiz. Qayta kirish uchun /start yuboring.",
        reply_markup=ReplyKeyboardRemove()
    )


# ── Menu dispatcher ────────────────────────────────────────────────────────────

async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update, ctx):
        return
    text = update.message.text
    if text == "📋 Sinf ro'yxati":
        await show_list(update, ctx)
    elif text == "⚡ HAMMANI ONLINE QILISH":
        await start_online(update, ctx)
    elif text == "⚙️ Sozlamalar":
        await settings_menu(update, ctx)
    elif text == "🚪 Chiqish":
        if update.effective_user.id in ADMIN_IDS:
            await update.message.reply_text("⛔ Admin tizimdan chiqolmaydi.")
        else:
            await logout(update, ctx)


# ── Student list ───────────────────────────────────────────────────────────────

async def show_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)
    if not students:
        await update.message.reply_text("📭 Ro'yxat bo'sh. Avval o'quvchi qo'shing.")
        return
    lines = [f"📋 *Sinf ro'yxati ({len(students)} o'quvchi):*\n"]
    for i, s in enumerate(students, 1):
        lines.append(
            f"{i}. *{s['fio']}*\n"
            f"   👤 `{s['login']}`  |  👨‍👩‍👦 `{s['parent']['login']}`"
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_kb()
    )


# ── ADD student conversation ───────────────────────────────────────────────────

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update, ctx):
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ *Yangi o'quvchi qo'shish*\n\n1️⃣ O'quvchining to'liq ismi (FIO):",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return ADD_FIO


async def add_fio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish": return await _cancel(update, ctx)
    ctx.user_data["ns_fio"] = update.message.text.strip()
    await update.message.reply_text("2️⃣ O'quvchi *logini*:", parse_mode="Markdown")
    return ADD_LOGIN


async def add_login_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish": return await _cancel(update, ctx)
    ctx.user_data["ns_login"] = update.message.text.strip()
    await update.message.reply_text("3️⃣ O'quvchi *paroli*:", parse_mode="Markdown")
    return ADD_PASS


async def add_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish": return await _cancel(update, ctx)
    ctx.user_data["ns_pass"] = update.message.text.strip()
    await update.message.reply_text("4️⃣ Ota-ona *logini*:", parse_mode="Markdown")
    return ADD_PARENT_LOGIN


async def add_parent_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish": return await _cancel(update, ctx)
    ctx.user_data["ns_plogin"] = update.message.text.strip()
    await update.message.reply_text("5️⃣ Ota-ona *paroli*:", parse_mode="Markdown")
    return ADD_PARENT_PASS


async def add_parent_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish": return await _cancel(update, ctx)
    ud = ctx.user_data
    tlogin = get_teacher_login(ctx)
    ok = db.add_student(
        tlogin,
        fio=ud["ns_fio"], login=ud["ns_login"], password=ud["ns_pass"],
        parent_login=ud["ns_plogin"], parent_password=update.message.text.strip()
    )
    for k in ("ns_fio","ns_login","ns_pass","ns_plogin"):
        ud.pop(k, None)

    if ok:
        student_name = ud.get("ns_fio", "O'quvchi")
        await update.message.reply_text(
            f"✅ *{student_name}* qo'shildi!",
            parse_mode="Markdown", 
            reply_markup=main_kb()
        )
    else:
        await update.message.reply_text(
            "⚠️ Bu login allaqachon mavjud.", 
            reply_markup=main_kb()
        )

    return ConversationHandler.END


# ── ONLINE ────────────────────────────────────────────────────────────────────

async def start_online(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)
    if not students:
        await update.message.reply_text("📭 Ro'yxat bo'sh.")
        return

    await update.message.reply_text(
        f"⚡ *{len(students)} o'quvchi* uchun jarayon boshlandi...\n⏳ Kuting.",
        parse_mode="Markdown"
    )

    chat_id = update.effective_chat.id
    bot     = ctx.bot
    loop    = asyncio.get_event_loop()

    def progress(current, total, fio, who, ok):
        icon = "✅" if ok else "❌"
        text = f"{icon} [{current}/{total}] *{fio}* — {who} {'✓' if ok else 'XATO'}"
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown"), loop
        )

    def run():
        results = sh.make_all_online(students, progress_callback=progress)
        summary = (
            f"\n🏁 *Tugadi!*\n\n"
            f"👤 O'quvchilar: ✅{results['student_ok']} ❌{results['student_fail']}\n"
            f"👨‍👩‍👦 Ota-onalar:  ✅{results['parent_ok']} ❌{results['parent_fail']}"
        )
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown"), loop
        )

    threading.Thread(target=run, daemon=True).start()


# ── SETTINGS ──────────────────────────────────────────────────────────────────

async def settings_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ *Sozlamalar:*", parse_mode="Markdown",
        reply_markup=settings_kb(is_admin(update))
    )


async def settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)

    if action == "change_pass":
        await query.edit_message_text("🔑 Yangi parolni kiriting:")
        return CHANGE_PASS_NEW

    if action == "admin":
        if not is_admin(update):
            await query.edit_message_text("⛔ Ruxsat yo'q.")
            return ConversationHandler.END
        teachers = db.get_all_teachers()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ O'qituvchi qo'shish", callback_data="admin_add")],
            [InlineKeyboardButton("🗑 O'qituvchi o'chirish", callback_data="admin_del")],
        ])
        await query.edit_message_text(
            f"👨‍💼 *O'qituvchilar soni:* {len(teachers)}", parse_mode="Markdown",
            reply_markup=kb
        )
        return ConversationHandler.END

    if not students:
        await query.edit_message_text("📭 Ro'yxat bo'sh.")
        return ConversationHandler.END

    label = "tahrirlash" if action == "edit" else "o'chirish"
    buttons = [[InlineKeyboardButton(s["fio"], callback_data=f"{action}::{s['login']}")] for s in students]
    await query.edit_message_text(
        f"Qaysi o'quvchini {label}?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EDIT_SELECT if action == "edit" else DEL_SELECT


# ── Change password ────────────────────────────────────────────────────────────

async def change_pass_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tlogin = get_teacher_login(ctx)
    db.change_teacher_password(tlogin, update.message.text.strip())
    await update.message.reply_text("✅ Parol o'zgartirildi!", reply_markup=main_kb())
    return ConversationHandler.END


# ── Edit student ───────────────────────────────────────────────────────────────

async def edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, slogin = query.data.split("::")
    ctx.user_data["edit_slogin"] = slogin
    tlogin  = get_teacher_login(ctx)
    student = db.get_student(tlogin, slogin)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 FIO",            callback_data="ef::fio")],
        [InlineKeyboardButton("🔑 O'quvchi paroli", callback_data="ef::password")],
        [InlineKeyboardButton("🔑 Ota-ona login",   callback_data="ef::parent_login")],
        [InlineKeyboardButton("🔑 Ota-ona paroli",  callback_data="ef::parent_password")],
    ])
    await query.edit_message_text(
        f"✏️ *{student['fio']}* — qaysi maydon?",
        parse_mode="Markdown", reply_markup=kb
    )
    return EDIT_FIELD


async def edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, field = query.data.split("::")
    ctx.user_data["edit_field"] = field
    labels = {"fio":"FIO","password":"O'quvchi paroli",
              "parent_login":"Ota-ona login","parent_password":"Ota-ona paroli"}
    await query.edit_message_text(f"Yangi *{labels[field]}*ni kiriting:", parse_mode="Markdown")
    return EDIT_VALUE


async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tlogin = get_teacher_login(ctx)
    db.update_student(tlogin, ctx.user_data["edit_slogin"],
                      ctx.user_data["edit_field"], update.message.text.strip())
    ctx.user_data.pop("edit_slogin", None)
    ctx.user_data.pop("edit_field", None)
    await update.message.reply_text("✅ Yangilandi!", reply_markup=main_kb())
    return ConversationHandler.END


# ── Delete student ─────────────────────────────────────────────────────────────

async def del_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, slogin = query.data.split("::")
    tlogin  = get_teacher_login(ctx)
    student = db.get_student(tlogin, slogin)
    db.delete_student(tlogin, slogin)
    await query.edit_message_text(
        f"🗑 *{student['fio'] if student else slogin}* o'chirildi.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── Admin: manage teachers ─────────────────────────────────────────────────────

async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        await query.edit_message_text("⛔ Ruxsat yo'q.")
        return ConversationHandler.END

    if query.data == "admin_add":
        await query.edit_message_text("Yangi o'qituvchi *logini*ni kiriting:", parse_mode="Markdown")
        return ADMIN_ADD_LOGIN

    if query.data == "admin_del":
        teachers = db.get_all_teachers()
        if not teachers:
            await query.edit_message_text("Hech qanday o'qituvchi yo'q.")
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(v["fio"], callback_data=f"adel::{k}")]
                   for k, v in teachers.items()]
        await query.edit_message_text(
            "O'chirish uchun o'qituvchini tanlang:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return ADMIN_DEL_SELECT


async def admin_add_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_tlogin"] = update.message.text.strip()
    await update.message.reply_text("Parolni kiriting:")
    return ADMIN_ADD_PASS


async def admin_add_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_tpass"] = update.message.text.strip()
    await update.message.reply_text("O'qituvchining to'liq ismi (FIO):")
    return ADMIN_ADD_FIO


async def admin_add_fio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    login = ctx.user_data.pop("new_tlogin", "")
    passw = ctx.user_data.pop("new_tpass", "")
    fio   = update.message.text.strip()
    ok = db.add_teacher(login, passw, fio)
    if ok:
        await update.message.reply_text(
            f"✅ O'qituvchi *{fio}* qo'shildi!\nLogin: `{login}`",
            parse_mode="Markdown", reply_markup=main_kb()
        )
    else:
        await update.message.reply_text("⚠️ Bu login allaqachon mavjud.", reply_markup=main_kb())
    return ConversationHandler.END


async def admin_del_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, tlogin = query.data.split("::")
    teacher   = db.get_teacher(tlogin)
    db.delete_teacher(tlogin)
    await query.edit_message_text(
        f"🗑 O'qituvchi *{teacher['fio'] if teacher else tlogin}* o'chirildi.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── Admin command: /addteacher (first setup) ──────────────────────────────────

async def cmd_addteacher(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ Yangi o'qituvchi qo'shish\nLoginni kiriting:",
        reply_markup=cancel_kb()
    )
    return ADMIN_ADD_LOGIN


# ── Cancel ─────────────────────────────────────────────────────────────────────

async def _cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    for k in list(ctx.user_data.keys()):
        if k.startswith(("ns_", "new_t", "edit_")):
            ctx.user_data.pop(k)
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=main_kb())
    return ConversationHandler.END


async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _cancel(update, ctx)


# ── App ────────────────────────────────────────────────────────────────────────

def build_app():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Auth conversation (/start)
    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            AUTH_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_login)],
            AUTH_PASS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        name="auth", persistent=False,
    )

    # Add student conversation
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ O'quvchi qo'shish$"), add_start)],
        states={
            ADD_FIO:          [MessageHandler(filters.TEXT & ~filters.COMMAND, add_fio)],
            ADD_LOGIN:        [MessageHandler(filters.TEXT & ~filters.COMMAND, add_login_step)],
            ADD_PASS:         [MessageHandler(filters.TEXT & ~filters.COMMAND, add_pass)],
            ADD_PARENT_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_parent_login)],
            ADD_PARENT_PASS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_parent_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    )

    # Settings conversation (inline buttons)
    settings_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(settings_cb, pattern="^(edit|delete|change_pass|admin)$")],
        states={
            EDIT_SELECT:     [CallbackQueryHandler(edit_select,     pattern="^edit::")],
            EDIT_FIELD:      [CallbackQueryHandler(edit_field,      pattern="^ef::")],
            EDIT_VALUE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            DEL_SELECT:      [CallbackQueryHandler(del_select,      pattern="^delete::")],
            CHANGE_PASS_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_pass_new)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    )

    # Admin: manage teachers
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_cb, pattern="^(admin_add|admin_del)$"),
            CommandHandler("addteacher", cmd_addteacher),
        ],
        states={
            ADMIN_ADD_LOGIN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_login)],
            ADMIN_ADD_PASS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_pass)],
            ADMIN_ADD_FIO:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_fio)],
            ADMIN_DEL_SELECT: [CallbackQueryHandler(admin_del_select, pattern="^adel::")],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    )

    app.add_handler(auth_conv)
    app.add_handler(add_conv)
    app.add_handler(settings_conv)
    app.add_handler(admin_conv)
    app.add_handler(MessageHandler(
        filters.Regex("^(📋 Sinf ro'yxati|⚡ HAMMANI ONLINE QILISH|⚙️ Sozlamalar|🚪 Chiqish)$"),
        menu_handler
    ))

    return app


def main():
    app = build_app()

    if USE_WEBHOOK:
        webhook_url = f"https://{RENDER_HOST}/webhook"
        logger.info(f"Webhook rejimi: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="/webhook",
            webhook_url=webhook_url,
        )
    else:
        logger.info("Polling rejimi (lokal)")
        app.run_polling()


if __name__ == "__main__":
    main()