"""Profile: card, wishlist, purchases, referral, redeem promo."""
import asyncio
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
        name=user["name"] or "?", tg_id=user["tg_id"], orders=orders_n,
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
    await _try_delete(message)
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_profile(message, user)


async def cmd_profile(message: types.Message, state: FSMContext):
    await state.finish()
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_profile(message, user)


@dp.callback_query_handler(text="prof")
async def cb_profile(query: types.CallbackQuery):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_profile(query, user)


@dp.callback_query_handler(text="wl")
async def cb_wishlist(query: types.CallbackQuery):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    items = await db.wishlist_list(user["id"])
    if not items:
        await edit_text_safe(query, texts.MSG_WISHLIST_EMPTY, kb.profile_kb())
    else:
        await edit_text_safe(query, texts.MSG_WISHLIST_TITLE, kb.wishlist_kb(items))


@dp.callback_query_handler(text="pur")
async def cb_purchases(query: types.CallbackQuery):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    orders = await db.list_user_orders(user["id"], 50, 0)
    items_list = await asyncio.gather(*(db.get_order_items(o["id"]) for o in orders))
    blocks = []
    for o, items in zip(orders, items_list):
        dvals = [(i["name"], i["delivered_value"]) for i in items if i["delivered_value"]]
        if dvals:
            blocks.append(texts.MSG_PURCHASE_BLOCK.format(oid=o["id"]) + "\n" +
                          "\n".join(
                              texts.MSG_PURCHASE_KEY_LINE.format(name=n, value=v)
                              for n, v in dvals))
    if not blocks:
        await edit_text_safe(query, texts.MSG_PURCHASES_EMPTY, kb.profile_kb())
    else:
        text = texts.MSG_PURCHASES_TITLE + "\n\n" + "\n\n".join(blocks[:10])
        if len(blocks) > 10:
            text += "\n\n(showing 10 of {})".format(len(blocks))
        if len(text) > 4000:
            text = text[:4000] + "..."
        await edit_text_safe(query, text, kb.profile_kb())


@dp.callback_query_handler(text="ref")
async def cb_referral(query: types.CallbackQuery):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    me = await bot.get_me()
    if not me.username:
        await edit_text_safe(query, texts.ERR_NOT_FOUND, kb.profile_kb())
        return
    link = f"https://t.me/{me.username}?start=ref_{user['ref_code']}"
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
    await query.answer()
    await CartPromo.waiting_code.set()
    await state.update_data(promo_origin="redeem")
    await query.message.answer(texts.MSG_REDEEM_ASK, reply_markup=kb.force_reply())
