import os
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
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
    r = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None

async def belongs(bot, uid):
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, uid)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

async def is_admin(bot, uid):
    gid = get_group_id()
    if not gid:
        return False
    m = await bot.get_chat_member(gid, uid)
    return m.status in ("administrator", "creator")

# ================= /start =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "📩 *Para registrarte debes escribirme al privado.*",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    if not await belongs(context.bot, update.effective_user.id):
        await update.message.reply_text(
            "🚫 *No perteneces al clan.*\n\nÚnete primero y luego vuelve 😉",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    exists = supabase.table("users").select("uid").eq("uid", uid).execute()
    if exists.data:
        await update.message.reply_text(
            "✅ *Ya estás registrado.*\n\nSi necesitas actualizar tu poder usa /act",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["uid"] = uid

    await update.message.reply_text(
        "🎮 *Bienvenido al clan*\n\nEscribe tu *nombre dentro del juego*:",
        parse_mode="Markdown"
    )
    return ASK_GUSER

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text.strip()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Gato", callback_data="race_gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="race_perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="race_rana")]
    ])

    await update.message.reply_text(
        "🧬 *Selecciona tu raza:*",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    return ASK_RACE

async def get_race(update, context):
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

    await q.edit_message_text(
        f"⚔️ *Raza seleccionada:* {race}\n\nAhora escribe tu *ATAQUE* (ej: 120k, 2.5m)",
        parse_mode="Markdown"
    )
    return ASK_ATK

async def get_atk_start(update, context):
    try:
        context.user_data["atk"] = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido. Usa números, k o m.")
        return ASK_ATK

    await update.message.reply_text(
        "🛡 *Perfecto.* Ahora escribe tu *DEFENSA*:",
        parse_mode="Markdown"
    )
    return ASK_DEF

async def get_def_start(update, context):
    try:
        defense = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido. Intenta de nuevo.")
        return ASK_DEF

    uid = context.user_data["uid"]

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

    await update.message.reply_text(
        "🎉 *Registro completado con éxito.*\n\nPrepárate para la guerra ⚔️",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ================= /act =================

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "📩 Escríbeme al privado para actualizar tu poder."
        )
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    user = supabase.table("users").select("uid").eq("uid", uid).execute()
    if not user.data:
        await update.message.reply_text(
            "❌ No estás registrado.\nUsa /start primero."
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["uid"] = uid

    await update.message.reply_text(
        "⚔️ *Actualización de poder*\n\nEscribe tu nuevo *ATAQUE*:",
        parse_mode="Markdown"
    )
    return ASK_ATK

async def get_atk_act(update, context):
    try:
        context.user_data["atk"] = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido. Intenta de nuevo.")
        return ASK_ATK

    await update.message.reply_text(
        "🛡 Ahora escribe tu nueva *DEFENSA*:",
        parse_mode="Markdown"
    )
    return ASK_DEF

async def get_def_act(update, context):
    try:
        defense = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return ASK_DEF

    uid = context.user_data["uid"]

    supabase.table("users").update({
        "atk": context.user_data["atk"],
        "def": defense,
        "sent_war": False
    }).eq("uid", uid).execute()

    await update.message.reply_text(
        "✅ *Poder actualizado correctamente.*\n\n¡Listo para la batalla! ⚔️",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ================= APP =================

tg_app = Application.builder().token(TOKEN).build()

conv_start = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
        ASK_ATK: [MessageHandler(filters.TEXT, get_atk_start)],
        ASK_DEF: [MessageHandler(filters.TEXT, get_def_start)],
    },
    fallbacks=[]
)

conv_act = ConversationHandler(
    entry_points=[CommandHandler("act", act)],
    states={
        ASK_ATK: [MessageHandler(filters.TEXT, get_atk_act)],
        ASK_DEF: [MessageHandler(filters.TEXT, get_def_act)],
    },
    fallbacks=[]
)

tg_app.add_handler(conv_start)
tg_app.add_handler(conv_act)

# ================= FASTAPI =================

app = FastAPI()

@app.post("/webhook")
async def webhook(req: Request):
    await tg_app.update_queue.put(Update.de_json(await req.json(), tg_app.bot))
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.start()
    print("✅ Bot listo, fluido y estable")
