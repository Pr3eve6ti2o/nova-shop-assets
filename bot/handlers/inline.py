"""Inline-mode product sharing (port plan 8.4) — PORTED from
DoktorShift/telegramshop `telegram.py::handle_inline_query`, adapted
to aiogram with minor changes: product photos here are Telegram
file_ids (CachedPhoto results) rather than URLs, and the deep link
uses this bot's existing `p_<id>` start payload instead of the
source's `product_<id>`.

Mechanics kept from the source: substring match over active
products, 20-result cap, bold-title + price caption, and a single
"🛍 View Product" URL button into the bot. Requires inline mode to
be enabled in BotFather (/setinline) — the doctor (7.3) reports it.
"""
from aiogram import types

import config
from loader import bot, db, dp
from utils import fmt_money
from utils import h as _h

_bot_username = None


async def _username() -> str:
    global _bot_username
    if _bot_username is None:
        try:
            me = await bot.get_me()
            _bot_username = me.username or ""
        except Exception:
            _bot_username = ""
    return _bot_username


@dp.inline_handler()
async def inline_search(inline_query: types.InlineQuery):
    query = (inline_query.query or "").strip()
    products = await db.search_products(query, 20, 0)
    username = await _username()
    results = []
    for p in products:
        price = fmt_money(p["price_cents"], config.CURRENCY)
        caption = f"<b>{_h(p['name'])}</b>\n{price}"
        markup = None
        if username:
            markup = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "🛍 View Product",
                    url=f"https://t.me/{username}?start=p_{p['id']}"))
        if p["photo_file_id"]:
            results.append(types.InlineQueryResultCachedPhoto(
                id=str(p["id"]),
                photo_file_id=p["photo_file_id"],
                caption=caption, parse_mode="HTML",
                reply_markup=markup))
        else:
            results.append(types.InlineQueryResultArticle(
                id=str(p["id"]),
                title=p["name"],
                description=price,
                input_message_content=types.InputTextMessageContent(
                    caption, parse_mode="HTML"),
                reply_markup=markup))
    await inline_query.answer(results, cache_time=30, is_personal=False)
