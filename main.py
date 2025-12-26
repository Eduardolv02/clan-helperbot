import os
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
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
@@ -17,6 +27,7 @@
ASK_GUSER, ASK_RACE, ASK_ATK, ASK_DEF = range(4)

# ================= UTIL =================

def parse_power(text: str) -> int:
t = text.lower().replace(" ", "")
if t.endswith("k"):
@@ -26,200 +37,249 @@ def parse_power(text: str) -> int:
return int(t)

def get_group_id():
    r = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(r.data[0]["value"]) if r.data else None
    res = supabase.table("settings").select("value").eq("key", "group_id").execute()
    return int(res.data[0]["value"]) if res.data else None

async def belongs(bot, uid):
async def belongs_to_clan(bot, user_id):
gid = get_group_id()
    if not gid:
        return False
try:
        m = await bot.get_chat_member(gid, uid)
        m = await bot.get_chat_member(gid, user_id)
return m.status in ("member", "administrator", "creator")
except:
return False

async def is_admin(bot, uid):
async def is_admin(bot, user_id):
gid = get_group_id()
    m = await bot.get_chat_member(gid, uid)
    if not gid:
        return False
    m = await bot.get_chat_member(gid, user_id)
return m.status in ("administrator", "creator")

# ================= START / ACT =================
# ================= START / REGISTRO =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("📩 Escríbeme al privado para registrarte.")
    if update.effective_chat.type != "private":
        await update.message.reply_text("📩 Escríbeme por privado para registrarte.")
return ConversationHandler.END
    if not await belongs(context.bot, update.effective_user.id):

    if not await belongs_to_clan(context.bot, update.effective_user.id):
await update.message.reply_text("🚫 No perteneces al clan.")
return ConversationHandler.END

uid = str(update.effective_user.id)
    user = supabase.table("users").select("uid").eq("uid", uid).execute()
    if user.data:
    context.user_data.clear()
    context.user_data["uid"] = uid

    exists = supabase.table("users").select("uid").eq("uid", uid).execute()
    if exists.data:
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
    context.user_data["guser"] = update.message.text.strip()

kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Gato", callback_data="gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="rana")]
        [InlineKeyboardButton("🐱 Gato", callback_data="race_gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="race_perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="race_rana")]
])
    await update.message.reply_text("🏹 Elige tu raza:", reply_markup=kb)

    await update.message.reply_text("🏹 Selecciona tu RAZA:", reply_markup=kb)
return ASK_RACE

async def get_race(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["race"] = q.data.capitalize()
    await q.edit_message_text("⚔️ Ingresa tu ATAQUE:")
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

async def get_atk(update, context):
    context.user_data["atk"] = parse_power(update.message.text)
    try:
        context.user_data["atk"] = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido. Ej: 120k o 1.5m")
        return ASK_ATK

await update.message.reply_text("🛡 Ingresa tu DEFENSA:")
return ASK_DEF

async def get_def(update, context):
    try:
        defense = parse_power(update.message.text)
    except:
        await update.message.reply_text("❌ Valor inválido.")
        return ASK_DEF

uid = context.user_data["uid"]
    supabase.table("users").upsert({

    # ===== VIENE DE /act =====
    if context.user_data.get("is_act"):
        supabase.table("users").update({
            "atk": context.user_data["atk"],
            "def": defense,
            "sent_war": False
        }).eq("uid", uid).execute()

        await update.message.reply_text("✅ Poder actualizado.")
        return ConversationHandler.END

    # ===== VIENE DE /start =====
    supabase.table("users").insert({
"uid": uid,
"tg": update.effective_user.username,
"guser": context.user_data["guser"],
"race": context.user_data["race"],
"atk": context.user_data["atk"],
        "def": parse_power(update.message.text),
        "send": False
        "def": defense,
        "sent_war": False
}).execute()
    supabase.table("members").update({"registered": True}).eq("uid", uid).execute()

await update.message.reply_text("✅ Registro completado.")
return ConversationHandler.END

# ================= ACT =================

async def act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "📩 Para actualizar tu poder, escríbeme por privado."
        )
        return ConversationHandler.END

    if not await belongs_to_clan(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 No perteneces al clan.")
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

# ================= WAR =================

async def war(update, context):
if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
return
    supabase.table("users").update({"send": False}).neq("uid", "").execute()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ Enviar tropas", callback_data="send")]])
    await update.message.reply_text("🔥 GUERRA INICIADA", reply_markup=kb)

async def war_cb(update, context):
    supabase.table("users").update({"sent_war": False}).neq("uid", "").execute()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Enviar tropas", callback_data="war_send")]
    ])

    await update.message.reply_text(
        "🔥 GUERRA INICIADA\n\nPresiona para enviar tropas:",
        reply_markup=kb
    )

async def war_callback(update, context):
uid = str(update.callback_query.from_user.id)
    supabase.table("users").update({"send": True}).eq("uid", uid).execute()

    supabase.table("users").update({
        "sent_war": True
    }).eq("uid", uid).execute()

await update.callback_query.answer("✅ Tropas enviadas")

async def warless(update, key, emoji):
    users = supabase.table("users").select("*").eq("send", False).execute().data
    total = sum(u[key] for u in users)
    users = supabase.table("users").select("*").eq("sent_war", False).execute().data
    total = sum(u[key] for u in users if u.get(key))
await update.message.reply_text(f"{emoji} Restante: {total:,}")

# ================= DELETE CON CONFIRMACION =================
async def delete(update, context):
async def warlessa(update, context):
    await warless(update, "atk", "⚔️")

async def warlessd(update, context):
    await warless(update, "def", "🛡")

async def endwar(update, context):
if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
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
        [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_{uid}"),
         InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
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
    supabase.table("users").update({"sent_war": False}).neq("uid", "").execute()
    await update.message.reply_text("🏁 Guerra finalizada.")

async def delete_cancel(update, context):
    await update.callback_query.edit_message_text("🚫 Acción cancelada.")
# ================= LISTAS =================

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
async def show(update, key):
    users = supabase.table("users").select("*").execute().data
    users = [u for u in users if u.get(key)]

    users.sort(key=lambda u: u[key], reverse=True)

    icon = "⚔️" if key == "atk" else "🛡"
    total = sum(u[key] for u in users)

    lines = [
        f"🎮 {u['guser']}\n└ {icon} {u[key]:,}"
        for u in users
    ]

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
    entry_points=[
        CommandHandler("start", start),
        CommandHandler("act", act)
    ],
states={
ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^(gato|perro|rana)$")],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_atk)],
ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_def)],
},
fallbacks=[]
)

# --- HANDLER ORDER CORRECTO ---
tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", lambda u, c: warless(u, "atk", "⚔️")))
tg_app.add_handler(CommandHandler("warlessd", lambda u, c: warless(u, "def", "🛡")))
tg_app.add_handler(CommandHandler("delete", delete))

tg_app.add_handler(CallbackQueryHandler(war_cb, pattern="send"))
tg_app.add_handler(CallbackQueryHandler(delete_ask, pattern="askdel_"))
tg_app.add_handler(CallbackQueryHandler(delete_confirm, pattern="confirm_"))
tg_app.add_handler(CallbackQueryHandler(delete_cancel, pattern="cancel"))

tg_app.add_handler(
    MessageHandler(filters.ChatType.GROUPS & filters.Entity("mention"), mention_bot)
)
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_send$"))

# --- FASTAPI ---
app = FastAPI()

@app.post("/webhook")
@@ -231,4 +291,5 @@ async def webhook(req: Request):
@app.on_event("startup")
async def startup():
await tg_app.initialize()
    print("✅ Bot listo")
    await tg_app.start()
    print("✅ Bot listo y estable")
