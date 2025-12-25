import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
from supabase import create_client

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= BOT =================
ASK_GUSER, ASK_ATK, ASK_DEF = range(3)
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= UTIL =================
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
    r = supabase.table("meta").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None

# ================= LIFESPAN =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializamos Telegram
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook set y bot iniciado")
    yield
    await tg_app.stop()
    print("Bot detenido")

app = FastAPI(lifespan=lifespan)

# ================= WEBHOOK =================
@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

# Health check
@app.get("/")
async def root():
    return {"status": "ok"}
