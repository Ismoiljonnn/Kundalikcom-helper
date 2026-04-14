"""
Emaktab Online Bot
"""

import os
import sys
import asyncio
import logging
import threading

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

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
PORT        = int(os.environ.get("PORT", 8080))
USE_WEBHOOK = bool(RENDER_HOST)

_admin_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS  = {int(x) for x in _admin_env.split(",") if x.strip().isdigit()}

if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN o'rnatilmagan!", flush=True)
    sys.exit(1)

logger.info(f"Bot ishga tushmoqda | Webhook: {USE_WEBHOOK} | Host: {RENDER_HOST}")

(
    AUTH_LOGIN, AUTH_PASS,
    ADD_STUDENT_FIO, ADD_STUDENT_LOGIN, ADD_STUDENT_PASS,
    ADD_PARENT_STUDENT, ADD_PARENT_LOGIN, ADD_PARENT_PASS,
    EDIT_SELECT, EDIT_FIELD, EDIT_VALUE,
    DEL_SELECT,
    ADMIN_ADD_LOGIN, ADMIN_ADD_PASS, ADMIN_ADD_FIO,
    ADMIN_DEL_SELECT,
) = range(16)


def main_kb():
    return ReplyKeyboardMarkup([
        ["➕ O'quvchi qo'shish", "👨‍👩‍👦 Ota-ona qo'shish"],
        ["📋 Ro'yxat",           "⚡ Hammani online"],
        ["⚙️ Sozlamalar",        "🚪 Chiqish"],
    ], resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup([
        ["👨‍🏫 O'qituvchilar", "⚙️ Sozlamalar"],
    ], resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

def list_type_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 O'quvchilar ro'yxati",  callback_data="list::students")],
        [InlineKeyboardButton("👨‍👩‍👦 Ota-onalar ro'yxati", callback_data="list::parents")],
    ])

def settings_kb(admin):
    rows = [
        [InlineKeyboardButton("✏️ O'quvchini tahrirlash", callback_data="edit")],
        [InlineKeyboardButton("🗑 O'quvchini o'chirish",  callback_data="delete")],
    ]
    if admin:
        rows.append([InlineKeyboardButton("👨‍💼 O'qituvchilarni boshqarish", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


def get_teacher_login(ctx):
    return ctx.user_data.get("teacher_login")

def is_admin(update):
    return update.effective_user.id in ADMIN_IDS

async def require_auth(update, ctx) -> bool:
    if get_teacher_login(ctx):
        return True
    if update.effective_user.id in ADMIN_IDS:
        linked = db.get_teacher_by_telegram(update.effective_user.id)
        if linked:
            ctx.user_data["teacher_login"] = linked
            return True
    await update.message.reply_text(
        "🔐 Tizimga kirish uchun /start yuboring.",
        reply_markup=ReplyKeyboardRemove()
    )
    return False


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    linked  = db.get_teacher_by_telegram(user_id)

    if linked:
        teacher = db.get_teacher(linked)
        if teacher:
            ctx.user_data["teacher_login"] = linked
            if user_id in ADMIN_IDS:
                teachers = db.get_all_teachers()
                await update.message.reply_text(
                    f"👋 Xush kelibsiz, *{teacher['fio']}!*\n🔐 _Admin paneli_\n"
                    f"👨‍🏫 O'qituvchilar: *{len(teachers)}* nafar",
                    parse_mode="Markdown", reply_markup=admin_kb()
                )
            else:
                students = db.get_students(linked)
                await update.message.reply_text(
                    f"👋 Xush kelibsiz, *{teacher['fio']}!*\n"
                    f"📊 O'quvchilar: *{len(students)}* nafar",
                    parse_mode="Markdown", reply_markup=main_kb()
                )
            return ConversationHandler.END

    if user_id in ADMIN_IDS:
        teachers = db.get_all_teachers()
        if not teachers:
            await update.message.reply_text(
                "🛠 Hali o'qituvchi yo'q.\n/addteacher bilan qo'shing.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        first_login, first_teacher = next(iter(teachers.items()))
        db.link_telegram(user_id, first_login)
        ctx.user_data["teacher_login"] = first_login
        await update.message.reply_text(
            f"👋 Xush kelibsiz, *{first_teacher['fio']}!*\n🔐 _Admin paneli_",
            parse_mode="Markdown", reply_markup=admin_kb()
        )
        return ConversationHandler.END

    teachers = db.get_all_teachers()
    if not teachers:
        await update.message.reply_text("⛔ Tizimda hali o'qituvchi yo'q.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🔐 *Tizimga kirish*\n\nLoginizni kiriting:",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
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
        teacher  = db.get_teacher(login)
        db.link_telegram(update.effective_user.id, login)
        ctx.user_data["teacher_login"] = login
        students = db.get_students(login)
        await update.message.reply_text(
            f"✅ Xush kelibsiz, *{teacher['fio']}!*\n"
            f"📊 O'quvchilar: *{len(students)}* nafar",
            parse_mode="Markdown", reply_markup=main_kb()
        )
        return ConversationHandler.END
    await update.message.reply_text("❌ Login yoki parol noto'g'ri.\nLoginizni qayta kiriting:")
    return AUTH_LOGIN

async def logout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.unlink_telegram(update.effective_user.id)
    ctx.user_data.clear()
    await update.message.reply_text(
        "🚪 Tizimdan chiqdingiz.\n/start — qayta kirish.",
        reply_markup=ReplyKeyboardRemove()
    )

async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update, ctx):
        return
    text = update.message.text
    if text == "📋 Ro'yxat":
        await show_list_menu(update, ctx)
    elif text == "⚡ Hammani online":
        await start_online(update, ctx)
    elif text == "⚙️ Sozlamalar":
        await settings_menu(update, ctx)
    elif text == "🚪 Chiqish":
        await logout(update, ctx)
    elif text == "👨‍🏫 O'qituvchilar":
        await admin_teachers_menu(update, ctx)


async def show_list_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Qaysi ro'yxat?*",
        parse_mode="Markdown",
        reply_markup=list_type_kb()
    )

async def list_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, list_type = query.data.split("::")
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)

    if list_type == "students":
        if not students:
            await query.edit_message_text("📭 O'quvchilar ro'yxati bo'sh.")
            return
        lines = [f"👤 *O'quvchilar* — {len(students)} nafar\n"]
        for i, s in enumerate(students, 1):
            lines.append(f"{i}. *{s['fio']}*\n    🔑 `{s['login']}`")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")

    elif list_type == "parents":
        parents = [s for s in students if s.get("parent", {}).get("login")]
        if not parents:
            await query.edit_message_text("📭 Ota-onalar ro'yxati bo'sh.")
            return
        lines = [f"👨‍👩‍👦 *Ota-onalar* — {len(parents)} nafar\n"]
        for i, s in enumerate(parents, 1):
            p = s["parent"]
            lines.append(f"{i}. *{s['fio']}* ota-onasi\n    🔑 `{p['login']}`")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


async def add_student_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update, ctx):
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ *Yangi o'quvchi qo'shish*\n\n1️⃣ O'quvchining to'liq ismi (FIO):",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return ADD_STUDENT_FIO

async def add_student_fio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish":
        return await _cancel(update, ctx)
    ctx.user_data["ns_fio"] = update.message.text.strip()
    await update.message.reply_text(
        "2️⃣ O'quvchining *login*i _(emaktab.uz dagi)_:",
        parse_mode="Markdown"
    )
    return ADD_STUDENT_LOGIN

async def add_student_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish":
        return await _cancel(update, ctx)
    ctx.user_data["ns_login"] = update.message.text.strip()
    await update.message.reply_text("3️⃣ O'quvchining *paroli*:", parse_mode="Markdown")
    return ADD_STUDENT_PASS

async def add_student_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish":
        return await _cancel(update, ctx)
    tlogin = get_teacher_login(ctx)
    fio    = ctx.user_data.pop("ns_fio", "")
    login  = ctx.user_data.pop("ns_login", "")
    passw  = update.message.text.strip()
    ok = db.add_student(tlogin, fio=fio, login=login, password=passw,
                        parent_login="", parent_password="")
    if ok:
        await update.message.reply_text(
            f"✅ *{fio}* qo'shildi!\n🔑 Login: `{login}`\n\n"
            f"_Ota-onasini biriktirish uchun \"👨‍👩‍👦 Ota-ona qo'shish\" tugmasini bosing._",
            parse_mode="Markdown", reply_markup=main_kb()
        )
    else:
        await update.message.reply_text("⚠️ Bu login allaqachon mavjud!", reply_markup=main_kb())
    return ConversationHandler.END


async def add_parent_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_auth(update, ctx):
        return ConversationHandler.END
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)
    if not students:
        await update.message.reply_text("📭 Avval o'quvchi qo'shing!", reply_markup=main_kb())
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(
            s["fio"] + (" ✅" if s.get("parent", {}).get("login") else ""),
            callback_data=f"parent_for::{s['login']}"
        )]
        for s in students
    ]
    await update.message.reply_text(
        "👨‍👩‍👦 *Qaysi o'quvchiga ota-ona biriktirasiz?*\n_(✅ — allaqachon biriktirilgan)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ADD_PARENT_STUDENT

async def add_parent_student_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, slogin = query.data.split("::")
    ctx.user_data["parent_for"] = slogin
    tlogin  = get_teacher_login(ctx)
    student = db.get_student(tlogin, slogin)
    current = student.get("parent", {}).get("login", "") if student else ""
    note = f"\n_(Hozirgi: `{current}`)_" if current else ""
    await query.edit_message_text(
        f"👤 *{student['fio']}* uchun:{note}\n\n1️⃣ Ota-ona *login*i:",
        parse_mode="Markdown"
    )
    return ADD_PARENT_LOGIN

async def add_parent_login_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish":
        return await _cancel(update, ctx)
    ctx.user_data["p_login"] = update.message.text.strip()
    await update.message.reply_text("2️⃣ Ota-ona *paroli*:", parse_mode="Markdown")
    return ADD_PARENT_PASS

async def add_parent_pass_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Bekor qilish":
        return await _cancel(update, ctx)
    tlogin  = get_teacher_login(ctx)
    slogin  = ctx.user_data.pop("parent_for", "")
    plogin  = ctx.user_data.pop("p_login", "")
    ppass   = update.message.text.strip()
    student = db.get_student(tlogin, slogin)
    db.update_student(tlogin, slogin, "parent_login", plogin)
    db.update_student(tlogin, slogin, "parent_password", ppass)
    await update.message.reply_text(
        f"✅ *{student['fio'] if student else slogin}* uchun\n"
        f"ota-ona biriktirildi! 👨‍👩‍👦\n🔑 Login: `{plogin}`",
        parse_mode="Markdown", reply_markup=main_kb()
    )
    return ConversationHandler.END


async def start_online(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)
    if not students:
        await update.message.reply_text("📭 Ro'yxat bo'sh.")
        return
    with_parents = sum(1 for s in students if s.get("parent", {}).get("login"))
    await update.message.reply_text(
        f"⚡ *Jarayon boshlandi!*\n\n"
        f"👤 O'quvchilar: *{len(students)}* ta\n"
        f"👨‍👩‍👦 Ota-onalar: *{with_parents}* ta\n"
        f"📱 Jami: *{len(students) + with_parents}* akkaunt\n\n"
        f"⏳ _Kuting..._",
        parse_mode="Markdown"
    )
    chat_id = update.effective_chat.id
    bot     = ctx.bot
    loop    = asyncio.get_event_loop()

    def progress(current, total, fio, who, ok):
        icon = "✅" if ok else "❌"
        asyncio.run_coroutine_threadsafe(
            bot.send_message(
                chat_id=chat_id,
                text=f"{icon} [{current}/{total}] *{fio}* — {who}",
                parse_mode="Markdown"
            ), loop
        )

    def run():
        results = sh.make_all_online(students, progress_callback=progress)
        asyncio.run_coroutine_threadsafe(
            bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🏁 *Tugadi!*\n\n"
                    f"👤 O'quvchilar: ✅ {results['student_ok']}  ❌ {results['student_fail']}\n"
                    f"👨‍👩‍👦 Ota-onalar:  ✅ {results['parent_ok']}  ❌ {results['parent_fail']}"
                ),
                parse_mode="Markdown"
            ), loop
        )

    threading.Thread(target=run, daemon=True).start()


async def settings_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ *Sozlamalar*", parse_mode="Markdown",
        reply_markup=settings_kb(is_admin(update))
    )

async def settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action   = query.data
    tlogin   = get_teacher_login(ctx)
    students = db.get_students(tlogin)

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
            f"👨‍💼 *O'qituvchilar:* {len(teachers)} nafar",
            parse_mode="Markdown", reply_markup=kb
        )
        return ConversationHandler.END

    if not students:
        await query.edit_message_text("📭 Ro'yxat bo'sh.")
        return ConversationHandler.END

    label   = "tahrirlash" if action == "edit" else "o'chirish"
    buttons = [[InlineKeyboardButton(s["fio"], callback_data=f"{action}::{s['login']}")] for s in students]
    await query.edit_message_text(
        f"Qaysi o'quvchini {label}?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EDIT_SELECT if action == "edit" else DEL_SELECT

async def edit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, slogin = query.data.split("::")
    ctx.user_data["edit_slogin"] = slogin
    tlogin  = get_teacher_login(ctx)
    student = db.get_student(tlogin, slogin)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 To'liq ismi (FIO)",    callback_data="ef::fio")],
        [InlineKeyboardButton("🔑 O'quvchi paroli",      callback_data="ef::password")],
        [InlineKeyboardButton("👤 Ota-ona logini",       callback_data="ef::parent_login")],
        [InlineKeyboardButton("🔑 Ota-ona paroli",       callback_data="ef::parent_password")],
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
    labels = {
        "fio": "To'liq ism (FIO)",
        "password": "O'quvchi paroli",
        "parent_login": "Ota-ona logini",
        "parent_password": "Ota-ona paroli"
    }
    await query.edit_message_text(
        f"✏️ Yangi *{labels[field]}*ni kiriting:", parse_mode="Markdown"
    )
    return EDIT_VALUE

async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tlogin = get_teacher_login(ctx)
    db.update_student(tlogin, ctx.user_data["edit_slogin"],
                      ctx.user_data["edit_field"], update.message.text.strip())
    ctx.user_data.pop("edit_slogin", None)
    ctx.user_data.pop("edit_field", None)
    await update.message.reply_text("✅ Muvaffaqiyatli yangilandi!", reply_markup=main_kb())
    return ConversationHandler.END

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


async def admin_teachers_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return
    teachers = db.get_all_teachers()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ O'qituvchi qo'shish", callback_data="admin_add")],
        [InlineKeyboardButton("🗑 O'qituvchi o'chirish", callback_data="admin_del")],
    ])
    lines = [f"👨‍💼 *O'qituvchilar:* {len(teachers)} nafar\n"]
    for i, (login, t) in enumerate(teachers.items(), 1):
        students_count = len(db.get_students(login))
        lines.append(f"{i}. *{t['fio']}*\n    🔑 `{login}` | 👤 {students_count} o'quvchi")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)

async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        await query.edit_message_text("⛔ Ruxsat yo'q.")
        return ConversationHandler.END
    if query.data == "admin_add":
        await query.edit_message_text("➕ *Yangi o'qituvchi*\n\nLoginni kiriting:", parse_mode="Markdown")
        return ADMIN_ADD_LOGIN
    if query.data == "admin_del":
        teachers = db.get_all_teachers()
        if not teachers:
            await query.edit_message_text("O'qituvchilar yo'q.")
            return ConversationHandler.END
        buttons = [[InlineKeyboardButton(v["fio"], callback_data=f"adel::{k}")] for k, v in teachers.items()]
        await query.edit_message_text("O'chirish uchun tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return ADMIN_DEL_SELECT

async def admin_add_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_tlogin"] = update.message.text.strip()
    await update.message.reply_text("🔑 Parolni kiriting:")
    return ADMIN_ADD_PASS

async def admin_add_pass(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_tpass"] = update.message.text.strip()
    await update.message.reply_text("👤 To'liq ismi (FIO)ni kiriting:")
    return ADMIN_ADD_FIO

async def admin_add_fio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    login = ctx.user_data.pop("new_tlogin", "")
    passw = ctx.user_data.pop("new_tpass", "")
    fio   = update.message.text.strip()
    ok    = db.add_teacher(login, passw, fio)
    kb    = admin_kb() if is_admin(update) else main_kb()
    if ok:
        await update.message.reply_text(
            f"✅ *{fio}* qo'shildi!\n🔑 Login: `{login}`",
            parse_mode="Markdown", reply_markup=kb
        )
    else:
        await update.message.reply_text("⚠️ Bu login allaqachon bor.", reply_markup=kb)
    return ConversationHandler.END

async def admin_del_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, tlogin = query.data.split("::")
    teacher   = db.get_teacher(tlogin)
    db.delete_teacher(tlogin)
    await query.edit_message_text(
        f"🗑 *{teacher['fio'] if teacher else tlogin}* o'chirildi.", parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cmd_addteacher(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Ruxsat yo'q.")
        return ConversationHandler.END
    await update.message.reply_text("➕ Yangi o'qituvchi\nLoginni kiriting:", reply_markup=cancel_kb())
    return ADMIN_ADD_LOGIN

async def _cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    for k in list(ctx.user_data.keys()):
        if k.startswith(("ns_", "new_t", "edit_", "p_", "parent_")):
            ctx.user_data.pop(k)
    kb = admin_kb() if update.effective_user.id in ADMIN_IDS else main_kb()
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=kb)
    return ConversationHandler.END

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _cancel(update, ctx)


def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            AUTH_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_login)],
            AUTH_PASS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        name="auth", persistent=False,
    )

    add_student_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ O'quvchi qo'shish$"), add_student_start)],
        states={
            ADD_STUDENT_FIO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_fio)],
            ADD_STUDENT_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_login)],
            ADD_STUDENT_PASS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    )

    add_parent_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👨‍👩‍👦 Ota-ona qo'shish$"), add_parent_start)],
        states={
            ADD_PARENT_STUDENT: [CallbackQueryHandler(add_parent_student_cb, pattern="^parent_for::")],
            ADD_PARENT_LOGIN:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_parent_login_step)],
            ADD_PARENT_PASS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_parent_pass_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    )

    settings_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(settings_cb, pattern="^(edit|delete|admin)$")],
        states={
            EDIT_SELECT: [CallbackQueryHandler(edit_select, pattern="^edit::")],
            EDIT_FIELD:  [CallbackQueryHandler(edit_field,  pattern="^ef::")],
            EDIT_VALUE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            DEL_SELECT:  [CallbackQueryHandler(del_select,  pattern="^delete::")],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=False,
        conversation_timeout=120,
    )

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
    app.add_handler(add_student_conv)
    app.add_handler(add_parent_conv)
    app.add_handler(settings_conv)
    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(list_cb, pattern="^list::"))
    app.add_handler(MessageHandler(
        filters.Regex("^(📋 Ro'yxat|⚡ Hammani online|⚙️ Sozlamalar|🚪 Chiqish|👨‍🏫 O'qituvchilar)$"),
        menu_handler
    ))

    return app


def main():
    app = build_app()
    if USE_WEBHOOK:
        webhook_url = f"https://{RENDER_HOST}/webhook"
        logger.info(f"Webhook: {webhook_url}")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path="/webhook", webhook_url=webhook_url)
    else:
        logger.info("Polling rejimi")
        app.run_polling()


if __name__ == "__main__":
    main()