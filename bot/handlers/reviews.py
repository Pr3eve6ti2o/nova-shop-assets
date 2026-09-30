"""Reviews: list, rating picker, leave-a-review (purchasers only)."""
from aiogram import types
from aiogram.dispatcher import FSMContext

import keyboards as kb
import texts
from loader import db, dp
from states import ReviewFlow
from .common import get_or_register, edit_text_safe, handle_escape, main_reply_kb
from utils import cb


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rv:"))
async def cb_reviews(query: types.CallbackQuery):
    await query.answer()
    pid = int(query.data.split(":")[1])
    p = await db.get_product(pid)
    if not p:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    reviews = await db.list_reviews(pid)
    if reviews:
        lines = []
        for r in reviews:
            stars = "\u2b50" * r["rating"]
            txt = (r["text"] or "").strip()
            if txt:
                lines.append(texts.MSG_REVIEW_LINE.format(
                    stars=stars, text=txt, name=r["user_name"] or "?",
                    date=(r["created_at"] or "")[:10]))
            else:
                lines.append(texts.MSG_REVIEW_NO_TEXT.format(
                    stars=stars, name=r["user_name"] or "?",
                    date=(r["created_at"] or "")[:10]))
        body = "\n\n".join(lines)
    else:
        body = texts.MSG_NO_REVIEWS
    text = texts.MSG_REVIEWS_TITLE.format(name=p["name"]) + "\n\n" + body
    can_review = await db.has_purchased(user["id"], pid)
    # Edit in place; reviews come from a photo message sometimes.
    try:
        if query.message.photo:
            await query.message.delete()
            await query.message.answer(text, reply_markup=kb.reviews_kb(pid, can_review),
                                       disable_web_page_preview=True)
        else:
            await edit_text_safe(query, text, kb.reviews_kb(pid, can_review))
    except Exception:
        await query.message.answer(text, reply_markup=kb.reviews_kb(pid, can_review),
                                   disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rvl:"))
async def cb_review_start(query: types.CallbackQuery):
    pid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if not await db.has_purchased(user["id"], pid):
        await query.answer(texts.TOAST_BUY_FIRST, show_alert=True)
        return
    await query.answer()
    await edit_text_safe(query, texts.MSG_REVIEW_ASK_RATING,
                         kb.rating_picker_kb(pid))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rvr:"))
async def cb_review_rate(query: types.CallbackQuery, state: FSMContext):
    _, pid_s, stars_s = query.data.split(":")
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    try:
        pid = int(pid_s)
        stars = int(stars_s)
    except (TypeError, ValueError):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # H5: range-check the rating — crafted callbacks could persist 0 or 999999,
    # breaking the reviews screen ("⭐" * 999999 exceeds Telegram's 4096 cap).
    if not 1 <= stars <= 5:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # Re-check purchase here too: the rating button is reachable directly,
    # so a crafted callback must not inject reviews (same as rvl:).
    if not await db.has_purchased(user["id"], pid):
        await query.answer(texts.TOAST_BUY_FIRST, show_alert=True)
        return
    await query.answer()
    await state.update_data(review_pid=pid, review_rating=stars)
    await ReviewFlow.waiting_text.set()
    await query.message.answer(texts.MSG_REVIEW_ASK_TEXT,
                               reply_markup=kb.force_reply())


# H1: the "⭐ Rate Items" button (or:{oid}) on order details was dead —
# no handler matched the or: prefix. Show the order's items as rate buttons.
@dp.callback_query_handler(lambda q: q.data and q.data.startswith("or:"))
async def cb_order_rate_items(query: types.CallbackQuery):
    try:
        oid = int(query.data.split(":")[1])
    except (TypeError, ValueError, IndexError):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await query.answer()
    items = await db.get_order_items(oid)
    if not items:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup()
    for it in items:
        markup.row(InlineKeyboardButton(
            f"⭐ Rate: {it['name'][:40]}",
            callback_data=f"rv:{it['product_id']}"))
    markup.row(InlineKeyboardButton(texts.BTN_BACK,
                                    callback_data=cb("od", oid)))
    await edit_text_safe(query, "⭐ <b>Rate your items</b>\n\nPick an item to review:",
                         markup)


@dp.message_handler(state=ReviewFlow.waiting_text)
async def review_text_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    data = await state.get_data()
    pid, rating = data.get("review_pid"), data.get("review_rating")
    text = "" if (message.text or "").strip().lower() == texts.BTN_SKIP.lower() else (message.text or "")
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    if pid and rating:
        await db.add_review(user["id"], pid, rating, text)
    await state.finish()
    await message.answer(texts.TOAST_REVIEW_SAVED,
                         reply_markup=await main_reply_kb(message.from_user.id))
