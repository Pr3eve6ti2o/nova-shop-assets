"""Admin returns console (port plan 1.1).

/returns lists requests (open first). Each request can be:
- approved with an instant refund to the customer's balance,
- approved for a manual refund (admin refunds via the original rail,
  then confirms with "Mark refunded"), or
- denied — a note is REQUIRED and is sent to the customer.

All decisions go through db.decide_return, whose atomic status claim
makes double-refunds impossible. Gated by PERM_ORDERS.
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import texts
from loader import bot, db, dp
from states import AdminReturnFlow
from utils import fmt_money

_STATUS_ICON = {"requested": "🕐", "approved": "✅",
                "denied": "⛔", "refunded": "💸"}


def _list_kb(rows):
    kb = InlineKeyboardMarkup(row_width=1)
    for r in rows:
        kb.add(InlineKeyboardButton(
            f"{_STATUS_ICON.get(r['status'], '')} Return #{r['id']} — "
            f"order #{r['order_id']} — {r['status']}",
            callback_data=f"ad:rtn:v:{r['id']}"))
    return kb


async def _render_list(target):
    rows = await db.list_returns(status="requested", limit=15)
    rows += await db.list_returns(status="approved", limit=10)
    if not rows:
        text = "📥 <b>Returns</b>\n\nNo open return requests."
        kb = None
    else:
        text = ("📥 <b>Returns</b>\n\nOpen requests (tap to review). "
                "Decided returns stay on their order's record.")
        kb = _list_kb(rows)
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@dp.message_handler(commands=["returns"], is_admin=config.PERM_ORDERS,
                    state="*")
async def cmd_returns(message: types.Message, state: FSMContext):
    await state.finish()
    await _render_list(message)


@dp.callback_query_handler(lambda q: q.data == "ad:rtn:list",
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_returns_list(query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await query.answer()
    await _render_list(query)


def _detail_kb(r):
    kb = InlineKeyboardMarkup(row_width=2)
    if r["status"] == "requested":
        kb.add(
            InlineKeyboardButton("✅ Refund to balance",
                                 callback_data=f"ad:rtn:ab:{r['id']}"),
            InlineKeyboardButton("✅ Approve (manual refund)",
                                 callback_data=f"ad:rtn:am:{r['id']}"))
        kb.add(InlineKeyboardButton("⛔ Deny",
                                    callback_data=f"ad:rtn:dn:{r['id']}"))
    elif r["status"] == "approved" and r["refund_target"] == "manual":
        kb.add(InlineKeyboardButton(
            "💸 Mark refunded", callback_data=f"ad:rtn:done:{r['id']}"))
    kb.add(InlineKeyboardButton("⬅️ All returns",
                                callback_data="ad:rtn:list"))
    return kb


async def _render_detail(query, rid: int):
    r = await db.get_return(rid)
    if not r:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    order = await db.get_order(r["order_id"])
    total = fmt_money(order["total_cents"]) if order else "—"
    lines = [
        f"↩️ <b>Return #{r['id']}</b> — {_STATUS_ICON.get(r['status'], '')} "
        f"{r['status']}",
        f"Order: #{r['order_id']} (total {total})",
        f"Requested: {r['created_at']}",
        f"\n<b>Customer's reason:</b>\n{r['reason']}",
    ]
    if r["admin_note"]:
        lines.append(f"\n<b>Admin note:</b>\n{r['admin_note']}")
    if r["status"] == "refunded":
        lines.append(f"Refunded: {fmt_money(r['refund_cents'] or 0)} "
                     f"via {r['refund_target']}")
    await query.answer()
    try:
        await query.message.edit_text("\n".join(lines),
                                      reply_markup=_detail_kb(r))
    except Exception:
        await query.message.answer("\n".join(lines),
                                   reply_markup=_detail_kb(r))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:rtn:v:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_return_detail(query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await _render_detail(query, int(query.data.split(":")[3]))


async def _notify_customer(r, text: str):
    user = await db.get_user(r["user_id"])
    if user:
        try:
            await bot.send_message(user["tg_id"], text)
        except Exception:
            pass


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:rtn:ab:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_return_approve_balance(query: types.CallbackQuery):
    rid = int(query.data.split(":")[3])
    admin = await db.get_user_by_tg(query.from_user.id)
    try:
        outcome = await db.decide_return(
            rid, admin["id"] if admin else 0, approve=True,
            refund_target="balance")
    except ValueError as e:
        return await query.answer(f"⚠️ {e}", show_alert=True)
    r = await db.get_return(rid)
    await query.answer("Refunded to balance 💸")
    await _notify_customer(
        r, f"↩️ <b>Return approved</b>\n\nOrder #{r['order_id']} — "
        f"{fmt_money(r['refund_cents'] or 0)} has been refunded to your "
        "balance.")
    await _render_detail(query, rid)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:rtn:am:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_return_approve_manual(query: types.CallbackQuery):
    rid = int(query.data.split(":")[3])
    admin = await db.get_user_by_tg(query.from_user.id)
    try:
        await db.decide_return(rid, admin["id"] if admin else 0,
                               approve=True, refund_target="manual")
    except ValueError as e:
        return await query.answer(f"⚠️ {e}", show_alert=True)
    r = await db.get_return(rid)
    await query.answer("Approved — refund manually, then mark refunded")
    await _notify_customer(
        r, f"↩️ <b>Return approved</b>\n\nOrder #{r['order_id']} — your "
        "refund is being arranged and you'll be updated here.")
    await _render_detail(query, rid)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:rtn:dn:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_return_deny_start(query: types.CallbackQuery,
                               state: FSMContext):
    rid = int(query.data.split(":")[3])
    await AdminReturnFlow.deny_note.set()
    await state.update_data(deny_return_id=rid)
    await query.answer()
    await bot.send_message(
        query.from_user.id,
        f"⛔ Denying return #{rid} — type the reason. "
        "It is sent to the customer, so write it for them.")


@dp.message_handler(state=AdminReturnFlow.deny_note,
                    is_admin=config.PERM_ORDERS)
async def msg_return_deny_note(message: types.Message, state: FSMContext):
    data = await state.get_data()
    rid = data.get("deny_return_id")
    await state.finish()
    if not rid:
        return await message.answer(texts.ERR_GENERIC)
    admin = await db.get_user_by_tg(message.from_user.id)
    try:
        await db.decide_return(rid, admin["id"] if admin else 0,
                               approve=False, note=message.text or "")
    except ValueError as e:
        return await message.answer(f"⚠️ {e}")
    r = await db.get_return(rid)
    await message.answer(f"⛔ Return #{rid} denied; the customer was notified.")
    await _notify_customer(
        r, f"↩️ <b>Return decision</b>\n\nOrder #{r['order_id']} — we're "
        f"unable to accept this return.\n\n{r['admin_note']}")


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:rtn:done:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_return_mark_refunded(query: types.CallbackQuery):
    rid = int(query.data.split(":")[3])
    r = await db.get_return(rid)
    if not r:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    order = await db.get_order(r["order_id"])
    total = int(order["total_cents"]) if order else 0
    if not await db.mark_return_refunded(rid, total):
        return await query.answer("⚠️ Not in a refundable state.",
                                  show_alert=True)
    await query.answer("Marked refunded 💸")
    r = await db.get_return(rid)
    await _notify_customer(
        r, f"↩️ <b>Refund sent</b>\n\nOrder #{r['order_id']} — your refund "
        f"of {fmt_money(total)} has been completed.")
    await _render_detail(query, rid)
