import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from supabase import create_client

# ================= ENV =================

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# ================= SUPABASE =================

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= TELEGRAM =================

ASK_GUSER, ASK_ATK, ASK_DEF = range(3)

tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= FASTAPI =================

app = FastAPI()

# ================= UTIL =================

def parse_power(text: str) -> int:
    t = text.lower().replace(" ", "")
    if t.endswith("k"):
        return int(float(t[:-1]) * 1_000)
    if t.endswith("m"):
        return int(float(t[:-1]) * 1_000_000)
    return int(t)

async def is_admin(bot, gid, uid) -> bool:
    member = await bot.get_chat_member(gid, uid)
    return member.status in ("administrator", "creator")

def get_group_id():
    res = supabase.table("meta").select("value").eq("key", "group_id").execute()
    return int(res.data[0]["value"]) if res.data else None

# ================= CONVERSATION =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["uid"] = str(update.effective_user.id)
    await update.message.reply_text("🎮 Ingresa tu nombre del juego:")
    return ASK_GUSER

async def get_guser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["guser"] = update.message.text
    await update.message.reply_text("⚔️ Ingresa tu ATAQUE:")
    return ASK_ATK

async def get_atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["atk"] = parse_power(update.message.text)
    await update.message.reply_text("🛡 Ingresa tu DEFENSA:")
    return ASK_DEF

async def get_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data["uid"]

    supabase.table("users").upsert({
        "id": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data["guser"],
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text),
    }).execute()

    supabase.table("members").upsert({
        "id": uid,
        "tg": update.effective_user.username,
        "registered": True,
    }).execute()

    await update.message.reply_text("✅ Registro / actualización completada")
    return ConversationHandler.END

# ================= COMMANDS =================

async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = get_group_id()
    if not await is_admin(context.bot, gid, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

    supabase.table("war_votes").delete().neq("user_id", "").execute()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Ya envié mis tropas", callback_data="war_yes")]
    ])

    await update.message.reply_text("🔥 GUERRA INICIADA", reply_markup=keyboard)

async def war_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.callback_query.from_user.id)

    supabase.table("war_votes").upsert({
        "user_id": uid,
        "status": "yes",
    }).execute()

    await update.callback_query.answer("✅ Tropas enviadas")

async def pspy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = get_group_id()
    if not await is_admin(context.bot, gid, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

    users = {
        u["id"]
        for u in supabase.table("users").select("id").execute().data
    }
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

# ================= HANDLERS =================

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[],
)

tg_app.add_handler(conv_handler)
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_yes$"))

# ================= WEBHOOK =================

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

# ================= LIFECYCLE =================

@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)

@app.on_event("shutdown")
async def on_shutdown():
    await tg_app.shutdown()

# ================= MAIN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
