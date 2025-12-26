import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)
from supabase import create_client

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# ================= SUPABASE =================
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= STATES =================
ASK_GUSER, ASK_ATK, ASK_DEF = range(3)

# ================= APP =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================= UTIL =================
def parse_power(t: str) -> int:
    t = t.lower().replace(" ", "")
    if t.endswith("k"):
        return int(float(t[:-1]) * 1_000)
    if t.endswith("m"):
        return int(float(t[:-1]) * 1_000_000)
    return int(t)

def get_group_id():
    r = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None

async def is_admin(bot, uid):
    gid = get_group_id()
    if not gid:
        return False
    m = await bot.get_chat_member(gid, uid)
    return m.status in ("administrator", "creator")

async def belongs_to_clan(bot, uid):
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, uid)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

# ================= START / ACT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text(
            "❌ Usted no pertenece al mejor clan hispanohablante."
        )
        return ConversationHandler.END

    context.user_data["uid"] = uid

    if context.args and context.args[0] == "act":
        await update.message.reply_text("⚔️ Ingresa tu ATAQUE:")
        return ASK_ATK

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
        "uid": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data.get("guser"),
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text),
    }).execute()

    supabase.table("members").upsert({
        "uid": uid,
        "tg": update.effective_user.username,
        "registered": True,
    }).execute()

    await update.message.reply_text("✅ Registro / actualización completada")
    return ConversationHandler.END

# ================= WAR =================
async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

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

# ================= WARLESS =================
async def warless(update, key, emoji):
    users = supabase.table("users").select("uid", key).execute().data
    voted = {
        v["uid"] for v in supabase.table("war_votes").select("uid").execute().data
    }

    total = sum(u[key] for u in users if u["uid"] not in voted)
    await update.message.reply_text(f"{emoji} Pendiente: {total:,}")

async def warlessa(update, context):
    await warless(update, "atk", "⚔️")

async def warlessd(update, context):
    await warless(update, "def", "🛡")

async def endwar(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        return
    supabase.table("war_votes").delete().neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada")

# ================= LISTAS =================
async def show(update, key):
    users = supabase.table("users").select("guser", key).execute().data
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

# ================= PSPY =================
async def pspy(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        return

    members = supabase.table("members").select("*").execute().data
    no_reg = [m for m in members if not m["registered"]]

    msg = "🕵️ *NO REGISTRADOS*\n\n"
    msg += "\n".join(f"• {m['tg']}" for m in no_reg) if no_reg else "✅ Todos registrados"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= HANDLERS =================
conv = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("act", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[]
)

tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="war_yes"))

# ================= WEBHOOK =================
@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "ok"}

# ================= STARTUP =================
@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.bot.set_webhook(WEBHOOK_URL)
    print("✅ Bot online y webhook activo")
