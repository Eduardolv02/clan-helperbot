import os
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
from supabase import create_client

# ================== ENV ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# ================== SUPABASE ==================

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================== STATES ==================

ASK_GUSER, ASK_ATK, ASK_DEF = range(3)

# ================== APPS ==================

app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================== UTIL ==================

def parse_power(t: str) -> int:
    t = t.lower().replace(" ", "")
    if t.endswith("k"):
        return int(float(t[:-1]) * 1_000)
    if t.endswith("m"):
        return int(float(t[:-1]) * 1_000_000)
    return int(t)

async def is_admin(bot, gid, uid):
    m = await bot.get_chat_member(gid, uid)
    return m.status in ("administrator", "creator")

def get_group_id():
    r = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None

# ================== START / REGISTRO ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["uid"] = str(update.effective_user.id)
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
    username = update.effective_user.username

    # USERS
    supabase.table("users").upsert({
        "uid": uid,
        "tg": username,
        "guser": context.user_data["guser"],
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text),
    }).execute()

    # MEMBERS
    supabase.table("members").upsert({
        "uid": uid,
        "tg": username,
        "registered": True,
    }).execute()

    await update.message.reply_text("✅ Registro completado")
    return ConversationHandler.END

# ================== WAR ==================

async def war(update, context):
    gid = get_group_id()
    if not await is_admin(context.bot, gid, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

    # limpiar votos anteriores
    supabase.table("war_votes").delete().neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Ya envié mis tropas", callback_data="war_yes")]
    ])
    await update.message.reply_text("🔥 GUERRA INICIADA", reply_markup=kb)

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)

    supabase.table("war_votes").upsert({
        "uid": uid,
        "voted": True
    }).execute()

    await update.callback_query.answer("✅ Tropas enviadas")

# ================== PSPY (ADMINS) ==================

async def pspy(update, context):
    gid = get_group_id()
    if not await is_admin(context.bot, gid, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

    users = {u["uid"] for u in supabase.table("users").select("uid").execute().data}
    members = supabase.table("members").select("*").execute().data

    msg = "🕵️ *NO REGISTRADOS*\n\n"
    missing = False

    for m in members:
        if m["uid"] not in users:
            tg = f"@{m['tg']}" if m["tg"] else "(sin username)"
            msg += f"• {tg}\n"
            missing = True

    if not missing:
        msg += "✅ Todos registrados"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================== HANDLERS ==================

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

# ================== WEBHOOK ==================

@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "ok"}

# ================== STARTUP ==================

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook seteado correctamente")
