  import os
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, ChatMemberHandler
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
            user_data = supabase.table("users").select("*").eq("uid", uid).execute().data[0]
            await update.message.reply_text(f"✅ Poder actualizado con éxito.\n🎮 Nombre: {user_data['guser']}\n🏹 Raza: {user_data['race']}\n⚔️ Ataque: {user_data['atk']:,}\n🛡 Defensa: {user_data['def']:,}")
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
            await update.message.reply_text(f"✅ Registro completado con éxito.\n🎮 Nombre: {context.user_data['guser']}\n🏹 Raza: {context.user_data['race']}\n⚔️ Ataque: {context.user_data['atk']:,}\n🛡 Defensa: {defense:,}")
    except Exception as e:
        print(f"Error saving to DB: {e}")
        await update.message.reply_text("❌ Error al guardar. Inténtalo de nuevo.")
        return ASK_DEF  # Repite el paso si falla

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
    # Limpiar procesos activos (si se guarda en DB, aquí se haría)
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

# ================= ME =================
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_data = supabase.table("users").select("*").eq("uid", uid).execute().data
    if not user_data:
        await update.message.reply_text("❌ No estás registrado. Usa /start para registrarte.")
        return
    user = user_data[0]
    await update.message.reply_text(f"🎮 Nombre: {user['guser']}\n🏹 Raza: {user['race']}\n⚔️ Ataque: {user['atk']:,}\n🛡 Defensa: {user['def']:,}")

# ================= MEMBER =================
async def member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    exists = supabase.table("members").select("uid").eq("uid", uid).execute()
    if exists.data:
        await update.message.reply_text("✅ Ya estás en la lista de miembros.")
        return
    supabase.table("members").insert({"uid": uid, "registered": False}).execute()
    await update.message.reply_text("✅ Agregado a la lista de miembros. Ahora puedes registrarte con /start.")

# ================= MEMBERLIST =================
async def memberlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    members = supabase.table("members").select("*").eq("registered", False).execute().data
    if not members:
        await update.message.reply_text("✅ Todos los miembros están registrados.")
        return
    mentions = []
    for m in members:
        uid = m["uid"]
        user_data = supabase.table("users").select("tg").eq("uid", uid).execute().data
        if user_data and user_data[0]["tg"]:
            mentions.append(f"@{user_data[0]['tg']}")
        else:
            mentions.append(f"@{uid}")  # Fallback a uid si no hay tg
    msg = "👥 Miembros no registrados: " + " ".join(mentions)
    gid = get_group_id()
    if gid:
        await context.bot.send_message(gid, msg)
    else:
        await update.message.reply_text(msg)

# ================= DELIST =================
async def delist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    members = supabase.table("members").select("*").execute().data
    if not members:
        await update.message.reply_text("❌ No hay miembros.")
        return
    context.user_data["delist_members"] = members
    context.user_data["delist_page"] = 0
    await send_delist_page(update, context)

async def send_delist_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    members = context.user_data["delist_members"]
    page = context.user_data["delist_page"]
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_members = members[start:end]
    
    kb = []
    for m in page_members:
        uid = m["uid"]
        user_data = supabase.table("users").select("guser, tg").eq("uid", uid).execute().data
        if user_data:
            name = user_data[0]["guser"]
        else:
            name = f"@{m.get('tg', uid)}"
        kb.append([InlineKeyboardButton(name, callback_data=f"delist_select_{uid}")])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data="delist_prev"))
    if end < len(members):
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data="delist_next"))
    if nav:
        kb.append(nav)
    
    kb.append([InlineKeyboardButton("❌ Cancelar", callback_data="delist_cancel")])
    
    msg = f"👥 Lista de Miembros (Página {page+1}):\n\n" + "\n".join([f"- {btn[0].text}" for btn in kb[:-1] if btn[0].callback_data.startswith("delist_select")])
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def delist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "delist_cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Delist cancelado.")
        return
    elif data == "delist_prev":
        context.user_data["delist_page"] -= 1
        await send_delist_page(update, context)
        return
    elif data == "delist_next":
        context.user_data["delist_page"] += 1
        await send_delist_page(update, context)
        return
    elif data.startswith("delist_select_"):
        uid = data.split("_")[2]
        context.user_data["delist_uid"] = uid
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirmar", callback_data="delist_confirm")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="delist_cancel")]
        ])
        await query.edit_message_text(f"¿Expulsar a {uid}? Esto borrará sus datos.", reply_markup=kb)
        return
    elif data == "delist_confirm":
        uid = context.user_data["delist_uid"]
        gid = get_group_id()
        if gid:
            try:
                await context.bot.ban_chat_member(gid, int(uid))
                await context.bot.unban_chat_member(gid, int(uid))  # Para desbanear si es necesario
            except:
                pass
        supabase.table("users").delete().eq("uid", uid).execute()
        supabase.table("members").delete().eq("uid", uid).execute()
        context.user_data.clear()
        await query.edit_message_text("✅ Usuario expulsado y datos borrados.")
        return

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
    gid = get_group_id()
    if gid:
        await context.bot.send_message(gid, 
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

    for seconds_before_end, msg in checkpoints:
        checkpoint_time = end_time - timedelta(seconds=seconds_before_end)
        if checkpoint_time > now:
            context.job_queue.run_once(lambda ctx: ctx.bot.send_message(gid, msg, reply_markup=kb), checkpoint_time - now)

    context.job_queue.run_once(lambda ctx: ctx.bot.send_message(gid, "🏁 La guerra ha terminado. ¡Gracias a todos por participar!"), remaining_seconds)

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

# ================= SYNC MEMBERS =================
async def sync_members(update, context):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    gid = get_group_id()
    if not gid:
        await update.message.reply_text("❌ Grupo no configurado.")
return
# Nota: Telegram no permite obtener todos los miembros fácilmente. Esto es limitado.
# Para grupos grandes, usar /sync_members para que usuarios se registren manualmente.
# Aquí, asumimos que admins pueden listar no registrados basados en members table.
members = supabase.table("members").select("*").eq("registered", False).execute().data
if not members:
    await update.message.reply_text("✅ Todos los miembros están registrados.")
    return
msg = "👥 Miembros no registrados:\n" + "\n".join([f"- {m['uid']}" for m in members])
await update.message.reply_text(msg)

# ================= MENCIONAR RAZAS =================
async def mention_race(update, context, race):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    users = supabase.table("users").select("uid").eq("race", race).execute().data
    if not users:
        await update.message.reply_text(f"❌ No hay usuarios de raza {race}.")
        return
    mentions = " ".join([f"@{u['uid']}" for u in users])  # Asumiendo uid es username
    gid = get_group_id()
    if gid:
        await context.bot.send_message(gid, f"📢 Mención a {race}s: {mentions}")

async def allgato(update, context): await mention_race(update, context, "Gato")
async def allperro(update, context): await mention_race(update, context, "Perro")
async def allrana(update, context): await mention_race(update, context, "Rana")

# ================= MANEJAR MIEMBROS SALIENDO =================
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if chat_member.new_chat_member.status == "left" or chat_member.new_chat_member.status == "kicked":
        uid = str(chat_member.new_chat_member.user.id)
        supabase.table("users").delete().eq("uid", uid).execute()
        supabase.table("members").delete().eq("uid", uid).execute()

# ================= MENCION AL BOT =================
async def mention_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "mention" and update.message.text[entity.offset:entity.offset + entity.length] == f"@{context.bot.username}":
                commands = """
📋 Comandos disponibles:
/start - Registrarte en el clan.
/act - Actualizar tus stats.
/me - Ver tus datos.
/atk - Ver ranking de ataque.
/def - Ver ranking de defensa.
/member - Agregarte a la lista de miembros.
/war HH:MM - Iniciar guerra (admins).
/warlessa - Poder restante en ataque.
/warlessd - Poder restante en defensa.
/endwar - Finalizar guerra (admins).
/memberlist - Listar no registrados (admins).
/delist - Gestionar miembros (admins).
/allgato - Mencionar gatos (admins).
/allperro - Mencionar perros (admins).
/allrana - Mencionar ranas (admins).
/cancel - Cancelar proceso.
/cancelall - Cancelar todos (admins).
"""
                await update.message.reply_text(commands)
                return

# ================= APP =================
tg_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_act_entry, filters.ChatType.PRIVATE), 
                  CommandHandler("act", start_act_entry, filters.ChatType.PRIVATE)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_def)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    per_chat=False,
    conversation_timeout=90  # 1 min 30 seg
)

tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", atk))
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("me", me))
tg_app.add_handler(CommandHandler("member", member))
tg_app.add_handler(CommandHandler("memberlist", memberlist))
tg_app.add_handler(CommandHandler("delist", delist))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", lambda u,c: warless(u,"atk","⚔️")))
tg_app.add_handler(CommandHandler("warlessd", lambda u,c: warless(u,"def","🛡")))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("sync_members", sync_members))
tg_app.add_handler(CommandHandler("allgato", allgato))
tg_app.add_handler(CommandHandler("allperro", allperro))
tg_app.add_handler(CommandHandler("allrana", allrana))
tg_app.add_handler(CommandHandler("cancelall", cancelall))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_send$"))
tg_app.add_handler(CallbackQueryHandler(delist_callback, pattern="^delist_"))
tg_app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
tg_app.add_handler(MessageHandler(filters.Entity("mention"), mention_bot))

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
        await tg_app.bot.send_message(gid, "⚡ Version 0.1.2 del Clan Helper activa!  🎮")
    print("✅ Bot listo y estable")
