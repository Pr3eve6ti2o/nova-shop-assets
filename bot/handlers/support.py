"""Support: FAQ/help, ticketed contact-support flow, admin replies."""
from datetime import datetime, timezone

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton

import keyboards as kb
import texts
from loader import bot, db, dp
from states import SupportFlow, AdminReplyFlow
from .common import get_or_register, edit_text_safe, handle_escape, notify_admins
import config


_TICKETS_DDL = (
    "CREATE TABLE IF NOT EXISTS support_tickets("
    " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
    " subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',"
    " created_at TEXT NOT NULL)"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_tickets_table():
    async with db._db() as conn:
        await conn.execute(_TICKETS_DDL)
        await conn.commit()


async def _open_tickets(user_id: int):
    await _ensure_tickets_table()
    async with db._db() as conn:
        async with conn.execute(
                "SELECT id, subject, status, created_at FROM support_tickets"
                " WHERE user_id=? AND status='open' ORDER BY id DESC",
                (user_id,)) as cur:
            return await cur.fetchall()


async def _create_ticket(user_id: int, subject: str) -> int:
    await _ensure_tickets_table()
    async with db._db() as conn:
        cur = await conn.execute(
            "INSERT INTO support_tickets(user_id, subject, status, created_at)"
            " VALUES(?, ?, 'open', ?)",
            (user_id, subject[:60], _now_iso()))
        await conn.commit()
        return cur.lastrowid


async def _close_ticket(ticket_id: int, user_id: int) -> bool:
    await _ensure_tickets_table()
    async with db._db() as conn:
        cur = await conn.execute(
            "UPDATE support_tickets SET status='closed'"
            " WHERE id=? AND user_id=? AND status='open'",
            (ticket_id, user_id))
        await conn.commit()
        return cur.rowcount > 0


async def render_support_list(target, user_id: int):
    """Ticket list for /support: open tickets + New request."""
    tickets = await _open_tickets(user_id)
    lines = [texts.MSG_SUPPORT_TICKETS_TITLE, ""]
    markup = types.InlineKeyboardMarkup()
    if tickets:
        for t in tickets:
            subj = (t["subject"] or "")[:34]
            markup.add(InlineKeyboardButton(
                f"#{t['id']} \u00b7 {subj}", callback_data=f"supt:{t['id']}"))
            lines.append(texts.MSG_SUPPORT_TICKET_ROW.format(
                id=t["id"], subject=subj, status=t["status"]))
    else:
        lines.append(texts.MSG_SUPPORT_NO_TICKETS)
    markup.add(InlineKeyboardButton(texts.BTN_NEW_REQUEST, callback_data="sup"))
    markup.row(kb.BTN_MENU)
    text = "\n".join(lines)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup,
                            disable_web_page_preview=True)


async def _try_delete(message):
    try:
        await message.delete()
    except Exception:
        pass
    try:
        await message.delete()
    except Exception:
        pass


@dp.message_handler(text=texts.BTN_SUPPORT)
async def nav_help(message: types.Message):
    await _try_delete(message)
    await get_or_register(message.from_user.id, message.from_user.full_name)
    await message.answer(texts.MSG_HELP, reply_markup=kb.support_kb(),
                         disable_web_page_preview=True)


@dp.message_handler(commands=["support"])
async def cmd_support(message: types.Message):
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    await render_support_list(message, user["id"])


@dp.callback_query_handler(text="sup_list")
async def cb_support_list(query: types.CallbackQuery):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_support_list(query, user["id"])


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("supt:"))
async def cb_support_ticket(query: types.CallbackQuery):
    await query.answer()
    tid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await _ensure_tickets_table()
    async with db._db() as conn:
        async with conn.execute(
                "SELECT id, subject, status, created_at FROM support_tickets"
                " WHERE id=? AND user_id=?", (tid, user["id"])) as cur:
            t = await cur.fetchone()
    if not t:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    created = (t["created_at"] or "")[:16].replace("T", " ")
    markup = types.InlineKeyboardMarkup()
    if t["status"] == "open":
        markup.add(InlineKeyboardButton(texts.BTN_CLOSE_TICKET,
                                       callback_data=f"suptc:{tid}"))
    markup.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="sup_list"))
    await edit_text_safe(
        query,
        texts.MSG_SUPPORT_TICKET_DETAIL.format(
            id=t["id"], status=t["status"], subject=t["subject"],
            created=created or "\u2014"),
        markup)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("suptc:"))
async def cb_support_ticket_close(query: types.CallbackQuery):
    tid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if await _close_ticket(tid, user["id"]):
        await query.answer(texts.TOAST_TICKET_CLOSED)
    else:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await render_support_list(query, user["id"])


@dp.callback_query_handler(text="help")
async def cb_help(query: types.CallbackQuery):
    await query.answer()
    await edit_text_safe(query, texts.MSG_HELP, kb.support_kb())


@dp.callback_query_handler(text="sup")
async def cb_support(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await SupportFlow.waiting_message.set()
    await query.message.answer(texts.MSG_SUPPORT_ASK, reply_markup=kb.force_reply())


@dp.message_handler(state=SupportFlow.waiting_message)
async def support_message(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    text = (message.text or "").strip()
    if not text:
        return
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await state.finish()
    ticket_id = await _create_ticket(user["id"], text)
    await notify_admins(
        texts.MSG_SUPPORT_TICKET_ADMIN.format(
            ticket_id=ticket_id, name=user["name"] or "?",
            tg_id=user["tg_id"], text=text),
        min_bit=0, reply_markup=kb.admin_reply_kb(user["tg_id"]))
    await message.answer(texts.MSG_SUPPORT_TICKET_OPEN.format(id=ticket_id))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("srep:"))
async def cb_support_reply(query: types.CallbackQuery, state: FSMContext):
    from .admin import IsAdmin
    # Admin-only: re-check manually (callback, not message handler).
    tg_id = query.from_user.id
    allowed = tg_id in config.ADMINS
    if not allowed:
        u = await db.get_user_by_tg(tg_id)
        allowed = bool(u and u["role_mask"])
    if not allowed:
        await query.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
        return
    target = int(query.data.split(":")[1])
    await query.answer()
    await AdminReplyFlow.waiting_text.set()
    await state.update_data(reply_to=target)
    await query.message.answer(texts.MSG_SUPPORT_REPLY_ASK.format(tg_id=target),
                               reply_markup=kb.force_reply())


@dp.message_handler(state=AdminReplyFlow.waiting_text)
async def admin_reply_text(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    data = await state.get_data()
    target = data.get("reply_to")
    text = (message.text or "").strip()
    await state.finish()
    if target and text:
        try:
            await bot.send_message(target, texts.MSG_SUPPORT_FROM_ADMIN.format(text=text))
            await message.answer(texts.MSG_SUPPORT_REPLIED)
        except Exception:
            await message.answer(texts.ERR_GENERIC)
