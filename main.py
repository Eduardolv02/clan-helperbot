import os
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ChatMemberHandler,
    ContextTypes, filters
)
from supabase import create_client
from fastapi import FastAPI, Request
import uvicorn

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEROKU_APP_URL = os.getenv("HEROKU_APP_URL")  # https://your-app.herokuapp.com

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ASK_GUSER, ASK_ATK, ASK_DEF = range(3)

# ================= UTIL =================
def parse_power(text: str) -> int:
    t = text.lower().replace(" ", "")
    if t.endswith("k"):
        return int(float(t[:-1]) * 1_000)
    if t.endswith("m"):
        return int(float(t[:-1]) * 1_000_000)
    return int(t)

async def get_group_id():
    res = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(res.data[0]["value"]) if res.data else None

async def is_admin(bot, user_id):
    gid = await get_group_id()
    if not gid:
        return False
    m = await bot.get_chat_member(gid, user_id)
    return m.status in ["administrator", "creator"]

# ================= MEMBER TRACK =================
async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.chat_member.chat
    supabase.table("settings").upsert({
        "key": "group_id",
        "value": str(chat.id)
    }).execute()

    new = update.chat_member.new_chat_member
    uid = str(new.user.id)

    if new.status in ["member", "administrator", "creator"]:
        supabase.table("members").upsert({
            "tg_id": uid,
            "tg_username": new.user.username or new.user.first_name,
            "registered": False
        }).execute()
    else:
        supabase.table("members").delete().eq("tg_id", uid).execute()

# ================= START / REGISTRO =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    context.user_data["uid"] = uid

    if context.args and context.args[0] == "act":
        await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:")
        return ASK_ATK

    await update.message.reply_text("🎮 Ingresa tu nombre de usuario del juego:")
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
        "tg_id": uid,
        "tg_username": update.effective_user.username,
        "guser": context.user_data.get("guser"),
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text)
    }).execute()

    supabase.table("members").update({
        "registered": True
    }).eq("tg_id", uid).execute()

    await update.message.reply_text("✅ Registro / actualización completada")
    return ConversationHandler.END

# ================= WAR =================
async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins.")
        return

    supabase.table("war_votes").delete().neq("tg_id", "0").execute()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Ya envié mis tropas", callback_data="war_yes")]
    ])

    await update.message.reply_text(
        "🔥 *GUERRA INICIADA*\nPulsa cuando envíes tropas",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def war_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    supabase.table("war_votes").upsert({
        "tg_id": str(query.from_user.id),
        "vote": "yes"
    }).execute()

    await query.reply_text("✅ Tropas enviadas")

async def warless(update, key: str, emoji: str):
    users = supabase.table("users").select("*").execute().data
    votes = {
        v["tg_id"] for v in supabase.table("war_votes").select("tg_id").execute().data
    }

    total = sum(u[key] for u in users if u["tg_id"] not in votes)
    await update.message.reply_text(f"{emoji} Pendiente: {total:,}")

async def warlessa(update, context):
    await warless(update, "atk", "⚔️")

async def warlessd(update, context):
    await warless(update, "def", "🛡")

async def endwar(update, context):
    supabase.table("war_votes").delete().neq("tg_id", "0").execute()
    await update.message.reply_text("🏁 Guerra finalizada")

# ================= LISTAS =================
async def show(update, key):
    users = supabase.table("users").select("*").execute().data
    total = 0
    msg = ""

    for u in users:
        total += u[key]
        msg += f"🎮 {u['guser']} — {u[key]:,}\n"

    msg += f"\n🔥 TOTAL: {total:,}"
    await update.message.reply_text(msg)

async def atk(update, context):
    await show(update, "atk")

async def defense(update, context):
    await show(update, "def")

# ================= PSPY (ADMIN ONLY) =================
async def pspy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins.")
        return

    members = supabase.table("members").select("*").execute().data
    no_reg = [m for m in members if not m["registered"]]

    msg = "🕵️ *NO REGISTRADOS:*\n\n"
    msg += "\n".join(f"• {m['tg_username']}" for m in no_reg) if no_reg else "✅ Todos registrados"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= DAILY MESSAGE =================
async def energy_job(app):
    while True:
        now = datetime.now()
        if now.hour == 19 and now.minute == 0:
            gid = await get_group_id()
            if gid:
                await app.bot.send_message(
                    gid,
                    "⚡ *ENERGÍA RENOVADA* ⚡",
                    parse_mode="Markdown"
                )
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# ================= TELEGRAM BOT APP =================
tg_app = ApplicationBuilder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("act", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)]
    },
    fallbacks=[]
)

# Handlers
tg_app.add_handler(ChatMemberHandler(track_member))
tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="war_yes"))

# ================= FASTAPI APP =================
app = FastAPI()

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.update_queue.put(update)
    return {"ok": True}

@app.on_event("startup")
async def startup_event():
    # Tareas de fondo
    tg_app.create_task(energy_job(tg_app))
    # Inicializa bot
    tg_app.create_task(tg_app.initialize())
    # Configura webhook en Telegram
    import requests
    webhook_url = f"{HEROKU_APP_URL}/webhook"
    requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}")

# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
