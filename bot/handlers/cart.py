"""Cart: view, steppers, promo, clear-confirm."""
import html

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.utils.exceptions import TelegramAPIError

import config
import keyboards as kb
import texts
from loader import db, dp
from states import CartPromo
from utils import fmt_money, utcnow_iso
from .common import (
    get_or_register, main_reply_kb, edit_text_safe, handle_escape,
    totals, render_lines, totals_text, product_available,
)


async def render_cart(target, user_id: int, state: FSMContext, dropped: list = None):
    items = await db.cart_items(user_id)
    # Stock re-check: drop unavailable items.
    dropped = list(dropped or [])
    for it in list(items):
        p = await db.get_product(it["product_id"])
        if not await product_available(p, it["qty"]):
            await db.cart_remove(user_id, it["product_id"])
            dropped.append(it["name"])
            items = [i for i in items if i["product_id"] != it["product_id"]]
    t = await totals(user_id, state)
    if not t["items"]:
        text = texts.MSG_CART_EMPTY
        markup = kb.cart_empty_kb()
    else:
        text = texts.MSG_CART_TITLE + "\n\n" + render_lines(t["items"])
        if t["promo_code"]:
            desc = f"-{fmt_money(t['discount'], config.CURRENCY)}"
            text += texts.MSG_CART_PROMO_LINE.format(code=t["promo_code"], discount=desc)
        text += texts.MSG_CART_TOTAL.format(total=fmt_money(t["total"], config.CURRENCY))
        promo_desc = f"-{fmt_money(t['discount'], config.CURRENCY)}" if t["promo_code"] else ""
        markup = kb.cart_kb(t["items"], t["promo_code"], promo_desc, t["total"])
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)
    if dropped:
        # Opus: escape product names — unescaped names in HTML parse mode
        # allow injection.
        toast = texts.MSG_CART_DROPPED.format(
            names=", ".join(html.escape(n) for n in dropped))
        if isinstance(target, types.CallbackQuery):
            await target.answer(toast, show_alert=True)
        else:
            await target.answer(toast)


@dp.message_handler(lambda m: (m.text or "") == texts.BTN_CART, state="*")
async def nav_cart(message: types.Message, state: FSMContext):
    # Opus: was startswith() — a support question beginning with the cart
    # label was treated as navigation and the user's message got deleted.
    if message.chat.type != "private":
        await message.answer("Your cart is private — please open me in a private chat.")
        return
    try:
        await message.delete()
    except TelegramAPIError:
        pass
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_cart(message, user["id"], state)


async def cmd_cart(message: types.Message, state: FSMContext):
    # Opus: nav_cart has a private-chat guard but cmd_cart did not —
    # cart contents could leak in a group chat.
    if message.chat.type != "private":
        await message.answer("Your cart is private — please open me in a private chat.")
        return
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_cart(message, user["id"], state)


@dp.callback_query_handler(text="cart", state="*")
async def cb_cart(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    # H4: clear the details share-contact keyboard if we're leaving it behind.
    data = await state.get_data()
    promo_code = data.get("promo_code")
    if data.get("details_rkb_mid"):
        from .checkout import _clear_details_prompt
        await _clear_details_prompt(query.message.chat.id, data.get("details_rkb_mid"))
    await state.finish()  # leaving any wizard (e.g. back from checkout review)
    if promo_code:
        await state.update_data(promo_code=promo_code)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_cart(query, user["id"], state)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cq:"), state="*")
async def cb_cart_qty(query: types.CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, pid_s, delta_s = parts
    if delta_s not in {"+1", "-1"}:
        await query.answer()
        return
    try:
        pid = int(pid_s)
    except ValueError:
        await query.answer()
        return
    delta = 1 if delta_s == "+1" else -1
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    # Opus: check stock BEFORE adjusting — the old rollback logic was wrong
    # when cart_adjust clamped the quantity (new_qty reflected the clamp,
    # not the requested delta, so -delta rollback landed below the cap).
    # Also enforces an upper bound so totals cannot grow unbounded.
    MAX_QTY = 99
    p = await db.get_product(pid)
    items = await db.cart_items(user["id"])
    current = next((i["qty"] for i in items if i["product_id"] == pid), 0)
    new_qty = current + delta
    if new_qty > MAX_QTY:
        # Opus: upper bound — silently ignore, matching shop stepper behaviour.
        await query.answer()
        return
    if new_qty > 0 and not await product_available(p, new_qty):
        await query.answer(texts.ERR_OUT_OF_STOCK, show_alert=True)
        return
    # Atomic adjust prevents read-modify-write race on rapid taps
    new_qty = await db.cart_adjust(user["id"], pid, delta)
    if new_qty <= 0:
        await query.answer(texts.TOAST_REMOVED)
    else:
        await query.answer()
    await render_cart(query, user["id"], state)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("crm:"), state="*")
async def cb_cart_remove(query: types.CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    if len(parts) != 2:
        await query.answer()
        return
    try:
        pid = int(parts[1])
    except ValueError:
        await query.answer()
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await db.cart_remove(user["id"], pid)
    await query.answer(texts.TOAST_REMOVED)
    await render_cart(query, user["id"], state)


@dp.callback_query_handler(text="cc", state="*")
async def cb_clear_ask(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    n = await db.cart_count(user["id"])
    await edit_text_safe(query, texts.MSG_CLEAR_CONFIRM.format(n=n),
                         kb.clear_confirm_kb(n))


@dp.callback_query_handler(text="ccy", state="*")
async def cb_clear_yes(query: types.CallbackQuery, state: FSMContext):
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await db.cart_clear(user["id"])
    await state.update_data(promo_code=None)
    await query.answer(texts.MSG_CART_CLEARED)
    await render_cart(query, user["id"], state)


@dp.callback_query_handler(text="pm", state="*")
async def cb_promo_ask(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await CartPromo.waiting_code.set()
    await state.update_data(promo_origin="cart")
    await query.message.answer(texts.MSG_PROMO_ASK, reply_markup=kb.force_reply())


@dp.message_handler(state=CartPromo.waiting_code)
async def promo_code_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    # Opus: validate BEFORE truncating — truncating first lets a long code
    # map onto a shorter valid-looking one.
    code = (message.text or "").strip()
    if len(code) > 32:
        await message.answer(texts.MSG_PROMO_INVALID,
                             reply_markup=await main_reply_kb(message.from_user.id))
        await state.finish()
        return
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)

    # Gift cards share this door: a NOVA-… code is a gift card, not a promo.
    # Look the card up first — an unknown NOVA- code falls through to the
    # promo validation below, so its error stays the familiar one.
    if code.upper().startswith("NOVA-"):
        card = await db.giftcard_get(code)
        if card is not None:
            ok, result = await db.giftcard_redeem(code, user["id"])
            await state.finish()
            if not ok:
                errors = {
                    "not_found": texts.MSG_GIFTCARD_ERR_NOT_FOUND,
                    "redeemed": texts.MSG_GIFTCARD_ERR_REDEEMED,
                    "revoked": texts.MSG_GIFTCARD_ERR_REVOKED,
                    "expired": texts.MSG_GIFTCARD_ERR_EXPIRED,
                }
                await message.answer(
                    errors.get(result, texts.ERR_GENERIC),
                    reply_markup=await main_reply_kb(message.from_user.id))
                return
            await message.answer(
                texts.MSG_GIFTCARD_OK.format(
                    amount=fmt_money(result["amount_cents"], config.CURRENCY),
                    balance=fmt_money(result["balance_cents"],
                                      config.CURRENCY)),
                reply_markup=await main_reply_kb(message.from_user.id))
            return

    data = await state.get_data()
    origin = data.get("promo_origin", "cart")

    if origin == "redeem":
        # Opus: redeem path must run the FULL promo validation (usage limits,
        # per-user usage), not just is_active + expiry — otherwise a code
        # accepted here can fail or misbehave at checkout.
        ok, reason, _discount, promo = await db.validate_promo(
            code, user["id"], 0, items=await db.cart_items(user["id"]))
        await state.finish()
        if not ok:
            await message.answer(texts.MSG_PROMO_INVALID,
                                 reply_markup=await main_reply_kb(message.from_user.id))
            return
        await state.update_data(promo_code=promo["code"])
        await message.answer(texts.MSG_REDEEM_SAVED.format(code=promo["code"]),
                             reply_markup=await main_reply_kb(message.from_user.id))
        return

    t = await totals(user["id"], state)
    if not t["items"]:
        await state.finish()
        await message.answer(texts.MSG_CART_EMPTY,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    ok, reason, discount, promo = await db.validate_promo(code, user["id"], t["subtotal"], items=t["items"])
    await state.finish()
    if not ok:
        msg = texts.MSG_PROMO_USED if reason == "used" else texts.MSG_PROMO_INVALID
        await message.answer(msg, reply_markup=await main_reply_kb(message.from_user.id))
        return
    await state.update_data(promo_code=promo["code"])
    desc = (f"{promo['value']}% off" if promo["kind"] == "percent"
            else f"-{fmt_money(discount, config.CURRENCY)}")
    await message.answer(
        texts.TOAST_PROMO_APPLIED.format(code=promo["code"], desc=desc),
        reply_markup=await main_reply_kb(message.from_user.id))
    # Re-render the cart as a fresh message. (Checkout promo is entered by
    # replying on the confirm screen, not via this state.)
    await render_cart(message, user["id"], state)


@dp.callback_query_handler(text="px", state="*")
async def cb_promo_remove(query: types.CallbackQuery, state: FSMContext):
    await state.update_data(promo_code=None)
    await query.answer(texts.TOAST_PROMO_REMOVED)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_cart(query, user["id"], state)
