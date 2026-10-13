"""Customer returns (port plan 1.1): request a return from the order page.

Flow: order detail -> "Request return" -> type a reason -> the request is
stored (db.create_return validates ownership, state, window, duplicates)
and admins are notified with a deep link to the admin decision view.
Existing buttons and texts are untouched; this module only appends.
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import texts
from loader import bot, db, dp
from states import ReturnFlow
from .common import get_or_register, notify_admins


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rtn:new:"),
                           state="*")
async def cb_return_start(query: types.CallbackQuery, state: FSMContext):
    try:
        oid = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        return await query.answer(texts.ERR_GENERIC, show_alert=True)
    user = await get_or_register(query.from_user)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    if order["status"] not in db.RETURNABLE_STATUSES:
        return await query.answer(
            "This order can't be returned in its current state.",
            show_alert=True)
    if await db.get_open_return(oid):
        return await query.answer(
            "A return for this order is already in progress.",
            show_alert=True)
    await state.finish()
    await ReturnFlow.reason.set()
    await state.update_data(return_order_id=oid)
    await query.answer()
    await bot.send_message(
        query.from_user.id,
        "↩️ <b>Request a return</b>\n\n"
        f"Order #{oid} — please tell us why you'd like to return it. "
        "Your message goes to our team, who will review it and reply here.")


@dp.message_handler(state=ReturnFlow.reason)
async def msg_return_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    oid = data.get("return_order_id")
    await state.finish()
    if not oid:
        return await message.answer(texts.ERR_GENERIC)
    user = await get_or_register(message.from_user)
    try:
        rid = await db.create_return(user["id"], int(oid),
                                     message.text or "")
    except ValueError as e:
        return await message.answer(f"⚠️ {e}")
    await message.answer(
        "✅ <b>Return requested.</b>\n\n"
        f"Order #{oid} — our team will review your request and you'll get "
        "the decision here. Approved refunds go to your balance (or are "
        "arranged with you, depending on how you paid).")
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "📥 Review return", callback_data=f"ad:rtn:v:{rid}"))
    await notify_admins(
        f"↩️ <b>New return request #{rid}</b>\n"
        f"Order #{oid} — tap below to review.",
        min_bit=4, reply_markup=markup,
        topic=config.ADMIN_TOPIC_ORDERS or None)
