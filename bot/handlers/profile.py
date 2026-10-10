"""Profile: card, wishlist, purchases, referral, redeem promo."""
import asyncio
import html
from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from states import CartPromo
from utils import fmt_money
from .common import (
    get_or_register, edit_text_safe,
)


async def _try_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


async def render_profile(target, user):
    orders_n = await db.count_user_orders(user["id"])
    spent = await db.user_spent(user["id"])
    earned = await db.referral_earnings_total(user["id"])
    balance = await db.get_balance(user["id"])
    text = texts.MSG_PROFILE.format(
        # P1-4: Escape user-controlled name to prevent HTML injection.
        name=html.escape(user["name"] or "?"), tg_id=user["tg_id"], orders=orders_n,
        spent=fmt_money(spent, config.CURRENCY),
        earnings=fmt_money(earned, config.CURRENCY),
        balance=fmt_money(balance, config.CURRENCY))
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, kb.profile_kb())
    else:
        await target.answer(text, reply_markup=kb.profile_kb(),
                            disable_web_page_preview=True)


@dp.message_handler(text=texts.BTN_PROFILE)
async def nav_profile(message: types.Message, state: FSMContext):
    await state.finish()
    if message.chat.type != "private":
        await message.answer("Your profile is private — please open me in a private chat.")
        return
    await _try_delete(message)
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_profile(message, user)


async def cmd_profile(message: types.Message, state: FSMContext):
    await state.finish()
    if message.chat.type != "private":
        await message.answer("Your profile is private — please open me in a private chat.")
        return
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_profile(message, user)


@dp.callback_query_handler(text="prof")
async def cb_profile(query: types.CallbackQuery):
    await query.answer()
    # Fail closed: refuse if there's no message context (e.g. inline mode).
    chat_type = query.message.chat.type if query.message else None
    if chat_type != "private":
        await query.answer(
            "Your profile is private — please open me in a private chat.",
            show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_profile(query, user)


@dp.callback_query_handler(text="wl")
async def cb_wishlist(query: types.CallbackQuery):
    await query.answer()
    # Wishlist contents are personal; don't render them in groups.
    chat_type = query.message.chat.type if query.message else None
    if chat_type != "private":
        await query.answer(
            "Your wishlist is private — please open me in a private chat.",
            show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    items = await db.wishlist_list(user["id"])
    if not items:
        await edit_text_safe(query, texts.MSG_WISHLIST_EMPTY, kb.profile_kb())
    else:
        await edit_text_safe(query, texts.MSG_WISHLIST_TITLE, kb.wishlist_kb(items))


@dp.callback_query_handler(text="pur")
async def cb_purchases(query: types.CallbackQuery):
    await query.answer()
    # Never render delivered keys outside a private chat: in a group,
    # anyone present could read and steal the user's license keys.
    # Fail closed: if there's no message context (e.g. inline), refuse.
    chat_type = query.message.chat.type if query.message else None
    if chat_type != "private":
        await query.answer(
            "Your purchases contain secret keys — please open me in a private chat to view them.",
            show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    # P0-1: Paginate instead of hard-capping at 50 orders.
    try:
        page = int(query.data.split(":")[1] if ":" in query.data else 0)
    except (ValueError, IndexError):
        page = 0
    PAGE_SIZE = 10
    orders = await db.list_user_orders(user["id"], PAGE_SIZE + 1, page * PAGE_SIZE)
    has_more = len(orders) > PAGE_SIZE
    orders = orders[:PAGE_SIZE]
    # P1-8: return_exceptions=True — one DB hiccup must not hide all keys.
    items_list = await asyncio.gather(
        *(db.get_order_items(o["id"]) for o in orders),
        return_exceptions=True,
    )
    # Filter out failed fetches, log them
    filtered = []
    for o, items in zip(orders, items_list):
        if isinstance(items, Exception):
            import logging
            logging.getLogger(__name__).warning(
                "Failed to fetch items for order %s: %s", o["id"], items)
            continue
        filtered.append((o, items))
    orders, items_list = zip(*filtered) if filtered else ([], [])
    blocks = []
    for o, items in zip(orders, items_list):
        dvals = [(i["name"], i["delivered_value"]) for i in items if i["delivered_value"]]
        # P0-2: Always show the order, even if nothing delivered yet.
        if dvals:
            # P1-5: Escape key values — HTML metachars would break rendering.
            import html as _html
            blocks.append(texts.MSG_PURCHASE_BLOCK.format(oid=o["id"]) + "\n" +
                          "\n".join(
                              texts.MSG_PURCHASE_KEY_LINE.format(
                                  name=_html.escape(str(n)),
                                  value=_html.escape(str(v)))
                              for n, v in dvals))
        else:
            blocks.append(texts.MSG_PURCHASE_BLOCK.format(oid=o["id"]) + "\n" +
                          "\u23f3 Awaiting delivery \u2014 contact support if this persists.")
    if not blocks and page == 0:
        await edit_text_safe(query, texts.MSG_PURCHASES_EMPTY, kb.profile_kb())
    else:
        text = texts.MSG_PURCHASES_TITLE + "\n\n" + "\n\n".join(blocks)
        if has_more:
            text += f"\n\n(Page {page + 1} \u2014 more orders available)"
        elif page > 0:
            text += f"\n(Page {page + 1})"
        await edit_text_safe(query, text, kb.profile_kb())


@dp.callback_query_handler(text="ref")
async def cb_referral(query: types.CallbackQuery):
    # P1-1: Fail-closed chat guard — referral links contain keys, private only.
    if query.message.chat.type != "private":
        await query.answer(
            "Referral links contain sensitive info — open me in a private chat.",
            show_alert=True)
        return
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    me = await bot.get_me()
    if not me.username:
        await edit_text_safe(query, texts.ERR_NOT_FOUND, kb.profile_kb())
        return
    # P1-6: ref_code may be NULL — do not emit a live ?start=ref_None link.
    ref_code = user.get("ref_code")
    if not ref_code:
        await edit_text_safe(
            query, "⚠️ Referral code not available. Contact support.",
            kb.profile_kb())
        return
    link = f"https://t.me/{me.username}?start=ref_{ref_code}"
    percent = await db.referral_percent()
    count = await db.referral_count(user["id"])
    earned = await db.referral_earnings_total(user["id"])
    await edit_text_safe(
        query,
        texts.MSG_REFERRAL.format(percent=percent, link=link, count=count,
                                  earned=fmt_money(earned, config.CURRENCY)),
        kb.profile_kb())


@dp.callback_query_handler(text="pm3")
async def cb_redeem(query: types.CallbackQuery, state: FSMContext):
    # P1-1: Fail-closed chat guard — promo codes are sensitive, private only.
    # P1-2: Single query.answer() — guard returns before the main answer.
    if query.message.chat.type != "private":
        await query.answer(
            "Promo codes are sensitive — open me in a private chat.",
            show_alert=True)
        return
    await query.answer()
    await CartPromo.waiting_code.set()
    await state.update_data(promo_origin="redeem")
    await query.message.answer(texts.MSG_REDEEM_ASK, reply_markup=kb.force_reply())
