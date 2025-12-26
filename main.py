import os
from fastapi import FastAPI, Request
from supabase import create_client
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ─────────────────────────────
# ENV
# ─────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

tg_app = Application.builder().token(BOT_TOKEN).build()
app = FastAPI()

# ─────────────────────────────
# HELPERS
# ─────────────────────────────
def get_setting(key):
    r = supabase.table("settings").select("value").eq("key", key).execute()
    return r.data[0]["value"] if r.data else None

def set_setting(key, value):
    supabase.table("settings").upsert({"key": key, "value": value}).execute()

def is_group(chat_id):
    return str(chat_id) == get_setting("group_id")

def is_admin(uid):
    admins = get_setting("admins")
    return admins and str(uid) in admins.split(",")

# ─────────────────────────────
# AUTO GUARDAR MIEMBROS POR MENSAJES
# ─────────────────────────────
async def capture_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not is_group(update.message.chat.id):
        return

    u = update.message.from_user

    # Obtener el conteo actual de mensajes para el usuario
    existing = supabase.table("members").select("messages").eq("uid", str(u.id)).execute()
    current_messages = existing.data[0]["messages"] if existing.data else 0

    supabase.table("members").upsert({
        "uid": str(u.id),
        "tg": u.username,
        "registered": False,
        "messages": current_messages + 1  # Incrementar contador de mensajes
    }).execute()

# ─────────────────────────────
# /start
# ─────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update.message.chat.id):
        return

    u = update.message.from_user

    # Al registrarse, marcar como registrado y resetear mensajes si es necesario (opcional)
    supabase.table("members").upsert({
        "uid": str(u.id),
        "tg": u.username,
        "registered": True,
        "messages": 0  # Opcional: resetear al registrarse
    }).execute()

    await update.message.reply_text("✅ Registrado en el clan.")

# ─────────────────────────────
# /act atk def
# ─────────────────────────────
async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update.message.chat.id):
        return

    try:
        atk = int(context.args[0])
        deff = int(context.args[1])
    except:
        await update.message.reply_text("Uso: /act ATK DEF")
        return

    u = update.message.from_user

    supabase.table("users").upsert({
        "uid": str(u.id),
        "tg": u.username,
        "atk": atk,
        "def": deff
    }).execute()

    # ✅ MARCAR VOTO SI HAY GUERRA
    if get_setting("war_active") == "true":
        supabase.table("war_votes").upsert({
            "uid": str(u.id),
            "voted": True
        }).execute()

    await update.message.reply_text("📊 Stats actualizados.")

# ─────────────────────────────
# /atk /def
# ─────────────────────────────
async def atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = supabase.table("users").select("tg,atk").order("atk", desc=True).execute()
    msg = "⚔️ ATAQUE CLAN\n\n"
    for x in r.data:
        msg += f"@{x['tg']} → {x['atk']}\n"
    await update.message.reply_text(msg)

async def deff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = supabase.table("users").select("tg,def").order("def", desc=True).execute()
    msg = "🛡 DEFENSA CLAN\n\n"
    for x in r.data:
        msg += f"@{x['tg']} → {x['def']}\n"
    await update.message.reply_text(msg)

# ─────────────────────────────
# WAR SYSTEM
# ─────────────────────────────
async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        return

    set_setting("war_active", "true")
    supabase.table("war_votes").delete().neq("uid", "").execute()  # Corregido: usar "" en lugar de "0"
    await update.message.reply_text("🔥 GUERRA INICIADA")

async def warlessa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if get_setting("war_active") != "true":
        return

    users = supabase.table("users").select("uid,tg").execute().data  # Simplificado: no necesitamos atk aquí
    voted = {x["uid"] for x in supabase.table("war_votes").select("uid").execute().data}

    msg = "❌ ATK PENDIENTE:\n\n"  # Corregido: agregar \n\n para consistencia
    for u in users:
        if u["uid"] not in voted:
            msg += f"@{u['tg']}\n"

    await update.message.reply_text(msg or "✅ Todos enviaron ATK")

async def warlessd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Para DEF, asumimos que es lo mismo que ATK, ya que /act envía ambos.
    # Si quieres distinguir, podrías agregar lógica separada para votos de DEF.
    await warlessa(update, context)

async def endwar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        return

    set_setting("war_active", "false")
    supabase.table("war_votes").delete().neq("uid", "").execute()  # Corregido: usar ""
    await update.message.reply_text("🏁 Guerra finalizada")

# ─────────────────────────────
# /pspy
# ─────────────────────────────
async def pspy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        return

    r = supabase.table("members").select("tg").eq("registered", False).execute()
    msg = "🕵️ NO REGISTRADOS:\n\n"  # Corregido: agregar \n\n
    for x in r.data:
        msg += f"@{x['tg']}\n"

    await update.message.reply_text(msg or "✅ Todos registrados")

# ─────────────────────────────
# HANDLERS
# ─────────────────────────────
tg_app.add_handler(MessageHandler(filters.ALL, capture_member))
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("act", act))
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", deff))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("pspy", pspy))

# ─────────────────────────────
# WEBHOOK
# ─────────────────────────────
@app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

# ─────────────────────────────
# STARTUP
# ─────────────────────────────
@app.on_event("startup")
async def startup():
    await tg_app.initialize()

    gid = get_setting("group_id")
    if gid:
        await tg_app.bot.send_message(
            gid,
            "🤖 *Bot del Clan ONLINE*\n\n📖 Comandos listos para la guerra ⚔️",  # Corregido: agregar \n\n
            parse_mode="Markdown"
        )

