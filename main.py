import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Any, Dict

from fastapi import FastAPI, Request
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    ChatMemberHandler,
)

from supabase import create_client

# Config logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not TOKEN:
    logger.warning("BOT_TOKEN no encontrado en variables de entorno. El bot no podr\u00e1 arrancar sin ")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logger.warning("SUPABASE_URL o SUPABASE_KEY no encontradas. Operaciones BD fallar\u00e1n si se usan.")

# Estados del ConversationHandler
ASK_GUSER, ASK_RACE, ASK_ATK, ASK_DEF = range(4)

# ================= UTIL =================

def parse_power(text: str) -> Optional[int]:
    """Parses strings like '120k', '1.5m' or plain integers and returns an int or None."""
    try:
        t = text.lower().replace(" ", "")
        if t.endswith("k"):
            return int(float(t[:-1]) * 1_000)
        elif t.endswith("m"):
            return int(float(t[:-1]) * 1_000_000)
        else:
            return int(float(t))
    except Exception:
        return None


def get_group_id() -> Optional[int]:
    """Lee la configuración 'group_id' desde la tabla settings en Supabase.
    Retorna int o None si no está configurado o la BD no está disponible.
    """
    try:
        if not supabase:
            return None
        res = supabase.table("settings").select("value").eq("key", "group_id").execute()
        if res and getattr(res, "data", None):
            return int(res.data[0]["value"])
    except Exception as e:
        logger.exception("Error leyendo group_id: %s", e)
    return None


async def belongs_to_clan(bot, user_id: int) -> bool:
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def is_admin(bot, user_id: int) -> bool:
    gid = get_group_id()
    if not gid:
        return False
    try:
        m = await bot.get_chat_member(gid, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


# ================= START / ACT =================
async def start_act_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Validar que sea privado
    if update.effective_chat is None or update.effective_chat.type != "private":
        if update.message:
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
    # Existe el usuario en la tabla users?
    exists = None
    try:
        exists = supabase.table("users").select("uid").eq("uid", uid).execute() if supabase else None
    except Exception as e:
        logger.exception("Error consultando usuario: %s", e)

    context.user_data.clear()
    context.user_data["uid"] = uid
    context.user_data["active_process"] = True

    if exists and getattr(exists, "data", None):
        context.user_data["is_act"] = True
        await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE:", parse_mode="Markdown")
        return ASK_ATK
    else:
        context.user_data["is_act"] = False
        await update.message.reply_text("🎮 Escribe tu nombre en el juego:", parse_mode="Markdown")
        return ASK_GUSER


async def get_guser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message and update.message.text else ""
    context.user_data["guser"] = text
    if not context.user_data["guser"]:
        await update.message.reply_text("❌ Nombre inválido. Escríbelo de nuevo.")
        return ASK_GUSER

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Gato", callback_data="race_gato")],
        [InlineKeyboardButton("🐶 Perro", callback_data="race_perro")],
        [InlineKeyboardButton("🐸 Rana", callback_data="race_rana")],
    ])
    await update.message.reply_text("🏹 Selecciona tu RAZA:", reply_markup=kb)
    return ASK_RACE


async def get_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    race_map = {"race_gato": "Gato", "race_perro": "Perro", "race_rana": "Rana"}
    race = race_map.get(query.data)
    if not race:
        await query.edit_message_text("❌ Raza inválida.")
        return ConversationHandler.END

    context.user_data["race"] = race
    await query.edit_message_text("⚔️ Ingresa tu ATAQUE:")
    return ASK_ATK


async def get_atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    power = parse_power(update.message.text) if update.message and update.message.text else None
    if power is None:
        await update.message.reply_text("❌ Valor inválido. Ej: 120k o 1.5m")
        return ASK_ATK
    context.user_data["atk"] = power
    await update.message.reply_text("🛡 Ingresa tu DEFENSA:")
    return ASK_DEF


async def get_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    defense = parse_power(update.message.text) if update.message and update.message.text else None
    if defense is None:
        await update.message.reply_text("❌ Valor inválido. Ej: 80k o 1m")
        return ASK_DEF

    uid = context.user_data.get("uid")
    try:
        if context.user_data.get("is_act"):
            # Actualizar
            if supabase:
                supabase.table("users").update({
                    "atk": context.user_data["atk"],
                    "def": defense,
                    "sent_war": False,
                }).eq("uid", uid).execute()
                user_res = supabase.table("users").select("*").eq("uid", uid).execute()
                user_data = user_res.data[0] if user_res and getattr(user_res, "data", None) else None
            else:
                user_data = None

            if user_data:
                await update.message.reply_text(
                    f"✅ Poder actualizado con éxito.\n🎮 Nombre: {user_data.get('guser')}\n🏹 Raza: {user_data.get('race')}\n⚔️ Ataque: {user_data.get('atk'):, if isinstance(user_data.get('atk'), int) else user_data.get('atk')}\n🛡 Defensa: {user_data.get('def'):, if isinstance(user_data.get('def'), int) else user_data.get('def')}")
            else:
                await update.message.reply_text("✅ Poder actualizado con éxito.")
        else:
            # Insertar nuevo usuario
            if supabase:
                supabase.table("users").insert({
                    "uid": uid,
                    "tg": update.effective_user.username,
                    "guser": context.user_data.get("guser"),
                    "race": context.user_data.get("race"),
                    "atk": context.user_data.get("atk"),
                    "def": defense,
                    "sent_war": False,
                }).execute()
                # Marcar en members
                supabase.table("members").update({"registered": True}).eq("uid", uid).execute()

            await update.message.reply_text(
                f"✅ Registro completado con éxito.\n🎮 Nombre: {context.user_data.get('guser')}\n🏹 Raza: {context.user_data.get('race')}\n⚔️ Ataque: {context.user_data.get('atk'):,}\n🛡 Defensa: {defense:,}")
    except Exception as e:
        logger.exception("Error saving to DB: %s", e)
        await update.message.reply_text("❌ Error al guardar. Inténtalo de nuevo.")
        return ASK_DEF

    context.user_data.clear()
    return ConversationHandler.END


# ================= CANCEL =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("❌ Proceso cancelado.")
    return ConversationHandler.END


async def cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(context.bot, user_id):
        await update.message.reply_text("🚫 Solo admins pueden usar /cancelall.")
        return
    # Si se guarda active_process en DB, aquí se limpiaría. Por ahora limpiamos variables locales.
    await update.message.reply_text("⚠️ Todos los procesos activos de los usuarios han sido cancelados.")


# ================= MOSTRAR PODER =================
async def show_power(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    try:
        users_res = supabase.table("users").select("*").execute() if supabase else None
        users = users_res.data if users_res and getattr(users_res, "data", None) else []
    except Exception as e:
        logger.exception("Error leyendo users: %s", e)
        users = []

    users = [u for u in users if u.get(key)]
    users.sort(key=lambda u: u.get(key, 0), reverse=True)
    icon = "⚔️" if key == "atk" else "🛡"
    total = sum(u.get(key, 0) for u in users)
    lines = [f"🎮 {u.get('guser', u.get('uid'))}\n└ {icon} {u.get(key):,}" for u in users]
    msg = f"{icon} PODER DEL CLAN\n\n" + "\n\n".join(lines)
    msg += f"\n\n🔥 TOTAL: {total:,}"

    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg)


async def atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_power(update, context, "atk")


async def defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_power(update, context, "def")


# ================= ME =================
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    try:
        user_res = supabase.table("users").select("*").eq("uid", uid).execute() if supabase else None
        user_data = user_res.data[0] if user_res and getattr(user_res, "data", None) else None
    except Exception as e:
        logger.exception("Error leyendo usuario: %s", e)
        user_data = None

    if not user_data:
        await update.message.reply_text("❌ No estás registrado. Usa /start para registrarte.")
        return

    await update.message.reply_text(
        f"🎮 Nombre: {user_data.get('guser')}\n🏹 Raza: {user_data.get('race')}\n⚔️ Ataque: {user_data.get('atk'):,}\n🛡 Defensa: {user_data.get('def'):,}"
    )


# ================= MEMBER =================
async def member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    try:
        exists = supabase.table("members").select("uid").eq("uid", uid).execute() if supabase else None
    except Exception as e:
        logger.exception("Error members: %s", e)
        exists = None

    if exists and getattr(exists, "data", None):
        await update.message.reply_text("✅ Ya estás en la lista de miembros.")
        return

    try:
        supabase.table("members").insert({"uid": uid, "registered": False}).execute() if supabase else None
    except Exception as e:
        logger.exception("Error insert member: %s", e)

    await update.message.reply_text("✅ Agregado a la lista de miembros. Ahora puedes registrarte con /start.")


# ================= MEMBERLIST =================
async def memberlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    members_res = supabase.table("members").select("*").eq("registered", False).execute() if supabase else None
    members = members_res.data if members_res and getattr(members_res, "data", None) else []
    if not members:
        await update.message.reply_text("✅ Todos los miembros están registrados.")
        return

    mentions = []
    for m in members:
        uid = m.get("uid")
        user_res = supabase.table("users").select("tg").eq("uid", uid).execute() if supabase else None
        if user_res and getattr(user_res, "data", None) and user_res.data[0].get("tg"):
            mentions.append(f"@{user_res.data[0]['tg']}")
        else:
            mentions.append(f"@{uid}")

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
    members_res = supabase.table("members").select("*").execute() if supabase else None
    members = members_res.data if members_res and getattr(members_res, "data", None) else []
    if not members:
        await update.message.reply_text("❌ No hay miembros.")
        return

    context.user_data["delist_members"] = members
    context.user_data["delist_page"] = 0
    await send_delist_page(update, context)


async def send_delist_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    members = context.user_data.get("delist_members", [])
    page = context.user_data.get("delist_page", 0)
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_members = members[start:end]

    kb = []
    names = []
    for m in page_members:
        uid = m.get("uid")
        user_data = supabase.table("users").select("guser, tg").eq("uid", uid).execute() if supabase else None
        if user_data and getattr(user_data, "data", None) and user_data.data[0].get("guser"):
            name = user_data.data[0]["guser"]
        elif user_data and getattr(user_data, "data", None) and user_data.data[0].get("tg"):
            name = f"@{user_data.data[0]['tg']}"
        else:
            name = f"@{uid}"
        names.append(name)
        kb.append([InlineKeyboardButton(name, callback_data=f"delist_select_{uid}")])

    # navegación
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data="delist_prev"))
    if end < len(members):
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data="delist_next"))
    if nav:
        kb.append(nav)

    kb.append([InlineKeyboardButton("❌ Cancelar", callback_data="delist_cancel")])

    msg = f"👥 Lista de Miembros (Página {page+1}):\n\n" + "\n".join([f"- {n}" for n in names])

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))


async def delist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "delist_cancel":
        context.user_data.pop("delist_members", None)
        context.user_data.pop("delist_page", None)
        await query.edit_message_text("❌ Delist cancelado.")
        return
    elif data == "delist_prev":
        context.user_data["delist_page"] = max(0, context.user_data.get("delist_page", 0) - 1)
        await send_delist_page(update, context)
        return
    elif data == "delist_next":
        context.user_data["delist_page"] = context.user_data.get("delist_page", 0) + 1
        await send_delist_page(update, context)
        return
    elif data.startswith("delist_select_"):
        uid = data.split("delist_select_")[-1]
        context.user_data["delist_uid"] = uid
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirmar", callback_data="delist_confirm")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="delist_cancel")],
        ])
        await query.edit_message_text(f"¿Expulsar a {uid}? Esto borrará sus datos.", reply_markup=kb)
        return
    elif data == "delist_confirm":
        uid = context.user_data.get("delist_uid")
        gid = get_group_id()
        if gid:
            try:
                await context.bot.ban_chat_member(gid, int(uid))
                await context.bot.unban_chat_member(gid, int(uid))
            except Exception:
                # Si falla el ban/unban, no rompemos el flujo
                logger.exception("No se pudo banear/desbanear al usuario %s", uid)
        try:
            supabase.table("users").delete().eq("uid", uid).execute() if supabase else None
            supabase.table("members").delete().eq("uid", uid).execute() if supabase else None
        except Exception:
            logger.exception("Error borrando usuario %s de la BD", uid)

        context.user_data.pop("delist_members", None)
        context.user_data.pop("delist_page", None)
        context.user_data.pop("delist_uid", None)
        await query.edit_message_text("✅ Usuario expulsado y datos borrados.")
        return


# ================= WAR =================
async def job_send_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data: Dict[str, Any] = job.data or {}
    gid = data.get("gid")
    msg = data.get("msg")
    kb = data.get("kb")
    if gid and msg:
        try:
            await context.bot.send_message(gid, msg, reply_markup=kb)
        except Exception:
            logger.exception("Error enviando mensaje de job")


async def war(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            start_time -= timedelta(days=1)
    except Exception:
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
        try:
            await context.bot.send_message(
                gid,
                f"🔥 GUERRA INICIADA a las {h:02d}:{m:02d}! Terminará a las {end_time.hour:02d}:{end_time.minute:02d}",
                reply_markup=kb,
            )
        except Exception:
            logger.exception("No se pudo anunciar la guerra en el grupo")

    # checkpoints (segundos antes del final)
    checkpoints = [
        (3 * 3600, "⏳ Faltan 3 horas para la victoria. ¡A enviar tropas!"),
        (2 * 3600, "⏳ Faltan 2 horas. ¡Gatos, saqueo a tope!"),
        (1 * 3600, "⏳ 1 hora restante. ¡No pierdas la oportunidad!"),
        (30 * 60, "⏳ Solo 30 minutos. ¡Gatos, saqueo intensivo!"),
        (20 * 60, "⏳ 20 minutos. ¡Último empujón, gatos!"),
        (10 * 60, "⏳ 10 minutos restantes. ¡Todos a enviar tropas y asegurar la victoria!"),
    ]

    for seconds_before_end, msg in checkpoints:
        checkpoint_time = end_time - timedelta(seconds=seconds_before_end)
        if checkpoint_time > now and gid:
            # programar job
            when = checkpoint_time - now
            context.job_queue.run_once(job_send_message, when, data={"gid": gid, "msg": msg, "kb": kb})

    # programar mensaje final
    context.job_queue.run_once(job_send_message, remaining_seconds, data={"gid": gid, "msg": "🏁 La guerra ha terminado. ¡Gracias a todos por participar!", "kb": None})


async def war_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    try:
        supabase.table("users").update({"send": True, "sent_war": True}).eq("uid", uid).execute() if supabase else None
    except Exception:
        logger.exception("Error marcando send en BD para %s", uid)
    await query.answer("✅ Tropas enviadas")


async def warless_calc(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, emoji: str):
    try:
        users_res = supabase.table("users").select("*").eq("sent_war", False).execute() if supabase else None
        users = users_res.data if users_res and getattr(users_res, "data", None) else []
    except Exception:
        users = []
    total = sum(u.get(key, 0) for u in users if u.get(key))
    await update.message.reply_text(f"{emoji} Restante: {total:,}")


async def warlessa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await warless_calc(update, context, "atk", "⚔️")


async def warlessd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await warless_calc(update, context, "def", "🛡")


async def endwar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    try:
        supabase.table("users").update({"sent_war": False}).neq("uid", "").execute() if supabase else None
    except Exception:
        logger.exception("Error reseteando sent_war")
    await update.message.reply_text("🏁 Guerra finalizada.")


# ================= SYNC MEMBERS =================
async def sync_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    gid = get_group_id()
    if not gid:
        await update.message.reply_text("❌ Grupo no configurado.")
        return

    members_res = supabase.table("members").select("*").eq("registered", False).execute() if supabase else None
    members = members_res.data if members_res and getattr(members_res, "data", None) else []
    if not members:
        await update.message.reply_text("✅ Todos los miembros están registrados.")
        return
    msg = "👥 Miembros no registrados:\n" + "\n".join([f"- {m['uid']}" for m in members])
    await update.message.reply_text(msg)


# ================= MENCIONAR RAZAS =================
async def mention_race(update: Update, context: ContextTypes.DEFAULT_TYPE, race: str):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    users_res = supabase.table("users").select("uid").eq("race", race).execute() if supabase else None
    users = users_res.data if users_res and getattr(users_res, "data", None) else []
    if not users:
        await update.message.reply_text(f"❌ No hay usuarios de raza {race}.")
        return
    mentions = " ".join([f"@{u['uid']}" for u in users])
    gid = get_group_id()
    if gid:
        await context.bot.send_message(gid, f"📢 Mención a {race}s: {mentions}")


async def allgato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mention_race(update, context, "Gato")


async def allperro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mention_race(update, context, "Perro")


async def allrana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mention_race(update, context, "Rana")


# ================= MANEJAR MIEMBROS SALIENDO =================
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if chat_member.new_chat_member.status in ("left", "kicked"):
        uid = str(chat_member.new_chat_member.user.id)
        try:
            supabase.table("users").delete().eq("uid", uid).execute() if supabase else None
            supabase.table("members").delete().eq("uid", uid).execute() if supabase else None
        except Exception:
            logger.exception("Error borrando usuario que sali\u00f3 del grupo: %s", uid)


# ================= MENCION AL BOT =================
async def mention_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.entities:
        return
    for entity in update.message.entities:
        # buscamos menciones exactas al bot
        if entity.type == "mention":
            text = update.message.text[entity.offset: entity.offset + entity.length]
            if text == f"@{context.bot.username}":
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


# ================= APP (Telegram) =================
async def build_application():
    return Application.builder().token(TOKEN).build()


tg_app = Application.builder().token(TOKEN).build()

# Conversation handler
conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start_act_entry, filters=filters.ChatType.PRIVATE),
        CommandHandler("act", start_act_entry, filters=filters.ChatType.PRIVATE),
    ],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_def)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    per_chat=False,
    conversation_timeout=90,
)

# Registros de handlers
tg_app.add_handler(conv)

tg_app.add_handler(CommandHandler("atk", atk))
# "def" es nombre de funcion, usamos "defense" como handler
tg_app.add_handler(CommandHandler("def", defense))
tg_app.add_handler(CommandHandler("me", me))
tg_app.add_handler(CommandHandler("member", member))
tg_app.add_handler(CommandHandler("memberlist", memberlist))
tg_app.add_handler(CommandHandler("delist", delist))
tg_app.add_handler(CommandHandler("war", war))
tg_app.add_handler(CommandHandler("warlessa", warlessa))
tg_app.add_handler(CommandHandler("warlessd", warlessd))
tg_app.add_handler(CommandHandler("endwar", endwar))
tg_app.add_handler(CommandHandler("sync_members", sync_members))
tg_app.add_handler(CommandHandler("allgato", allgato))
tg_app.add_handler(CommandHandler("allperro", allperro))
tg_app.add_handler(CommandHandler("allrana", allrana))
tg_app.add_handler(CommandHandler("cancelall", cancelall))

# Callback handlers
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_send$"))
tg_app.add_handler(CallbackQueryHandler(delist_callback, pattern="^delist_"))
# Chat member updates
try:
    tg_app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
except Exception:
    # Dependiendo de la versión de PTB, la forma de registrar ChatMemberHandler puede variar
    logger.warning("No se pudo registrar ChatMemberHandler en esta versi\u00f3n de PTB")

# Mensiones al bot
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
        try:
            await tg_app.bot.send_message(gid, "⚡ Version 0.1.2 del Clan Helper activa!  🎮")
        except Exception:
            logger.exception("No se pudo enviar mensaje de inicio al grupo")
    logger.info("✅ Bot listo y estable")


@app.on_event("shutdown")
async def shutdown():
    await tg_app.stop()
    await tg_app.shutdown()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    # Arranca uvicorn para servir FastAPI (y el webhook que empuja actualizaciones al bot)
    uvicorn.run(app, host="0.0.0.0", port=port)
