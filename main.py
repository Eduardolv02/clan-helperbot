import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
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

# ================= MEMBER TRACK =================

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.chat_member.chat

    supabase.table("settings").upsert({
        "key": "group_id",
        "value": str(chat.id)
    }).execute()

    new = update.chat_member.new_chat_member
    uid = str(new.user.id)

    if new.status in ("member", "administrator", "creator"):
        supabase.table("members").upsert({
            "uid": uid,
            "tg": new.user.username or new.user.first_name,
            "registered": False
        }).execute()
    else:
        supabase.table("members").delete().eq("uid", uid).execute()

# ================= START / REGISTRO =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text(
            "🚫 *Acceso denegado*\n\n"
            "Solo miembros del mejor clan hispanohablante 💪🔥",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    context.user_data["uid"] = uid

    if context.args and context.args[0] == "act":
        await update.message.reply_text("⚔️ Ingresa tu *nuevo ATAQUE*:", parse_mode="Markdown")
        return ASK_ATK

    await update.message.reply_text(
        "🎮 *Registro del Clan*\n\n"
        "Escribe tu *nombre en el juego*:",
        parse_mode="Markdown"
    )
    return ASK_GUSER

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text
    await update.message.reply_text("⚔️ Ingresa tu *ATAQUE*:", parse_mode="Markdown")
    return ASK_ATK

async def get_atk(update, context):
    context.user_data["atk"] = parse_power(update.message.text)
    await update.message.reply_text("🛡 Ingresa tu *DEFENSA*:", parse_mode="Markdown")
    return ASK_DEF

async def get_def(update, context):
    uid = context.user_data["uid"]

    supabase.table("users").upsert({
        "uid": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data.get("guser"),
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text)
    }).execute()

    supabase.table("members").update({
        "registered": True
    }).eq("uid", uid).execute()

    await update.message.reply_text(
        "✅ *Registro completado*\n"
        "Ya formas parte del poder del clan 💪🔥",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ================= WAR =================

async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins", parse_mode="Markdown")
        return

    supabase.table("war_votes").delete().neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Ya envié mis tropas", callback_data="war_yes")]
    ])

    await update.message.reply_text(
        "🔥 *GUERRA INICIADA*\n\n"
        "Cuando envíes tus tropas, confirma aquí 👇",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("war_votes").upsert({
        "uid": uid,
        "voted": True
    }).execute()
    await update.callback_query.answer("✅ Tropas confirmadas")

async def warless(update, key, emoji):
    users = supabase.table("users").select("*").execute().data
    votes = {
        v["uid"] for v in supabase.table("war_votes").select("uid").execute().data
    }
    total = sum(u[key] for u in users if u["uid"] not in votes)
    await update.message.reply_text(f"{emoji} *Pendiente:* `{total:,}`", parse_mode="Markdown")

async def warlessa(update, context):
    await warless(update, "atk", "⚔️")

async def warlessd(update, context):
    await warless(update, "def", "🛡")

async def endwar(update, context):
    supabase.table("war_votes").delete().neq("uid", "").execute()
    await update.message.reply_text("🏁 *Guerra finalizada*", parse_mode="Markdown")

# ================= LISTAS =================

async def show(update, key):
    users = supabase.table("users").select("*").execute().data
    icon = "⚔️" if key == "atk" else "🛡"

    total = 0
    lines = []

    for u in users:
        total += u[key]
        lines.append(f"🎮 *{u['guser']}*\n└ {icon} `{u[key]:,}`")

    msg = (
        f"{icon} *PODER DEL CLAN*\n\n"
        "━━━━━━━━━━━━━━\n"
        + "\n\n".join(lines) +
        "\n━━━━━━━━━━━━━━\n\n"
        f"🔥 *TOTAL:* `{total:,}`"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def atk(update, context):
    await show(update, "atk")

async def defense(update, context):
    await show(update, "def")

# ================= PSPY =================

async def pspy(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins", parse_mode="Markdown")
        return

    members = supabase.table("members").select("*").execute().data
    no_reg = [m for m in members if not m["registered"]]

    if not no_reg:
        await update.message.reply_text("✅ Todos registrados", parse_mode="Markdown")
        return

    msg = "🕵️ *NO REGISTRADOS*\n\n"
    for m in no_reg:
        msg += f"• `{m['tg']}`\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= HELP =================

async def helpc(update, context):
    await update.message.reply_text(
        "📖 *COMANDOS DEL CLAN*\n\n"
        "📋 /start – Registro\n"
        "📋 /act – Actualizar stats\n\n"
        "📊 /atk – Ataque clan\n"
        "📊 /def – Defensa clan\n\n"
        "⚔️ /war – Iniciar guerra\n"
        "⚔️ /warlessa – ATK pendiente\n"
        "⚔️ /warlessd – DEF pendiente\n"
        "⚔️ /endwar – Finalizar\n\n"
        "🕵️ /pspy – No registrados\n",
        parse_mode="Markdown"
    )

# ================= DAILY MESSAGE =================

async def energy_job(app):
    while True:
        now = datetime.now()
        if now.hour == 19 and now.minute == 0:
            gid = get_group_id()
            if gid:
                await app.bot.send_message(
                    gid,
                    "⚡ *ENERGÍA RENOVADA* ⚡",
                    parse_mode="Markdown"
                )
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# ================= TELEGRAM APP =================

tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("act", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[]
)

tg_app.add_handler(ChatMemberHandler(track_member))
tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CommandHandler("helpc", helpc))
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
    tg_app.create_task(energy_job(tg_app))
    print("✅ Bot iniciado correctamente")
