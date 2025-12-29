
# Clan Helper Bot — Beta 2
# Full command set implemented / scaffolded
# Ready for deploy (Koyeb / VPS)
# Python 3.10+

import os
import re
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from supabase import create_client

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= STATES =================
RACE, ATK, DEF, CONFIRM = range(4)
TEMP_TIMEOUT = 180  # 3 minutes

# ================= UTILS =================
def parse_power(value: str) -> int | None:
    value = value.lower().strip()
    m = re.fullmatch(r"(\\d+)([km]?)", value)
    if not m:
        return None
    n, u = m.groups()
    n = int(n)
    if u == "k":
        return n * 1_000
    if u == "m":
        return n * 1_000_000
    return n

def numeric_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["1","2","3"],
            ["4","5","6"],
            ["7","8","9"],
            ["0","k","m"],
            ["Cancelar"]
        ],
        resize_keyboard=True
    )

def expired(context):
    return datetime.utcnow() - context.user_data.get("started_at", datetime.utcnow()) > timedelta(seconds=TEMP_TIMEOUT)

# ================= BASIC COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "🤖 Clan Helper — Beta 2\n\n"
            "Para registrar o actualizar stats debes escribirme por privado."
        )
        return

    await update.message.reply_text(
        "🤖 Clan Helper — Beta 2\n\n"
        "Sistema en pruebas.\n"
        "Usa /me o /act para registrar o actualizar tus datos.\n"
        "Espera nuevas instrucciones del admin."
    )

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await me(update, context)

# ================= PROFILE FLOW =================
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    res = supabase.table("users").select("*").eq("uid", uid).execute()

    if res.data:
        u = res.data[0]
        await update.message.reply_text(
            f"👤 Perfil\n"
            f"Raza: {u['race']}\n"
            f"ATK: {u['atk']}\n"
            f"DEF: {u['def']}"
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["started_at"] = datetime.utcnow()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐶 Perro", callback_data="perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="rana")],
        [InlineKeyboardButton("🐱 Gato", callback_data="gato")]
    ])

    await update.message.reply_text("Selecciona tu raza:", reply_markup=kb)
    return RACE

async def race_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["race"] = q.data
    await q.edit_message_text("Introduce tu ATK (ej: 34k, 6m, 1200)")
    await q.message.reply_text("ATK:", reply_markup=numeric_keyboard())
    return ATK

async def atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if expired(context):
        await update.message.reply_text("⏰ Tiempo agotado", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if update.message.text == "Cancelar":
        await update.message.reply_text("❌ Cancelado", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    val = parse_power(update.message.text)
    if val is None:
        await update.message.reply_text("ATK inválido")
        return ATK

    context.user_data["atk"] = val
    await update.message.reply_text("Introduce DEF:", reply_markup=numeric_keyboard())
    return DEF

async def defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if expired(context):
        await update.message.reply_text("⏰ Tiempo agotado", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    val = parse_power(update.message.text)
    if val is None:
        await update.message.reply_text("DEF inválido")
        return DEF

    context.user_data["def"] = val

    d = context.user_data
    await update.message.reply_text(
        f"Confirmar datos:\nRaza: {d['race']}\nATK: {d['atk']}\nDEF: {d['def']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirmar", callback_data="ok")],
            [InlineKeyboardButton("Cancelar", callback_data="cancel")]
        ])
    )
    return CONFIRM

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "cancel":
        await q.edit_message_text("Cancelado")
        return ConversationHandler.END

    u = q.from_user
    supabase.table("users").insert({
        "uid": str(u.id),
        "tg": u.username,
        "race": context.user_data["race"],
        "atk": context.user_data["atk"],
        "def": context.user_data["def"],
        "sent_war": False
    }).execute()

    await q.edit_message_text("Perfil guardado")
    return ConversationHandler.END

# ================= RANKINGS =================
async def atk_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("users").select("tg,atk").order("atk", desc=True).limit(20).execute()
    txt = "🏆 Ranking ATK\n"
    for i,u in enumerate(res.data,1):
        if u["tg"]:
            txt += f"{i}. @{u['tg']} — {u['atk']}\n"
    await update.message.reply_text(txt)

async def def_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("users").select("tg,def").order("def", desc=True).limit(20).execute()
    txt = "🛡 Ranking DEF\n"
    for i,u in enumerate(res.data,1):
        if u["tg"]:
            txt += f"{i}. @{u['tg']} — {u['def']}\n"
    await update.message.reply_text(txt)

# ================= MEMBERS =================
async def member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    tg = update.effective_user.username
    supabase.table("members").upsert({
        "uid": uid,
        "tg": tg,
        "registered": False,
        "messages": 0
    }).execute()
    await update.message.reply_text("UID agregado a miembros")

async def memberlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = supabase.table("members").select("*").eq("registered", False).execute()
    txt = "Miembros no registrados:\n"
    for m in res.data:
        if m["tg"]:
            txt += f"@{m['tg']}\n"
    await update.message.reply_text(txt)

async def delist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Delist interactivo (placeholder)")

# ================= WAR (BASE LOGIC) =================
async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Guerra iniciada (placeholder)")

async def warlessa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ATK restante (placeholder)")

async def warlessd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("DEF restante (placeholder)")

async def endwar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supabase.table("users").update({"sent_war": False}).execute()
    await update.message.reply_text("Guerra finalizada")

# ================= MENTIONS =================
async def all_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    race = update.message.text.replace("/all","")
    res = supabase.table("users").select("tg").eq("race", race).execute()
    await update.message.reply_text(" ".join(f"@{u['tg']}" for u in res.data if u["tg"]))

# ================= CANCEL =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Proceso cancelado", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelación global (lógica simple)")

# ================= COMMAND LIST =================
async def getcom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - iniciar\n"
        "/act - actualizar stats\n"
        "/me - perfil\n"
        "/atk - ranking ataque\n"
        "/def - ranking defensa\n"
        "/member - agregar miembro\n"
        "/memberlist - miembros no registrados\n"
        "/delist - eliminar miembros\n"
        "/war HH:MM - iniciar guerra\n"
        "/warlessa - atk restante\n"
        "/warlessd - def restante\n"
        "/endwar - finalizar guerra\n"
        "/allgato /allperro /allrana - mencionar raza\n"
        "/cancel - cancelar proceso\n"
        "/cancelall - cancelar todo\n"
        "/getcom - comandos"
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("me", me), CommandHandler("act", me)],
        states={
            RACE: [CallbackQueryHandler(race_cb)],
            ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, atk)],
            DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, defense)],
            CONFIRM: [CallbackQueryHandler(confirm)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getcom", getcom))
    app.add_handler(CommandHandler("atk", atk_rank))
    app.add_handler(CommandHandler("def", def_rank))
    app.add_handler(CommandHandler("member", member))
    app.add_handler(CommandHandler("memberlist", memberlist))
    app.add_handler(CommandHandler("delist", delist))
    app.add_handler(CommandHandler("war", war))
    app.add_handler(CommandHandler("warlessa", warlessa))
    app.add_handler(CommandHandler("warlessd", warlessd))
    app.add_handler(CommandHandler("endwar", endwar))
    app.add_handler(CommandHandler("cancelall", cancelall))
    app.add_handler(CommandHandler("allgato", all_race))
    app.add_handler(CommandHandler("allperro", all_race))
    app.add_handler(CommandHandler("allrana", all_race))
    app.add_handler(conv)

    app.run_polling()

if __name__ == "__main__":
    main()
