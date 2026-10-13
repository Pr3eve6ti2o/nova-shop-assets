"""Product reviews (port plan 5.1 — RESTORED).

The data layer (reviews table, add/list, denormalised product
aggregates), the texts, reviews_kb, the ReviewFlow state, and the
callback scheme (rv / rvl / rvr, documented in keyboards.py) all
survived in the codebase; only these handlers were missing. Rebuilt
to that spec: anyone can read reviews; only customers who bought the
product can write one (re-posting replaces, per the DB upsert).
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import keyboards as kb
import texts
from loader import bot, db, dp
from states import ReviewFlow
from utils import h as _h
from .common import get_or_register, edit_text_safe, handle_escape


async def _can_review(user_id: int, pid: int) -> bool:
    bought = await db.user_purchased_products(user_id)
    return any(p["id"] == pid for p in bought)


def _stars(n: int) -> str:
    return "⭐" * max(1, min(5, int(n)))


async def _render_reviews(target, pid: int, user):
    p = await db.get_product(pid)
    if not p:
        if isinstance(target, types.CallbackQuery):
            await target.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    rows = await db.list_reviews(pid, limit=10)
    lines = [texts.MSG_REVIEWS_TITLE.format(name=_h(p["name"])), ""]
    if rows:
        for r in rows:
            date = (r["created_at"] or "")[:10]
            if (r["text"] or "").strip():
                lines.append(texts.MSG_REVIEW_LINE.format(
                    stars=_stars(r["rating"]), text=_h(r["text"]),
                    name=_h(r["user_name"] or "Customer"), date=date))
            else:
                lines.append(texts.MSG_REVIEW_NO_TEXT.format(
                    stars=_stars(r["rating"]),
                    name=_h(r["user_name"] or "Customer"), date=date))
    else:
        lines.append(texts.MSG_NO_REVIEWS)
    markup = kb.reviews_kb(pid, await _can_review(user["id"], pid))
    text = "\n\n".join(lines)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup,
                            disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rv:"), state="*")
async def cb_reviews(query: types.CallbackQuery):
    try:
        pid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await query.answer()
    user, _ = await get_or_register(query.from_user.id,
                                    query.from_user.full_name)
    await _render_reviews(query, pid, user)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rvl:"), state="*")
async def cb_review_leave(query: types.CallbackQuery, state: FSMContext):
    try:
        pid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    user, _ = await get_or_register(query.from_user.id,
                                    query.from_user.full_name)
    if not await _can_review(user["id"], pid):
        return await query.answer(
            "Only customers who bought this can review it.",
            show_alert=True)
    await query.answer()
    markup = InlineKeyboardMarkup(row_width=5)
    markup.row(*[InlineKeyboardButton(
        "⭐" * n, callback_data=f"rvr:{pid}:{n}") for n in range(1, 6)])
    markup.add(InlineKeyboardButton(texts.BTN_BACK,
                                    callback_data=f"rv:{pid}"))
    await edit_text_safe(query, texts.MSG_REVIEW_ASK_RATING, markup)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rvr:"), state="*")
async def cb_review_rate(query: types.CallbackQuery, state: FSMContext):
    try:
        _, pid_s, stars_s = query.data.split(":")
        pid, stars = int(pid_s), int(stars_s)
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    if not 1 <= stars <= 5:
        return await query.answer(texts.ERR_GENERIC, show_alert=True)
    user, _ = await get_or_register(query.from_user.id,
                                    query.from_user.full_name)
    if not await _can_review(user["id"], pid):
        return await query.answer(
            "Only customers who bought this can review it.",
            show_alert=True)
    await query.answer()
    await ReviewFlow.waiting_text.set()
    await state.update_data(review_pid=pid, review_rating=stars)
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton(
        "Skip ⏭", callback_data=f"rvs:{pid}"))
    await edit_text_safe(query, texts.MSG_REVIEW_ASK_TEXT, markup)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rvs:"),
                           state=ReviewFlow.waiting_text)
async def cb_review_skip(query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.finish()
    pid, stars = data.get("review_pid"), data.get("review_rating")
    user, _ = await get_or_register(query.from_user.id,
                                    query.from_user.full_name)
    if pid and stars:
        await db.add_review(user["id"], int(pid), int(stars), "")
        await query.answer(texts.TOAST_REVIEW_SAVED)
    await _render_reviews(query, int(pid), user)


@dp.message_handler(state=ReviewFlow.waiting_text)
async def msg_review_text(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    data = await state.get_data()
    pid, stars = data.get("review_pid"), data.get("review_rating")
    await state.finish()
    if not pid or not stars:
        return await message.answer(texts.ERR_GENERIC)
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    await db.add_review(user["id"], int(pid), int(stars),
                        (message.text or "").strip()[:500])
    await message.answer(texts.TOAST_REVIEW_SAVED)
    await _render_reviews(message, int(pid), user)
