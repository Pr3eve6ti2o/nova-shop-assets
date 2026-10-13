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
from utils import h
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
    # Opus P2: was deleting the same message twice (copy-paste bug).
    try:
        await message.delete()
    except Exception:
        pass


@dp.message_handler(text=texts.BTN_SUPPORT, state="*")
async def nav_help(message: types.Message):
    await _try_delete(message)
    await get_or_register(message.from_user.id, message.from_user.full_name)
    await message.answer(texts.MSG_HELP, reply_markup=kb.support_kb(),
                         disable_web_page_preview=True)


@dp.message_handler(commands=["support"], state="*")
async def cmd_support(message: types.Message):
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    await render_support_list(message, user["id"])


@dp.callback_query_handler(text="sup_list", state="*")
async def cb_support_list(query: types.CallbackQuery):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_support_list(query, user["id"])


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("supt:"), state="*")
async def cb_support_ticket(query: types.CallbackQuery):
    try:
        tid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return await query.answer(texts.ERR_GENERIC, show_alert=True)
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    t = await db.ticket_get(tid)
    if not t or t["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    created = (t["created_at"] or "")[:16].replace("T", " ")
    # Port 3.1: render the thread, not just the subject line.
    thread = await db.ticket_messages(tid, limit=10)
    lines = [texts.MSG_SUPPORT_TICKET_DETAIL.format(
        id=t["id"], status=t["status"], subject=h(t["subject"] or ""),
        created=created or "\u2014")]
    if thread:
        lines.append("")
        for m in thread:
            who = "\U0001f9d1 You" if m["sender"] == "user" else "\U0001f6df Support"
            when = (m["created_at"] or "")[:16].replace("T", " ")
            lines.append(f"<b>{who}</b> \u00b7 {when}\n{h(m['body'])}")
    markup = types.InlineKeyboardMarkup()
    if t["status"] == "open":
        markup.add(InlineKeyboardButton(
            "\u2709\ufe0f Add a message", callback_data=f"supa:{tid}"))
        markup.add(InlineKeyboardButton(texts.BTN_CLOSE_TICKET,
                                       callback_data=f"suptc:{tid}"))
    markup.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="sup_list"))
    await edit_text_safe(query, "\n\n".join(lines), markup)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("supa:"),
                           state="*")
async def cb_support_add(query: types.CallbackQuery, state: FSMContext):
    try:
        tid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return await query.answer(texts.ERR_GENERIC, show_alert=True)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    t = await db.ticket_get(tid)
    if not t or t["user_id"] != user["id"] or t["status"] != "open":
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await query.answer()
    await SupportFlow.followup.set()
    await state.update_data(followup_ticket=tid)
    await query.message.answer(
        f"\u2709\ufe0f <b>Ticket #{tid}</b> \u2014 type your message and it "
        "will be added to this conversation.",
        reply_markup=kb.force_reply())


@dp.message_handler(state=SupportFlow.followup)
async def support_followup(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    tid = data.get("followup_ticket")
    await state.finish()
    if not text or not tid:
        return
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    t = await db.ticket_get(int(tid))
    if not t or t["user_id"] != user["id"]:
        return await message.answer(texts.ERR_NOT_FOUND)
    try:
        await db.ticket_add_message(int(tid), "user", text)
    except ValueError as e:
        return await message.answer(f"\u26a0\ufe0f {e}")
    await notify_admins(
        f"\u2709\ufe0f <b>Ticket #{tid}</b> \u2014 new message from the "
        f"customer:\n\n{h(text)}",
        min_bit=0, reply_markup=kb.admin_reply_kb(user["tg_id"]),
        topic=config.ADMIN_TOPIC_SUPPORT or None)
    await message.answer("\u2705 Added to your ticket. We'll reply here.")


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("suptc:"), state="*")
async def cb_support_ticket_close(query: types.CallbackQuery):
    try:
        tid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return await query.answer(texts.ERR_GENERIC, show_alert=True)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if await _close_ticket(tid, user["id"]):
        await query.answer(texts.TOAST_TICKET_CLOSED)
    else:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await render_support_list(query, user["id"])


@dp.callback_query_handler(text="help", state="*")
async def cb_help(query: types.CallbackQuery):
    await query.answer()
    await edit_text_safe(query, texts.MSG_HELP, kb.support_kb())


@dp.callback_query_handler(text="sup", state="*")
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
    # Port 3.1: the ticket now stores its first message in the thread.
    ticket_id = await db.ticket_create(user["id"], text)
    await notify_admins(
        texts.MSG_SUPPORT_TICKET_ADMIN.format(
            ticket_id=ticket_id, name=h(user["name"] or "?"),
            tg_id=user["tg_id"], text=h(text)),
        min_bit=0, reply_markup=kb.admin_reply_kb(user["tg_id"]),
        topic=config.ADMIN_TOPIC_SUPPORT or None)
    await message.answer(texts.MSG_SUPPORT_TICKET_OPEN.format(id=ticket_id))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("srep:"), state="*")
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
    # Defence in depth (stress-audit LOW-3): this handler was gated by
    # FSM state alone; re-check the same gate as the reply button.
    if not await _support_admin(message.from_user.id):
        await state.finish()
        return
    if await handle_escape(message, state):
        return
    data = await state.get_data()
    target = data.get("reply_to")
    reply_ticket = data.get("reply_ticket")
    text = (message.text or "").strip()
    await state.finish()
    if target and text:
        try:
            await bot.send_message(target, texts.MSG_SUPPORT_FROM_ADMIN.format(text=text))
            # Port 3.1: store the reply in the thread so both sides keep
            # the full conversation. Explicit ticket (inbox) wins; else
            # the customer's most recent open ticket.
            try:
                tuser = await db.get_user_by_tg(target)
                if tuser:
                    tid = reply_ticket
                    if not tid:
                        open_ts = await db.user_open_tickets(tuser["id"])
                        tid = open_ts[0]["id"] if open_ts else None
                    if tid:
                        await db.ticket_add_message(int(tid), "admin", text)
            except Exception:
                pass  # storage must never block the reply itself
            await message.answer(texts.MSG_SUPPORT_REPLIED)
        except Exception:
            await message.answer(texts.ERR_GENERIC)


# ------------------------------------------------------- admin inbox (3.2)
async def _support_admin(tg_id: int) -> bool:
    """Same gate as the reply button: config admins or any role mask."""
    if tg_id in config.ADMINS:
        return True
    u = await db.get_user_by_tg(tg_id)
    return bool(u and u["role_mask"])


def _inbox_kb(rows):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for t in rows:
        arrow = "🧑" if t["last_sender"] == "user" else "🛟"
        preview = (t["last_body"] or t["subject"] or "")[:28]
        order = f" · order #{t['order_id']}" if t["order_id"] else ""
        markup.add(InlineKeyboardButton(
            f"#{t['id']} {arrow} {preview}{order}",
            callback_data=f"supv:{t['id']}"))
    return markup


async def _render_inbox(target):
    rows = await db.tickets_inbox(limit=15)
    if rows:
        text = ("📥 <b>Support inbox</b>\n\nOpen conversations, latest "
                "first. 🧑 = waiting on us, 🛟 = we replied last.")
        kb = _inbox_kb(rows)
    else:
        text = "📥 <b>Support inbox</b>\n\nNo open conversations. 🎉"
        kb = None
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb,
                            disable_web_page_preview=True)


@dp.message_handler(commands=["inbox"], state="*")
async def cmd_inbox(message: types.Message, state: FSMContext):
    if not await _support_admin(message.from_user.id):
        return await message.answer(texts.MSG_ADMIN_DENIED)
    await state.finish()
    await _render_inbox(message)


@dp.callback_query_handler(text="supi", state="*")
async def cb_inbox(query: types.CallbackQuery, state: FSMContext):
    if not await _support_admin(query.from_user.id):
        return await query.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
    await state.finish()
    await query.answer()
    await _render_inbox(query)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("supv:"),
                           state="*")
async def cb_inbox_view(query: types.CallbackQuery, state: FSMContext):
    if not await _support_admin(query.from_user.id):
        return await query.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
    await state.finish()
    tid = int(query.data.split(":")[1])
    t = await db.ticket_get(tid)
    if not t:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await query.answer()
    customer = await db.get_user(t["user_id"])
    thread = await db.ticket_messages(tid, limit=15)
    lines = [f"🎫 <b>Ticket #{tid}</b> — {t['status']}"
             + (f" · order #{t['order_id']}" if t["order_id"] else ""),
             f"Customer: {customer['name'] if customer else '?'}"
             f" (<code>{customer['tg_id'] if customer else '?'}</code>)",
             ""]
    for m in thread:
        who = "🧑 Customer" if m["sender"] == "user" else "🛟 Support"
        when = (m["created_at"] or "")[:16].replace("T", " ")
        lines.append(f"<b>{who}</b> · {when}\n{m['body']}")
    markup = types.InlineKeyboardMarkup(row_width=2)
    if t["status"] == "open":
        markup.add(InlineKeyboardButton(
            "✉️ Reply", callback_data=f"supr:{tid}"),
            InlineKeyboardButton(
                "✅ Close ticket", callback_data=f"supx:{tid}"))
    markup.add(InlineKeyboardButton("⬅️ Inbox", callback_data="supi"))
    await edit_text_safe(query, "\n\n".join(lines), markup)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("supr:"),
                           state="*")
async def cb_inbox_reply(query: types.CallbackQuery, state: FSMContext):
    if not await _support_admin(query.from_user.id):
        return await query.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
    tid = int(query.data.split(":")[1])
    t = await db.ticket_get(tid)
    if not t or t["status"] != "open":
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    customer = await db.get_user(t["user_id"])
    if not customer:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await query.answer()
    await AdminReplyFlow.waiting_text.set()
    await state.update_data(reply_to=customer["tg_id"], reply_ticket=tid)
    await query.message.answer(
        texts.MSG_SUPPORT_REPLY_ASK.format(tg_id=customer["tg_id"]),
        reply_markup=kb.force_reply())


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("supx:"),
                           state="*")
async def cb_inbox_close(query: types.CallbackQuery):
    if not await _support_admin(query.from_user.id):
        return await query.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
    tid = int(query.data.split(":")[1])
    if await db.ticket_close(tid):
        await query.answer("Ticket closed ✅")
    else:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await _render_inbox(query)
