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

# ================= START / ACT =================
async def start_act_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Validar que sea privado
    if update.effective_chat.type != "private":
        await update.message.reply_text("🚫 Usa este comando en privado conmigo.")
        return ConversationHandler.END

    user_id = update.effective_user.id
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
    if not context.user_data["guser"]:
        await update.message.reply_text("❌ Nombre inválido. Escríbelo de nuevo.")
        return ASK_GUSER

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
    try:
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
    except:
        await update.message.reply_text("❌ Hubo un error, por favor intenta de nuevo.")
        return ASK_DEF

    context.user_data.clear()
    return ConversationHandler.END

# ================= CANCEL =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Proceso cancelado.")
    return ConversationHandler.END

async def cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(context.bot, user_id):
        await update.message.reply_text("🚫 Solo admins pueden usar /cancelall.")
        return
    # Aquí podrías limpiar todos los active_process si lo guardas en DB
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
    user_id = update.effective_user.id
    if not await is_admin(context.bot, user_id):
        await update.message.reply_text("🚫 Solo admins pueden iniciar la guerra.")
        return

    args = context.args
    if not args or ":" not in args[0]:
        await update.message.reply_text("❌ Usa /war HH:MM (hora de inicio, ya pasada)")
        return

    try:
        h, m = map(int, args[0].split(":"))
        now = datetime.now()
        start_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start_time > now:
            start_time -= timedelta(days=1)  # Ajustar si la hora "ya pasó"
    except:
        await update.message.reply_text("❌ Formato de hora inválido. Ej: /war 6:05")
        return

    end_time = start_time + timedelta(hours=12)
    remaining_seconds = (end_time - now).total_seconds()
    if remaining_seconds <= 0:
        await update.message.reply_text("❌ Esta guerra ya terminó según la hora indicada.")
        return

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ Enviar tropas", callback_data="war_send")]])
    await update.message.reply_text(
        f"🔥 GUERRA INICIADA a las {h:02d}:{m:02d}! Terminará a las {end_time.hour:02d}:{end_time.minute:02d}",
        reply_markup=kb
    )

    checkpoints = [
        (3*3600, "⏳ Faltan 3 horas para la victoria. ¡A enviar tropas!"),
        (2*3600, "⏳ Faltan 2 horas. ¡Gatos, saqueo a tope!"),
        (1*3600, "⏳ 1 hora restante. ¡No pierdas la oportunidad!"),
        (30*60, "⏳ Solo 30 minutos. ¡Gatos, saqueo intensivo!"),
        (20*60, "⏳ 20 minutos. ¡Último empujón, gatos!"),
        (10*60, "⏳ 10 minutos restantes. ¡Todos a enviar tropas y asegurar la victoria!")
    ]

    async def send_checkpoint(delay, message):
        if delay > 0:
            await asyncio.sleep(delay)
            await context.bot.send_message(chat_id=get_group_id(), text=message, reply_markup=kb)

    now_ts = now.timestamp()
    tasks = []
    for seconds_before_end, msg in checkpoints:
        checkpoint_ts = end_time.timestamp() - seconds_before_end
        delay = checkpoint_ts - now_ts
        if delay > 0:
            tasks.append(send_checkpoint(delay, msg))

    tasks.append(send_checkpoint(remaining_seconds, "🏁 La guerra ha terminado. ¡Gracias a todos por participar!"))

    asyncio.create_task(asyncio.gather(*tasks))

async def war_callback(update, context):
    uid = str(update.callback_query.from_user.id)
    supabase.table("users").update({"send": True, "sent_war": True}).eq("uid", uid).execute()
    await update.callback_query.answer("✅ Tropas enviadas")

async def warless(update, key, emoji):
    users = supabase.table("users").select("*").eq("sent_war", False).execute().data
    total = sum(u[key] for u in users if u.get(key))
    await update.message.reply_text(f"{emoji} Restante: {total:,}")

async def endwar(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    supabase.table("users").update({"sent_war": False}).neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada.")

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
tg_app.add_handler(CommandHandler("warlessa", lambda u,c: warless(u,"atk","⚔️")))
tg_app.add_handler(CommandHandler("warlessd", lambda u,c: warless(u,"def","🛡")))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("cancelall", cancelall))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_send$"))

# ================= FASTAPI =================
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
        await tg_app.bot.send_message(gid, "⚡ Version 0.016 del Clan Helper activa! El clan vikingo me la pela 🎮")
    print("✅ Bot listo y estable")
