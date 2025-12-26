import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)
from supabase import create_client

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

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

def get_group_id():
    res = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(res.data[0]["value"]) if res.data else None

async def is_admin(bot, user_id):
    gid = get_group_id()
    if not gid:
        return False
    m = await bot.get_chat_member(gid, user_id)
    return m.status in ("administrator", "creator")

async def belongs_to_clan(bot, user_id):
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

# ================= AUTO TRACK MENSAJES =================

async def track_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.chat:
        return

    gid = get_group_id()
    if update.message.chat.id != gid:
        return

    user = update.effective_user
    supabase.table("members").upsert({
        "uid": str(user.id),
        "tg": user.username or user.first_name,
        "registered": False
    }).execute()

# ================= MEMBER TRACK (JOIN / LEAVE) =================

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.chat_member.chat
    supabase.table("settings").upsert({
        "key": "group_id",
        "value": str(chat.id)
    }).execute()

# ================= START / REGISTRO =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo miembros del clan")
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    context.user_data["uid"] = uid

    await update.message.reply_text("🎮 Escribe tu *nombre en el juego*:", parse_mode="Markdown")
    return ASK_GUSER

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text
    await update.message.reply_text("⚔️ Ingresa tu *ATAQUE*:")
    return ASK_ATK

async def get_atk(update, context):
    context.user_data["atk"] = parse_power(update.message.text)
    await update.message.reply_text("🛡 Ingresa tu *DEFENSA*:")
    return ASK_DEF

async def get_def(update, context):
    uid = context.user_data["uid"]

    supabase.table("users").upsert({
        "uid": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data["guser"],
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text)
    }).execute()

    supabase.table("members").update({
        "registered": True
    }).eq("uid", uid).execute()

    await update.message.reply_text("✅ Registro completo")
    return ConversationHandler.END

# ================= WAR =================

async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins")
        return

    supabase.table("war_votes").delete().neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Ya envié mis tropas", callback_data="war_yes")]
    ])

    await update.message.reply_text(
        "🔥 *GUERRA INICIADA*\n\nPulsa cuando envíes tropas",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)

    if not await belongs_to_clan(context.bot, int(uid)):
        await update.callback_query.answer("No perteneces al clan", show_alert=True)
        return

    supabase.table("war_votes").upsert({
        "uid": uid,
        "voted": True
    }).execute()

    await update.callback_query.answer("✅ Tropas confirmadas")

# ================= ELIMINAR =================

async def eliminar(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins")
        return

    if not context.args:
        await update.message.reply_text("Uso: /eliminar <guser>")
        return

    guser = " ".join(context.args)

    supabase.table("users").delete().eq("guser", guser).execute()
    supabase.table("members").update({"registered": False}).execute()

    await update.message.reply_text(f"🗑 Jugador *{guser}* eliminado", parse_mode="Markdown")

# ================= PSPY =================

async def pspy(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins")
        return

    members = supabase.table("members").select("*").execute().data
    no_reg = [m for m in members if not m["registered"]]

    if not no_reg:
        await update.message.reply_text("✅ Todos registrados")
        return

    msg = "🕵️ *NO REGISTRADOS*\n\n"
    for m in no_reg:
        msg += f"• `{m['tg']}`\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= TELEGRAM =================

tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[]
)

tg_app.add_handler(ChatMemberHandler(track_member))
tg_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_message))
tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("eliminar", eliminar))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="war_yes"))

# ================= FASTAPI =================

app = FastAPI()

@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)

    gid = get_group_id()
    if gid:
        await tg_app.bot.send_message(
            gid,
            "🤖 *Bot del Clan ACTIVADO*\n\n"
            "Listo para registrar guerreros,\n"
            "coordinar guerras y vigilar desertores 💀🔥",
            parse_mode="Markdown"
        )

    print("✅ BOT ONLINE")
