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

# ================= START / REGISTRO =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Usted no pertenece al clan.")
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    
    # Verificar si ya está registrado
    member = supabase.table("members").select("registered").eq("uid", uid).execute()
    if member.data and member.data[0]["registered"]:
        await update.message.reply_text("✅ Ya estás registrado en el clan.")
        return ConversationHandler.END

    context.user_data["uid"] = uid

    if context.args and context.args[0] == "act":
        await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:")
        return ASK_ATK

    await update.message.reply_text("🎮 Escribe tu nombre en el juego:")
    return ASK_GUSER

async def get_guser(update, context):
    context.user_data["guser"] = update.message.text
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Gato", callback_data="race_gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="race_perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="race_rana")]
    ])
    
    await update.message.reply_text("🏹 Selecciona tu RAZA:", reply_markup=kb)
    return ASK_RACE

async def get_race(update, context):
    query = update.callback_query
    await query.answer()
    
    race_map = {
        "race_gato": "Gato",
        "race_perro": "Perro",
        "race_rana": "Rana"
    }
    context.user_data["race"] = race_map.get(query.data, "Desconocida")
    
    await query.edit_message_text("⚔️ Ingresa tu ATAQUE:")
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
        "race": context.user_data.get("race"),
        "atk": context.user_data["atk"],
        "def": parse_power(update.message.text)
    }).execute()

    supabase.table("members").update({
        "registered": True
    }).eq("uid", uid).execute()

    await update.message.reply_text("✅ Registro completado. ¡Bienvenido al clan!")
    return ConversationHandler.END

# ================= ACT =================

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo miembros del clan.")
        return ConversationHandler.END

    uid = str(update.effective_user.id)
    member = supabase.table("members").select("registered").eq("uid", uid).execute()
    if not member.data or not member.data[0]["registered"]:
        await update.message.reply_text("🚫 Debes registrarte primero con /start.")
        return ConversationHandler.END

    context.user_data["uid"] = uid
    await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:")
    return ASK_ATK

# ================= WAR =================

async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return

    supabase.table("war_votes").delete().neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Enviar las tropas", callback_data="war_yes")]
    ])

    await update.message.reply_text("🔥 GUERRA INICIADA. Presiona para enviar tropas:", reply_markup=kb)

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("war_votes").upsert({
        "uid": uid,
        "voted": True
    }).execute()
    await update.callback_query.answer("✅ Tropas enviadas")

async def warless(update, key, emoji):
    users = supabase.table("users").select("*").execute().data
    votes = {v["uid"] for v in supabase.table("war_votes").select("uid").execute().data}
    total = sum(u[key] for u in users if u["uid"] not in votes)
    await update.message.reply_text(f"{emoji} Restante: {total:,}")

async def warlessa(update, context):
    await warless(update, "atk", "⚔️")

async def warlessd(update, context):
    await warless(update, "def", "🛡")

async def endwar(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return

    supabase.table("war_votes").delete().neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada. Puedes iniciar una nueva con /war.")

# ================= LISTAS =================

async def show(update, key):
    members_registered = {m["uid"] for m in supabase.table("members").select("uid").eq("registered", True).execute().data}
    users = [u for u in supabase.table("users").select("*").execute().data if u["uid"] in members_registered]
    
    users.sort(key=lambda u: u[key], reverse=True)
    
    icon = "⚔️" if key == "atk" else "🛡"
    total = sum(u[key] for u in users)
    
    lines = [f"🎮 {u['guser']}\n└ {icon} {u[key]:,}" for u in users]
    
    msg = f"{icon} PODER DEL CLAN\n\n" + "\n\n".join(lines) + f"\n\n🔥 TOTAL: {total:,}"
    await update.message.reply_text(msg)

async def atk(update, context):
    await show(update, "atk")

async def defense(update, context):
    await show(update, "def")

# ================= APP =================

tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("act", act)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="race_")],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[]
)

tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="war_yes"))

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
