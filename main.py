import os
from fastapi import FastAPI, Request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from supabase import create_client

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ASK_GUSER, ASK_RACE, ASK_ATK, ASK_DEF = range(4)

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

async def belongs_to_clan(bot, user_id):
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

async def is_admin(bot, user_id):
    gid = get_group_id()
    if not gid:
        return False
    m = await bot.get_chat_member(gid, user_id)
    return m.status in ("administrator", "creator")

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("📩 Escríbeme al privado para registrarte.")
        return ConversationHandler.END

    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 No perteneces al clan.")
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    exists = supabase.table("users").select("uid").eq("uid", uid).execute()

    if exists.data:
        await update.message.reply_text("✅ Ya estás registrado.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["uid"] = uid

    await update.message.reply_text("🎮 Escribe tu nombre en el juego:")
    return ASK_GUSER

async def get_guser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["guser"] = update.message.text.strip()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Gato", callback_data="race_gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="race_perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="race_rana")]
    ])

    await update.message.reply_text("🏹 Selecciona tu RAZA:", reply_markup=kb)
    return ASK_RACE

async def get_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    race_map = {
        "race_gato": "Gato",
        "race_perro": "Perro",
        "race_rana": "Rana"
    }

    race = race_map.get(q.data)
    if not race:
        await q.edit_message_text("❌ Raza inválida.")
        return ConversationHandler.END

    context.user_data["race"] = race
    await q.edit_message_text("⚔️ Ingresa tu ATAQUE:")
    return ASK_ATK

# ================= ACT =================

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("📩 Escríbeme al privado para actualizar.")
        return ConversationHandler.END

    uid = str(update.effective_user.id)

    user = supabase.table("users").select("uid").eq("uid", uid).execute()
    if not user.data:
        await update.message.reply_text("❌ No estás registrado. Usa /start.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["uid"] = uid
    context.user_data["is_act"] = True

    await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:")
    return ASK_ATK

# ================= ATK / DEF =================

async def get_atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["atk"] = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido. Ej: 120k o 1.5m")
        return ASK_ATK

    await update.message.reply_text("🛡 Ingresa tu DEFENSA:")
    return ASK_DEF

async def get_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        defense = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return ASK_DEF

    uid = context.user_data.get("uid")
    if not uid:
        await update.message.reply_text("⚠️ Sesión inválida. Usa /start o /act.")
        return ConversationHandler.END

    # ===== /act =====
    if context.user_data.get("is_act"):
        supabase.table("users").update({
            "atk": context.user_data["atk"],
            "def": defense,
            "sent_war": False
        }).eq("uid", uid).execute()

        await update.message.reply_text("✅ Poder actualizado.")
        return ConversationHandler.END

    # ===== /start =====
    for key in ("guser", "race", "atk"):
        if key not in context.user_data:
            await update.message.reply_text("⚠️ Registro incompleto. Usa /start.")
            return ConversationHandler.END

    supabase.table("users").insert({
        "uid": uid,
        "tg": update.effective_user.username,
        "guser": context.user_data["guser"],
        "race": context.user_data["race"],
        "atk": context.user_data["atk"],
        "def": defense,
        "sent_war": False
    }).execute()

    supabase.table("members").update(
        {"registered": True}
    ).eq("uid", uid).execute()

    await update.message.reply_text("✅ Registro completado.")
    return ConversationHandler.END

# ================= WAR =================

async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return

    supabase.table("users").update({"sent_war": False}).neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Enviar tropas", callback_data="war_send")]
    ])

    await update.message.reply_text("🔥 GUERRA INICIADA", reply_markup=kb)

async def war_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.callback_query.from_user.id)
    supabase.table("users").update({"sent_war": True}).eq("uid", uid).execute()
    await update.callback_query.answer("✅ Tropas enviadas")

async def warless(update, key, emoji):
    users = supabase.table("users").select("*").eq("sent_war", False).execute().data
    total = sum(u.get(key, 0) for u in users)
    await update.message.reply_text(f"{emoji} Restante: {total:,}")

async def warlessa(update, context):
    await warless(update, "atk", "⚔️")

async def warlessd(update, context):
    await warless(update, "def", "🛡")

async def endwar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return

    supabase.table("users").update({"sent_war": False}).neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada.")

# ================= ERROR HANDLER =================

async def error_handler(update, context):
    print("❌ ERROR:", context.error)

# ================= APP =================

tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        CommandHandler("act", act)
    ],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
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
tg_app.add_handler(CallbackQueryHandler(war_send, pattern="^war_send$"))
tg_app.add_error_handler(error_handler)

# ================= FASTAPI =================

app = FastAPI()

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    await tg_app.update_queue.put(Update.de_json(data, tg_app.bot))
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.start()
    print("✅ Bot listo y estable")
