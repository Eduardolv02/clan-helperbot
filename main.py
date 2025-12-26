import os
import logging
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from supabase import create_client
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxxx.koyeb.app
GROUP_ID = int(os.getenv("GROUP_ID"))

bot = Bot(BOT_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)

# ================= APP =================

app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()

# ================= HELPERS =================

async def ensure_member(update: Update):
    uid = str(update.effective_user.id)
    tg = update.effective_user.username or update.effective_user.full_name

    supabase.table("members").upsert({
        "uid": uid,
        "tg": tg,
        "registered": False
    }).execute()

# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_member(update)

    uid = str(update.effective_user.id)
    tg = update.effective_user.username or update.effective_user.full_name

    supabase.table("users").upsert({
        "uid": uid,
        "tg": tg,
        "atk": 0,
        "def": 0
    }).execute()

    supabase.table("members").update({
        "registered": True
    }).eq("uid", uid).execute()

    await update.message.reply_text("✅ Registro completado. Usa /act para actualizar stats.")

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    try:
        atk = int(context.args[0])
        df = int(context.args[1])
    except:
        await update.message.reply_text("❌ Uso: /act ATK DEF")
        return

    supabase.table("users").update({
        "atk": atk,
        "def": df
    }).eq("uid", uid).execute()

    await update.message.reply_text("📊 Stats actualizados.")

async def atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = supabase.table("users").select("tg,atk").execute().data
    msg = "📊 ATK DEL CLAN\n\n"
    for r in rows:
        msg += f"{r['tg']}: {r['atk']}\n"
    await update.message.reply_text(msg)

async def def_(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = supabase.table("users").select("tg,def").execute().data
    msg = "📊 DEF DEL CLAN\n\n"
    for r in rows:
        msg += f"{r['tg']}: {r['def']}\n"
    await update.message.reply_text(msg)

async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supabase.table("war_votes").delete().neq("uid", "").execute()
    await update.message.reply_text("⚔️ Guerra iniciada. Envíen /act")

async def warlessa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = supabase.table("users").select("uid,tg,atk").execute().data
    msg = "⚔️ ATK PENDIENTE\n\n"
    for u in users:
        if not u["atk"]:
            msg += f"{u['tg']}\n"
    await update.message.reply_text(msg or "✅ Todos enviaron ATK")

async def warlessd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = supabase.table("users").select("uid,tg,def").execute().data
    msg = "⚔️ DEF PENDIENTE\n\n"
    for u in users:
        if not u["def"]:
            msg += f"{u['tg']}\n"
    await update.message.reply_text(msg or "✅ Todos enviaron DEF")

async def endwar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supabase.table("war_votes").delete().neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada.")

async def pspy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = supabase.table("members").select("tg").eq("registered", False).execute().data
    msg = "🕵️ No registrados:\n\n"
    for r in rows:
        msg += f"{r['tg']}\n"
    await update.message.reply_text(msg or "✅ Todos registrados")

# ================= HANDLERS =================

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("act", act))
application.add_handler(CommandHandler("atk", atk))
application.add_handler(CommandHandler("def", def_))
application.add_handler(CommandHandler("war", war))
application.add_handler(CommandHandler("warlessa", warlessa))
application.add_handler(CommandHandler("warlessd", warlessd))
application.add_handler(CommandHandler("endwar", endwar))
application.add_handler(CommandHandler("pspy", pspy))

# ================= WEBHOOK =================

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    await application.process_update(Update.de_json(data, bot))
    return {"ok": True}

# ================= STARTUP =================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    await bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        allowed_updates=["message"]  # 🔴 CLAVE
    )

    await bot.send_message(
        chat_id=GROUP_ID,
        text=(
            "🤖 **BOT DEL CLAN ACTIVO**\n\n"
            "📖 COMANDOS DEL CLAN\n\n"
            "📋 /start – Registro\n"
            "📋 /act – Actualizar stats\n\n"
            "📊 /atk – Ataque clan\n"
            "📊 /def – Defensa clan\n\n"
            "⚔️ /war – Iniciar guerra\n"
            "⚔️ /warlessa – ATK pendiente\n"
            "⚔️ /warlessd – DEF pendiente\n"
            "⚔️ /endwar – Finalizar\n\n"
            "🕵️ /pspy – No registrados"
        )
    )

    yield
    await application.shutdown()

app.router.lifespan_context = lifespan
