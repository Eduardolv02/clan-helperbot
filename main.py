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
    r = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None

async def belongs(bot, uid):
    gid = get_group_id()
    try:
        m = await bot.get_chat_member(gid, uid)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

async def is_admin(bot, uid):
    gid = get_group_id()
    m = await bot.get_chat_member(gid, uid)
    return m.status in ("administrator", "creator")

# ================= TRACK MEMBERS =================

async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type == "private":
        return

    uid = str(update.effective_user.id)
    tg = update.effective_user.username

    supabase.table("members").upsert({
        "uid": uid,
        "tg": tg
    }).execute()

# ================= START / ACT =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("📩 Escríbeme al privado para registrarte.")
        return ConversationHandler.END

    if not await belongs(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 No perteneces al clan.")
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    user = supabase.table("users").select("uid").eq("uid", uid).execute()

    if user.data:
        await update.message.reply_text("✅ Ya estás registrado.")
        return ConversationHandler.END

    context.user_data["uid"] = uid
    await update.message.reply_text("🎮 Escribe tu nombre en el juego:")
    return ASK_GUSER

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("📩 Escríbeme al privado para actualizar stats.")
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    user = supabase.table("users").select("uid").eq("uid", uid).execute()

    if not user.data:
        await update.message.reply_text("🚫 Debes registrarte primero con /start")
        return ConversationHandler.END

    context.user_data["uid"] = uid
    await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:")
    return ASK_ATK

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Gato", callback_data="gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="rana")]
    ])
    await update.message.reply_text("🏹 Elige tu raza:", reply_markup=kb)
    return ASK_RACE

async def get_race(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["race"] = q.data.capitalize()
    await q.edit_message_text("⚔️ Ingresa tu ATAQUE:")
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
        "guser": context.user_data["guser"],
        "race": context.user_data["race"],
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text),
        "send": False
    }).execute()

    supabase.table("members").update({"registered": True}).eq("uid", uid).execute()
    await update.message.reply_text("✅ Registro completado.")
    return ConversationHandler.END

# ================= WAR =================

async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        return

    supabase.table("users").update({"send": False}).neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Enviar tropas", callback_data="send")]
    ])
    await update.message.reply_text("🔥 GUERRA INICIADA", reply_markup=kb)

async def war_cb(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("users").update({"send": True}).eq("uid", uid).execute()
    await update.callback_query.answer("✅ Tropas enviadas")

async def warless(update, key, emoji):
    users = supabase.table("users").select("*").eq("send", False).execute().data
    total = sum(u[key] for u in users)
    await update.message.reply_text(f"{emoji} Restante: {total:,}")

# ================= DELETE CON CONFIRMACION =================

async def delete(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        return

    members = supabase.table("members").select("*").execute().data
    users = {u["uid"]: u for u in supabase.table("users").select("*").execute().data}

    kb = []
    for m in members:
        label = f"@{m['tg']}"
        if m["uid"] in users:
            label += f" (🎮 {users[m['uid']]['guser']})"
        kb.append([InlineKeyboardButton(label, callback_data=f"askdel_{m['uid']}")])

    await update.message.reply_text("🗑 Selecciona usuario:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_ask(update, context):
    uid = update.callback_query.data.split("_")[1]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{uid}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel")
        ]
    ])
    await update.callback_query.edit_message_text(
        "⚠️ ¿Confirmas expulsar y borrar este usuario?",
        reply_markup=kb
    )

async def delete_confirm(update, context):
    uid = update.callback_query.data.split("_")[1]
    gid = get_group_id()

    await context.bot.ban_chat_member(gid, uid)
    supabase.table("members").delete().eq("uid", uid).execute()
    supabase.table("users").delete().eq("uid", uid).execute()

    await update.callback_query.edit_message_text("❌ Usuario eliminado.")

async def delete_cancel(update, context):
    await update.callback_query.edit_message_text("🚫 Acción cancelada.")

# ================= MENCION BOT =================

async def mention_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        return

    if f"@{context.bot.username}" not in update.message.text:
        return

    uid = update.effective_user.id
    admin = await is_admin(context.bot, uid)

    msg = (
        "🔥 ¡El clan no se rinde!\n"
        "⚔️ Cada guerrero cuenta, envía tus tropas y asegura la victoria.\n\n"
        "📜 *Comandos disponibles:*\n"
        "/atk – Poder de ataque\n"
        "/def – Poder de defensa\n"
        "/warlessa – Ataque restante\n"
        "/warlessd – Defensa restante\n"
    )

    if admin:
        msg += (
            "\n👑 *Admin:*\n"
            "/war – Iniciar guerra\n"
            "/pspy – No registrados\n"
            "/delete – Expulsar miembros"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= APP =================

tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("act", act)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race)],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[]
)

tg_app.add_handler(MessageHandler(filters.ALL, track_member))
tg_app.add_handler(MessageHandler(filters.TEXT, mention_bot))
tg_app.add_handler(conv)

tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", lambda u, c: warless(u, "atk", "⚔️")))
tg_app.add_handler(CommandHandler("warlessd", lambda u, c: warless(u, "def", "🛡")))
tg_app.add_handler(CommandHandler("delete", delete))

tg_app.add_handler(CallbackQueryHandler(war_cb, pattern="send"))
tg_app.add_handler(CallbackQueryHandler(delete_ask, pattern="askdel_"))
tg_app.add_handler(CallbackQueryHandler(delete_confirm, pattern="confirm_"))
tg_app.add_handler(CallbackQueryHandler(delete_cancel, pattern="cancel"))

app = FastAPI()

@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    print("✅ Bot listo")
