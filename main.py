import os
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
from supabase import create_client

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ASK_GUSER, ASK_ATK, ASK_DEF = range(3)

app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ---------------- UTIL ----------------

def parse_power(t):
    t = t.lower().replace(" ", "")
    if t.endswith("k"): return int(float(t[:-1]) * 1_000)
    if t.endswith("m"): return int(float(t[:-1]) * 1_000_000)
    return int(t)

async def is_admin(bot, gid, uid):
    m = await bot.get_chat_member(gid, uid)
    return m.status in ["administrator", "creator"]

def get_group_id():
    r = supabase.table("meta").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None

# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    context.user_data["uid"] = uid
    await update.message.reply_text("🎮 Ingresa tu nombre del juego:")
    return ASK_GUSER

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text
    await update.message.reply_text("⚔️ Ingresa tu ATAQUE:")
    return ASK_ATK

async def get_atk(update, context):
    context.user_data["atk"] = parse_power(update.message.text)
    await update.message.reply_text("🛡 Ingresa tu DEFENSA:")
    return ASK_DEF

async def get_def(update, context):
    uid = context.user_data["uid"]
    supabase.table("users").upsert({
        "id": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data["guser"],
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text)
    }).execute()

    supabase.table("members").upsert({
        "id": uid,
        "tg": update.effective_user.username,
        "registered": True
    }).execute()

    await update.message.reply_text("✅ Registro / actualización completada")
    return ConversationHandler.END

# ---------------- WAR ----------------

async def war(update, context):
    gid = get_group_id()
    if not await is_admin(context.bot, gid, update.effective_user.id):
        return await update.message.reply_text("❌ Solo admins")

    supabase.table("war_votes").delete().neq("user_id", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Ya envié mis tropas", callback_data="war_yes")]
    ])
    await update.message.reply_text("🔥 GUERRA INICIADA", reply_markup=kb)

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("war_votes").upsert({
        "user_id": uid,
        "status": "yes"
    }).execute()
    await update.callback_query.answer("✅ Tropas enviadas")

# ---------------- PSPY (ADMINS) ----------------

async def pspy(update, context):
    gid = get_group_id()
    if not await is_admin(context.bot, gid, update.effective_user.id):
        return await update.message.reply_text("❌ Solo admins")

    users = {u["id"] for u in supabase.table("users").select("id").execute().data}
    members = supabase.table("members").select("*").execute().data

    msg = "🕵️ *NO REGISTRADOS*\n\n"
    missing = False
    for m in members:
        if m["id"] not in users:
            msg += f"• {m['tg']}\n"
            missing = True

    if not missing:
        msg += "✅ Todos registrados"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------- HANDLERS ----------------

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[]
)

tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="war_yes"))

# ---------------- WEBHOOK ----------------

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.bot.set_webhook(WEBHOOK_URL)

