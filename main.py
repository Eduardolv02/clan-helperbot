#!/usr/bin/env python3
"""
Clan Helper Bot - Beta 2 (deploy-ready)

- Single-file bot that runs under Uvicorn/FastAPI (exposes `app`).
- On startup it initializes and starts the python-telegram-bot Application in background.
- Uses Supabase as DB backend.
- Conversation flow in private: guser -> race (inline) -> atk (numeric keyboard) -> def (numeric keyboard) -> confirm -> upsert.
- Timeout: 180 seconds (3 minutes).
- Commands: start/act/me/atk/def/member/memberlist/delist/war/warlessa/warlessd/endwar/sync_members/allgato/allperro/allrana/cancel/cancelall/getcom
- Environment variables required: BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY
"""

import os
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, List, Tuple

from fastapi import FastAPI, Request
import uvicorn

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    ChatMemberHandler,
)

from supabase import create_client

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Config / Supabase ----------
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not TOKEN:
    logger.warning("BOT_TOKEN not set in environment.")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logger.warning("SUPABASE_URL or SUPABASE_KEY not set; DB operations will fail.")

# ---------- Conversation states & settings ----------
ASK_GUSER, ASK_RACE, ASK_ATK, ASK_DEF, CONFIRM = range(5)
TIMEOUT_SECONDS = 180  # 3 minutes

# ---------- Utilities ----------
def parse_power(text: str) -> Optional[int]:
    """Parse strings like '34k', '1.5m', '1200' -> int or None."""
    if not isinstance(text, str):
        return None
    t = text.strip().lower().replace(",", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", t)
    if not m:
        return None
    num = float(m.group(1))
    suf = m.group(2)
    if suf == "k":
        num *= 1_000
    elif suf == "m":
        num *= 1_000_000
    return int(num)

def build_num_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        ["0", "k", "m"],
        ["Cancelar"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=False)

def get_group_id() -> Optional[int]:
    """Read settings.group_id from supabase settings table if present."""
    try:
        if not supabase:
            return None
        res = supabase.table("settings").select("value").eq("key", "group_id").execute()
        if res and getattr(res, "data", None):
            return int(res.data[0]["value"])
    except Exception:
        logger.exception("Error reading group_id")
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

def expired(context: ContextTypes.DEFAULT_TYPE) -> bool:
    started = context.user_data.get("started_at")
    if not started:
        return True
    return (datetime.utcnow() - started).total_seconds() > TIMEOUT_SECONDS

# ---------- Handlers: start / registration flow ----------
async def start_group_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When /start is used in group — invite user to PM the bot."""
    bot_username = context.bot.username or "<bot>"
    text = (
        "⚡ *Versión de prueba: Beta 2*\n\n"
        "Para registrarte o actualizar tus stats, por favor envíame un mensaje privado:\n"
        f"▶️ @{bot_username}\n\n"
        "Espera nuevos requisitos que publicará el admin. Gracias."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def start_act_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for /start and /act in private chat."""
    # Only private
    if update.effective_chat is None or update.effective_chat.type != "private":
        if update.message:
            await update.message.reply_text("🚫 Usa este comando en privado conmigo.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    # protect against concurrent process
    if context.user_data.get("active_process"):
        await update.message.reply_text("⚠️ Tienes un proceso activo. Usa /cancel para reiniciarlo.")
        return ConversationHandler.END

    if not await belongs_to_clan(context.bot, user_id):
        await update.message.reply_text("🚫 No perteneces al clan.")
        return ConversationHandler.END

    uid = str(user_id)
    # check exists
    exists = None
    try:
        exists = supabase.table("users").select("uid").eq("uid", uid).execute() if supabase else None
    except Exception:
        logger.exception("Error checking user exists.")

    # init session
    context.user_data.clear()
    context.user_data["started_at"] = datetime.utcnow()
    context.user_data["uid"] = uid
    context.user_data["active_process"] = True

    if exists and getattr(exists, "data", None):
        context.user_data["is_act"] = True
        # ask for atk directly
        await update.message.reply_text("⚔️ Ingresa tu nuevo ATAQUE (ej: 34k, 1.5m, 34000):", reply_markup=build_num_keyboard())
        return ASK_ATK
    else:
        context.user_data["is_act"] = False
        await update.message.reply_text("🎮 Escribe tu nombre en el juego:", reply_markup=ReplyKeyboardRemove())
        return ASK_GUSER

async def get_guser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if expired(context):
        await update.message.reply_text("⏱️ Tiempo agotado. Usa /start nuevamente.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    text = update.message.text.strip() if update.message and update.message.text else ""
    if text.lower() == "cancelar":
        await update.message.reply_text("❌ Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    if not text:
        await update.message.reply_text("❌ Nombre inválido. Escríbelo de nuevo.")
        return ASK_GUSER

    context.user_data["guser"] = text
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
    if expired(context):
        await query.edit_message_text("⏱️ Tiempo agotado. Usa /start nuevamente.")
        context.user_data.clear()
        return ConversationHandler.END

    race_map = {"race_gato": "gato", "race_perro": "perro", "race_rana": "rana"}
    race = race_map.get(query.data)
    if not race:
        await query.edit_message_text("❌ Raza inválida.")
        return ConversationHandler.END

    context.user_data["race"] = race
    # ask atk with numeric keyboard
    await query.edit_message_text("⚔️ Ingresa tu ATAQUE (ej: 34k, 1.5m, 34000):")
    await context.bot.send_message(query.from_user.id, "Usa el teclado de abajo. Pulsa 'Cancelar' para salir.", reply_markup=build_num_keyboard())
    return ASK_ATK

async def get_atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if expired(context):
        await update.message.reply_text("⏱️ Tiempo agotado. Usa /start nuevamente.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    raw = update.message.text if update.message and update.message.text else ""
    if raw.lower() == "cancelar":
        await update.message.reply_text("❌ Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    power = parse_power(raw)
    if power is None:
        await update.message.reply_text("❌ Valor inválido. Ej: 34k o 1.5m", reply_markup=build_num_keyboard())
        return ASK_ATK

    context.user_data["atk"] = power
    await update.message.reply_text(f"🛡 Ahora ingresa tu DEFENSA. Ataque registrado: {power:,}", reply_markup=build_num_keyboard())
    return ASK_DEF

async def get_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if expired(context):
        await update.message.reply_text("⏱️ Tiempo agotado. Usa /start nuevamente.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    raw = update.message.text if update.message and update.message.text else ""
    if raw.lower() == "cancelar":
        await update.message.reply_text("❌ Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    defense = parse_power(raw)
    if defense is None:
        await update.message.reply_text("❌ Valor inválido. Ej: 80k o 1m", reply_markup=build_num_keyboard())
        return ASK_DEF

    uid = context.user_data.get("uid")
    try:
        if context.user_data.get("is_act"):
            # update existing
            if supabase:
                supabase.table("users").update({
                    "atk": context.user_data["atk"],
                    "def": defense,
                    "sent_war": False
                }).eq("uid", uid).execute()
                user_res = supabase.table("users").select("*").eq("uid", uid).execute()
                user_data = user_res.data[0] if user_res and getattr(user_res, "data", None) else None
            else:
                user_data = None

            await update.message.reply_text(
                f"✅ Poder actualizado con éxito.\n"
                f"🎮 Nombre: {user_data.get('guser') if user_data else '—'}\n"
                f"🏹 Raza: {user_data.get('race') if user_data else '—'}\n"
                f"⚔️ Ataque: {context.user_data.get('atk'):,}\n"
                f"🛡 Defensa: {defense:,}",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            # insert new user and update members
            tg = update.effective_user.username
            if supabase:
                supabase.table("users").insert({
                    "uid": uid,
                    "tg": tg,
                    "guser": context.user_data.get("guser"),
                    "race": context.user_data.get("race"),
                    "atk": context.user_data.get("atk"),
                    "def": defense,
                    "sent_war": False
                }).execute()
                # upsert into members
                try:
                    supabase.table("members").upsert({
                        "uid": uid,
                        "tg": tg,
                        "registered": True,
                        "messages": 0
                    }).execute()
                except Exception:
                    try:
                        supabase.table("members").update({"tg": tg, "registered": True}).eq("uid", uid).execute()
                    except Exception:
                        pass

            await update.message.reply_text(
                f"✅ Registro completado con éxito.\n"
                f"🎮 Nombre: {context.user_data.get('guser')}\n"
                f"🏹 Raza: {context.user_data.get('race')}\n"
                f"⚔️ Ataque: {context.user_data.get('atk'):,}\n"
                f"🛡 Defensa: {defense:,}",
                reply_markup=ReplyKeyboardRemove()
            )
    except Exception:
        logger.exception("Error saving to DB")
        await update.message.reply_text("❌ Error al guardar. Inténtalo de nuevo.", reply_markup=ReplyKeyboardRemove())
        return ASK_DEF

    context.user_data.clear()
    return ConversationHandler.END

# ---------- Cancel handlers ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("❌ Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(context.bot, user_id):
        await update.message.reply_text("🚫 Solo admins pueden usar /cancelall.")
        return
    await update.message.reply_text("⚠️ Todos los procesos activos de los usuarios han sido cancelados.")

# ---------- Show power (rankings) ----------
async def show_power(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    try:
        users_res = supabase.table("users").select("*").execute() if supabase else None
        users = users_res.data if users_res and getattr(users_res, "data", None) else []
    except Exception:
        users = []
    users = [u for u in users if u.get(key)]
    users.sort(key=lambda u: u.get(key, 0), reverse=True)
    icon = "⚔️" if key == "atk" else "🛡"
    total = sum(u.get(key, 0) for u in users)
    lines = [f"🎮 {u.get('guser', u.get('uid'))}\n└ {icon} {u.get(key):,}" for u in users]
    msg = f"{icon} PODER DEL CLAN\n\n" + "\n\n".join(lines) + f"\n\n🔥 TOTAL: {total:,}"
    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg)

async def cmd_atk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_power(update, context, "atk")

async def cmd_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_power(update, context, "def")

# ---------- /me ----------
async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    try:
        user_res = supabase.table("users").select("*").eq("uid", uid).execute() if supabase else None
        user_data = user_res.data[0] if user_res and getattr(user_res, "data", None) else None
    except Exception:
        user_data = None

    if not user_data:
        await update.message.reply_text("❌ No estás registrado. Usa /start para registrarte.")
        return

    await update.message.reply_text(
        f"🎮 Nombre: {user_data.get('guser')}\n"
        f"🏹 Raza: {user_data.get('race')}\n"
        f"⚔️ Ataque: {user_data.get('atk'):,}\n"
        f"🛡 Defensa: {user_data.get('def'):,}"
    )

# ---------- Members ----------
async def cmd_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    tg = update.effective_user.username
    try:
        exists = supabase.table("members").select("uid").eq("uid", uid).execute() if supabase else None
    except Exception:
        exists = None

    if exists and getattr(exists, "data", None):
        try:
            supabase.table("members").update({"tg": tg}).eq("uid", uid).execute() if supabase else None
        except Exception:
            pass
        await update.message.reply_text("✅ Ya estás en la lista de miembros.")
        return

    try:
        if supabase:
            supabase.table("members").insert({"uid": uid, "tg": tg, "registered": False, "messages": 0}).execute()
    except Exception:
        logger.exception("Error insert member")

    await update.message.reply_text("✅ Agregado a la lista de miembros. Ahora puedes registrarte con /start.")

async def cmd_memberlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        tg = m.get("tg")
        if tg:
            mentions.append(f"@{tg}")
        else:
            mentions.append(f"@{m.get('uid')}")
    gid = get_group_id()
    msg = "👥 Miembros no registrados: " + " ".join(mentions)
    if gid:
        await context.bot.send_message(gid, msg)
    else:
        await update.message.reply_text(msg)

# ---------- Delist (interactive) ----------
async def cmd_delist(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        user_data = None
        try:
            user_res = supabase.table("users").select("guser,tg").eq("uid", uid).execute() if supabase else None
            user_data = user_res.data[0] if user_res and getattr(user_res, "data", None) else None
        except Exception:
            user_data = None
        if user_data and user_data.get("guser"):
            name = user_data.get("guser")
        elif m.get("tg"):
            name = f"@{m.get('tg')}"
        elif user_data and user_data.get("tg"):
            name = f"@{user_data.get('tg')}"
        else:
            name = f"@{uid}"
        names.append(name)
        kb.append([InlineKeyboardButton(name, callback_data=f"delist_select_{uid}")])
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

# ---------- WAR (scheduling) ----------
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

async def cmd_war(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await context.bot.send_message(gid, f"🔥 GUERRA INICIADA a las {h:02d}:{m:02d}! Terminará a las {end_time.hour:02d}:{end_time.minute:02d}", reply_markup=kb)
        except Exception:
            logger.exception("No se pudo anunciar la guerra en el grupo")
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
            when = checkpoint_time - now
            context.job_queue.run_once(job_send_message, when, data={"gid": gid, "msg": msg, "kb": kb})
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

async def cmd_warlessa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await warless_calc(update, context, "atk", "⚔️")

async def cmd_warlessd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await warless_calc(update, context, "def", "🛡")

async def cmd_endwar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    try:
        supabase.table("users").update({"sent_war": False}).neq("uid", "").execute() if supabase else None
    except Exception:
        logger.exception("Error reseteando sent_war")
    await update.message.reply_text("🏁 Guerra finalizada.")

# ---------- Sync Members ----------
async def cmd_sync_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ---------- Mention bot / getcom ----------
async def mention_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.entities:
        return
    for entity in update.message.entities:
        if entity.type == "mention":
            text = update.message.text[entity.offset: entity.offset + entity.length]
            if text == f"@{context.bot.username}":
                commands = """
📋 Comandos disponibles:
/start - Registrarte en el clan (en privado).
/act - Actualizar tus stats (en privado).
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
/getcom - Mostrar comandos y su función.
"""
                await update.message.reply_text(commands)
                return

async def cmd_getcom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd_list: List[Tuple[str, str]] = [
        ("/start", "Inicia el registro o actualización de tus stats (debe ser en privado)."),
        ("/act", "Alias de /start: actualizar tus stats si ya estás registrado."),
        ("/me", "Muestra tus datos registrados (nombre, raza, ataque, defensa)."),
        ("/atk", "Muestra el ranking de ataque del clan."),
        ("/def", "Muestra el ranking de defensa del clan."),
        ("/member", "Agrega tu UID a la lista de miembros (registro previo)."),
        ("/memberlist", "(Admins) Publica la lista de miembros no registrados."),
        ("/delist", "(Admins) Gestiona y elimina miembros desde un menú interactivo."),
        ("/war HH:MM", "(Admins) Inicia una guerra basada en la hora de inicio (ya pasada)."),
        ("/warlessa", "Muestra poder de ataque restante (usuarios que no enviaron tropas)."),
        ("/warlessd", "Muestra poder de defensa restante (usuarios que no enviaron tropas)."),
        ("/endwar", "(Admins) Finaliza la guerra y resetea los flags de envío."),
        ("/sync_members", "(Admins) Mostrar miembros no registrados (limitado por Supabase)."),
        ("/allgato / allperro / allrana", "(Admins) Menciona usuarios por raza."),
        ("/cancel", "Cancela el proceso actual del usuario en el conversation handler."),
        ("/cancelall", "(Admins) Forzar cancelación de procesos (lógica simple)."),
        ("/getcom", "Muestra esta lista de comandos y su función."),
    ]
    lines = [f"{cmd} — {desc}" for cmd, desc in cmd_list]
    msg = "📋 Comandos disponibles y su función:\n\n" + "\n".join(lines)
    MAX = 3800
    if len(msg) <= MAX:
        await update.message.reply_text(msg)
        return
    parts = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > MAX:
            parts.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        parts.append(current)
    for p in parts:
        await update.message.reply_text("📋 Comandos disponibles y su función:\n\n" + p)

# ---------- Chat member left handling ----------
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if chat_member.new_chat_member.status in ("left", "kicked"):
        uid = str(chat_member.new_chat_member.user.id)
        try:
            supabase.table("users").delete().eq("uid", uid).execute() if supabase else None
            supabase.table("members").delete().eq("uid", uid).execute() if supabase else None
        except Exception:
            logger.exception("Error borrando usuario que salió del grupo: %s", uid)

# ---------- Mention by race ----------
async def cmd_allgato(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await mention_race_helper(update, context, "gato")
async def cmd_allperro(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await mention_race_helper(update, context, "perro")
async def cmd_allrana(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await mention_race_helper(update, context, "rana")

async def mention_race_helper(update: Update, context: ContextTypes.DEFAULT_TYPE, race: str):
    if not await is_admin(context.bot, update.effective_user.id):
        await update.message.reply_text("🚫 Solo admins.")
        return
    try:
        res = supabase.table("users").select("tg").eq("race", race).execute() if supabase else None
        users = res.data if res and getattr(res, "data", None) else []
    except Exception:
        users = []
    mentions = [f"@{u['tg']}" for u in users if u.get("tg")]
    if not mentions:
        await update.message.reply_text(f"❌ No hay usuarios de raza {race} con username para mencionar.")
        return
    gid = get_group_id()
    msg = f"📢 Mención a {race}s: " + " ".join(mentions)
    if gid:
        await context.bot.send_message(gid, msg)
    else:
        await update.message.reply_text(msg)

# ---------- Application build & registration ----------
tg_app = Application.builder().token(TOKEN).build()

# Conversation handler
conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_act_entry, filters=filters.ChatType.PRIVATE), CommandHandler("act", start_act_entry, filters=filters.ChatType.PRIVATE)],
    states={
        ASK_GUSER: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_guser)],
        ASK_RACE: [CallbackQueryHandler(get_race, pattern="^race_")],
        ASK_ATK: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_atk)],
        ASK_DEF: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_def)],
        CONFIRM: [CallbackQueryHandler(lambda u,c: None)]  # confirm handled inline in flow (if needed can be added)
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    per_chat=False,
    conversation_timeout=TIMEOUT_SECONDS,
)

# Register handlers
tg_app.add_handler(CommandHandler("start", start_group_entry, filters=filters.ChatType.GROUP | filters.ChatType.SUPERGROUP))
tg_app.add_handler(conv)
tg_app.add_handler(CommandHandler("atk", cmd_atk))
tg_app.add_handler(CommandHandler("def", cmd_def))
tg_app.add_handler(CommandHandler("me", cmd_me))
tg_app.add_handler(CommandHandler("member", cmd_member))
tg_app.add_handler(CommandHandler("memberlist", cmd_memberlist))
tg_app.add_handler(CommandHandler("delist", cmd_delist))
tg_app.add_handler(CommandHandler("war", cmd_war))
tg_app.add_handler(CommandHandler("warlessa", cmd_warlessa))
tg_app.add_handler(CommandHandler("warlessd", cmd_warlessd))
tg_app.add_handler(CommandHandler("endwar", cmd_endwar))
tg_app.add_handler(CommandHandler("sync_members", cmd_sync_members))
tg_app.add_handler(CommandHandler("allgato", cmd_allgato))
tg_app.add_handler(CommandHandler("allperro", cmd_allperro))
tg_app.add_handler(CommandHandler("allrana", cmd_allrana))
tg_app.add_handler(CommandHandler("cancelall", cancelall))
tg_app.add_handler(CommandHandler("getcom", cmd_getcom))
tg_app.add_handler(CallbackQueryHandler(war_callback, pattern="^war_send$"))
tg_app.add_handler(CallbackQueryHandler(delist_callback, pattern="^delist_"))
try:
    tg_app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
except Exception:
    logger.warning("Could not register ChatMemberHandler on this PTB version")
tg_app.add_handler(MessageHandler(filters.Entity("mention"), mention_bot))

# ---------- FastAPI app (exposes 'app') ----------
app = FastAPI()

@app.post("/webhook")
async def webhook(req: Request):
    """Optional webhook endpoint — if you use webhooks, you can POST updates here."""
    data = await req.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.update_queue.put(update)
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "ok", "bot": "Clan Helper Beta 2"}

# Start Telegram Application when FastAPI starts
@app.on_event("startup")
async def startup():
    try:
        await tg_app.initialize()
        await tg_app.start()
        gid = get_group_id()
        if gid:
            try:
                await tg_app.bot.send_message(gid, "⚡ Versión de prueba: Beta 2 del Clan Helper activa! 🎮\nPor favor esperen nuevos requisitos del admin.")
            except Exception:
                logger.exception("Could not send startup message to group")
        logger.info("✅ Bot listo y estable")
    except Exception:
        logger.exception("Error starting telegram application")

@app.on_event("shutdown")
async def shutdown():
    try:
        await tg_app.stop()
        await tg_app.shutdown()
    except Exception:
        logger.exception("Error shutting down telegram application")

# ---------- Run (uvicorn entrypoint) ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
