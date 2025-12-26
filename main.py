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

# ================== APP ==================

app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

# ================== HELPERS ==================

def parse_power(t: str) -> int:
    t = t.lower().replace(" ", "")
    if t.endswith("k"):
        return int(float(t[:-1]) * 1_000)
    if t.endswith("m"):
        return int(float(t[:-1]) * 1_000_000)
    return int(t)

def get_group_id():
    r = supabase.table("config").select("value").eq("key", "group_id").execute()
    return str(r.data[0]["value"]) if r.data else None

async def belongs_to_clan(bot, user_id: int) -> bool:
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

async def is_admin(bot, user_id: int) -> bool:
    gid = get_group_id()
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("administrator", "creator")
    except:
        return False

# ================== REGISTRO ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text("❌ Debes pertenecer al clan.")
        return ConversationHandler.END

    context.user_data["uid"] = str(update.effective_user.id)
    await update.message.reply_text("🎮 Nombre en el juego:")
    return ASK_GUSER

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text
    await update.message.reply_text("⚔️ ATK:")
    return ASK_ATK

async def get_atk(update, context):
    context.user_data["atk"] = parse_power(update.message.text)
    await update.message.reply_text("🛡 DEF:")
    return ASK_DEF

async def get_def(update, context):
    uid = context.user_data["uid"]

    supabase.table("users").upsert({
        "uid": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data["guser"],
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text),
    }).execute()

    supabase.table("members").upsert({
        "uid": uid,
        "tg": update.effective_user.username,
        "registered": True,
    }).execute()

    await update.message.reply_text("✅ Registro actualizado")
    return ConversationHandler.END

# ================== STATS ==================

async def atk_list(update, context):
    rows = supabase.table("users").select("guser,atk").order("atk", desc=True).execute().data
    msg = "⚔️ *ATK*\n\n"
    for r in rows:
        msg += f"{r['guser']}: {r['atk']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def def_list(update, context):
    rows = supabase.table("users").select("guser,def").order("def", desc=True).execute().data
    msg = "🛡 *DEF*\n\n"
    for r in rows:
        msg += f"{r['guser']}: {r['def']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ================== WAR ==================

async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

    supabase.table("war_votes").delete().neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Tropas enviadas", callback_data="war_yes")]
    ])
    await update.message.reply_text("🔥 *GUERRA INICIADA*", reply_markup=kb, parse_mode="Markdown")

async def war_vote(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("war_votes").upsert({
        "uid": uid,
        "sent": True
    }).execute()
    await update.callback_query.answer("✅ Registrado")

async def endwar(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        return
    supabase.table("war_votes").delete().neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada")

# ================== PSPY ==================

async def pspy(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("❌ Solo admins")
        return

    users = {u["uid"] for u in supabase.table("users").select("uid").execute().data}
    members = supabase.table("members").select("*").execute().data

    msg = "🕵️ *NO REGISTRADOS*\n\n"
    missing = False

    for m in members:
        if m["uid"] not in users:
            msg += f"• @{m['tg']}\n"
            missing = True

    if not missing:
        msg += "✅ Todos registrados"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================== HELP ==================

async def helpc(update, context):
    await update.message.reply_text(
        """📋 *COMANDOS*

/start – Registrarse
/atk – Lista ATK
/def – Lista DEF

⚔️ *GUERRA*
/war – Iniciar
/endwar – Finalizar

🔍 *ADMIN*
/pspy – No registrados
""",
        parse_mode="Markdown"
    )

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
tg_app.add_handler(CommandHandler("atk", atk_list))
tg_app.add_handler(CommandHandler("def", def_list))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("pspy", pspy))
tg_app.add_handler(CommandHandler("helpc", helpc))
tg_app.add_handler(CallbackQueryHandler(war_vote, pattern="war_yes"))

# ================== WEBHOOK ==================

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "ok"}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook listo")
