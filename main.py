import os
import asyncio
from datetime import datetime, timedelta
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
active_wars = {}  # para almacenar la guerra activa

# ================= UTIL =================
def parse_power(text: str) -> int | None:
    try:
        t = text.lower().replace(" ", "")
        if t.endswith("k"):
            return int(float(t[:-1]) * 1_000)
        elif t.endswith("m"):
            return int(float(t[:-1]) * 1_000_000)
        else:
            return int(t)
    except:
        return None

def get_group_id():
    res = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(res.data[0]["value"]) if res.data else None

async def belongs_to_clan(bot, user_id):
    gid = get_group_id()
    if not gid: return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

async def is_admin(bot, user_id):
    gid = get_group_id()
    if not gid: return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("administrator", "creator")
    except:
        return False

# ================= START / ACT =================
async def start_act_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != "private":
        await update.message.reply_text("📩 Por favor, usa este comando en privado.")
        return ConversationHandler.END

    if context.user_data.get("active_process"):
        await update.message.reply_text("⚠️ Tienes un proceso activo. Usa /cancel para reiniciarlo.")
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
        context.user_data["is_act"] = True
        await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:", parse_mode="Markdown")
        return ASK_ATK
    else:
        context.user_data["is_act"] = False
        await update.message.reply_text("🎮 Escribe tu nombre en el juego:", parse_mode="Markdown")
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
    query = update.callback_query
    await query.answer()
    race_map = {"race_gato": "Gato", "race_perro": "Perro", "race_rana": "Rana"}
    race = race_map.get(query.data)
    if not race:
        await query.edit_message_text("❌ Raza inválida.")
        context.user_data.clear()
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
    if context.user_data.get("is_act"):
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
    await update.message.reply_text("❌ Proceso cancelado.")
    return ConversationHandler.END

async def cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins pueden usar /cancelall.")
        return
    # Limpiar todos los procesos activos (solo en memoria por ahora)
    await update.message.reply_text("⚠️ Todos los procesos activos de los usuarios han sido cancelados.")

# ================= MOSTRAR PODER =================
async def show(update, key):
    users = supabase.table("users").select("*").execute().data
    users = [u for u in users if u.get(key)]
    users.sort(key=lambda u: u[key], reverse=True)
    icon = "⚔️" if key == "atk" else "🛡"
    total = sum(u[key] for u in users)
    lines = [f"🎮 {u['guser']}\n└ {icon} {u[key]:,}" for u in users]
    msg = f"{icon} PODER DEL CLAN\n\n" + "\n\n".join(lines) + f"\n\n🔥 TOTAL: {total:,}"
    await update.message.reply_text(msg)

async def atk(update, context): await show(update, "atk")
async def defense(update, context): await show(update, "def")

# ================= WAR =================
async def war(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return

    if active_wars.get("current"):
        await update.message.reply_text("⚠️ Ya hay una guerra activa.")
        return

    args = context.args
    if not args:
        start_time = datetime.now()
    else:
        try:
            t = args[0]
            h, m = map(int, t.split(":"))
            start_time = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        except:
            await update.message.reply_text("Formato inválido. Usa /war HH:MM")
            return

    gid = get_group_id()
    end_time = start_time + timedelta(hours=12)
    active_wars["current"] = True

    # Mensaje inicial
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ Enviar tropas", callback_data="war_send")]])
    await update.message.reply_text(f"🔥 GUERRA INICIADA a las {start_time.strftime('%H:%M')} - durará 12h", reply_markup=kb)

    # Lanzar temporizador async
    asyncio.create_task(war_timer(context.bot, gid, end_time))

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("users").update({"send": True, "sent_war": True}).eq("uid", uid).execute()
    await update.callback_query.answer("✅ Tropas enviadas")

async def war_timer(bot, gid, end_time):
    checkpoints = [
        (3, "⌛ Quedan 3 horas para enviar tropas. ¡No aflojen!"),
        (2, "⌛ Quedan 2 horas para enviar tropas. ¡Mantengan el ritmo!"),
        (1, "⌛ Solo 1 hora para enviar tropas. ¡Aseguren la victoria!"),
        (0.5, "⌛ 30 minutos restantes! 🐱 Gatos, aprovechen el saqueo!"),
        (0.3333, "⌛ 20 minutos restantes! 🐱 Gatos, aceleren el saqueo!"),
        (0.1666, "⌛ 10 minutos restantes! ¡Todos a enviar tropas, inspiren al resto!")
    ]
    for hours_left, message in checkpoints:
        checkpoint_time = end_time - timedelta(hours=hours_left)
        delay = (checkpoint_time - datetime.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ Enviar tropas", callback_data="war_send")]])
            await bot.send_message(gid, message + "\n" + "⚔️ Presiona para enviar tropas", reply_markup=kb)
    # Finalizar guerra
    final_delay = (end_time - datetime.now()).total_seconds()
    if final_delay > 0:
        await asyncio.sleep(final_delay)
    await bot.send_message(gid, "🏁 GUERRA FINALIZADA")
    active_wars.pop("current", None)

# ================= APP =================
tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_act_entry), CommandHandler("act", start_act_entry)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    per_chat=False
)

tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_send$"))
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
    gid = get_group_id()
    if gid:
        await tg_app.bot.send_message(gid, "🔥 Clan Helper v0.012 activo!")
    print("✅ Bot listo y estable")
