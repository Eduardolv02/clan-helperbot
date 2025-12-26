import os
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
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
    try:
        if t.endswith("k"):
            return int(float(t[:-1]) * 1_000)
        elif t.endswith("m"):
            return int(float(t[:-1]) * 1_000_000)
        return int(t)
    except:
        return None

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
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("administrator", "creator")
    except:
        return False

# ================= START / ACT UNIFICADO =================
async def start_act_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Verifica si ya hay un proceso activo
    if context.user_data.get("active_process"):
        await update.message.reply_text("⚠️ Tienes un proceso activo. Termínalo o usa /cancel para reiniciar.")
        return ConversationHandler.END

    if not await belongs_to_clan(context.bot, user_id):
        await update.message.reply_text("🚫 No perteneces al clan.")
        return ConversationHandler.END

    uid = str(user_id)
    exists = supabase.table("users").select("uid").eq("uid", uid).execute()
    context.user_data.clear()
    context.user_data["uid"] = uid
    context.user_data["active_process"] = True

    if exists.data:
        # ACTUALIZACIÓN
        context.user_data["is_act"] = True
        await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:", parse_mode="Markdown")
    else:
        # REGISTRO
        context.user_data["is_act"] = False
        await update.message.reply_text("🎮 Escribe tu nombre en el juego:", parse_mode="Markdown")
    return ASK_GUSER if not context.user_data.get("is_act") else ASK_ATK

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
    query = update.callback_query
    await query.answer()
    race_map = {
        "race_gato": "Gato",
        "race_perro": "Perro",
        "race_rana": "Rana"
    }
    race = race_map.get(query.data)
    if not race:
        await query.edit_message_text("❌ Raza inválida.")
        return ConversationHandler.END

    context.user_data["race"] = race
    await query.edit_message_text("⚔️ Ingresa tu ATAQUE:")
    return ASK_ATK

async def get_atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    power = parse_power(update.message.text)
    if power is None:
        await update.message.reply_text("❌ Valor inválido. Ej: 120k o 1.5m")
        return ASK_ATK
    context.user_data["atk"] = power
    await update.message.reply_text("🛡 Ingresa tu DEFENSA:")
    return ASK_DEF

async def get_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    defense = parse_power(update.message.text)
    if defense is None:
        await update.message.reply_text("❌ Valor inválido. Ej: 80k o 1m")
        return ASK_DEF

    uid = context.user_data["uid"]
    is_act = context.user_data.get("is_act")

    if is_act:
        supabase.table("users").update({
            "atk": context.user_data["atk"],
            "def": defense,
            "sent_war": False
        }).eq("uid", uid).execute()
        await update.message.reply_text("✅ Poder actualizado con éxito.")
    else:
        supabase.table("users").insert({
            "uid": uid,
            "tg": update.effective_user.username,
            "guser": context.user_data["guser"],
            "race": context.user_data["race"],
            "atk": context.user_data["atk"],
            "def": defense,
            "sent_war": False
        }).execute()
        supabase.table("members").update({"registered": True}).eq("uid", uid).execute()
        await update.message.reply_text("✅ Registro completado con éxito.")

    context.user_data.clear()
    return ConversationHandler.END

# ================= CANCEL =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚫 Proceso cancelado.")
    return ConversationHandler.END

async def cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins pueden usar /cancelall")
        return
    # Limpiar todos los procesos activos de todos los usuarios
    for user_data in context.application.user_data.values():
        user_data.clear()
    await update.message.reply_text("🚫 Todos los procesos activos fueron cancelados.")

# ================= COMANDOS GLOBALES =================
async def atk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = supabase.table("users").select("*").execute().data
    lines = [f"🎮 {u['guser']}\n└ ⚔️ {u['atk']:,}" for u in users]
    total = sum(u["atk"] for u in users)
    msg = "⚔️ *Poder de Ataque del Clan*\n\n" + "\n\n".join(lines) + f"\n\n🔥 TOTAL: {total:,}"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def def_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = supabase.table("users").select("*").execute().data
    lines = [f"🎮 {u['guser']}\n└ 🛡 {u['def']:,}" for u in users]
    total = sum(u["def"] for u in users)
    msg = "🛡 *Poder de Defensa del Clan*\n\n" + "\n\n".join(lines) + f"\n\n🔥 TOTAL: {total:,}"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= APP =================
tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_act_entry), CommandHandler("act", start_act_entry)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
        ASK_ATK: [MessageHandler(filters.TEXT, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT, get_def)],
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

# --- HANDLERS GLOBALES ---
tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", atk_cmd))
tg_app.add_handler(CommandHandler("def", def_cmd))
tg_app.add_handler(CommandHandler("cancelall", cancelall))

# --- FASTAPI ---
app = FastAPI()

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.update_queue.put(update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.start()
    print("✅ Bot listo y estable")
