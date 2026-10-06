"""Checkout: details -> payment -> confirm. Sleek 3-screen flow."""
import asyncio
import html
import logging

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import LabeledPrice, ReplyKeyboardRemove

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from payload_hooks import push_order_to_payload
from states import Checkout
from utils import fmt_money
from .common import (
    get_or_register, edit_text_safe, handle_escape,
    totals, render_lines, totals_text, product_available, stars_label,
    notify_admins, fulfill_order, maybe_credit_referral,
)

logger = logging.getLogger(__name__)

# --- double-tap guard: one placement at a time per user ----------------------
_place_locks: dict[int, asyncio.Lock] = {}


def _place_lock(user_id: int) -> asyncio.Lock:
    lock = _place_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _place_locks[user_id] = lock
    return lock


def payment_label(method: str, kind: str) -> str:
    """Human label for the chosen payment method (confirm screen)."""
    if method == "cod" and kind == "pickup":
        return texts.PAY_METHOD_PICKUP
    return texts.PAY_METHOD_LABEL.get(method, method or "—")


async def _cart_is_digital_only(user_id: int) -> bool:
    items = await db.cart_items(user_id)
    if not items:
        return False
    for it in items:
        p = await db.get_product(it["product_id"])
        if not p or p["kind"] != "digital":
            return False
    return True


async def _cart_has_digital(user_id: int) -> bool:
    """True if the cart contains any digital item. Digital keys are handed
    out at fulfillment, so any cart with digital goods must be prepaid —
    COD is only safe for physical-only carts."""
    for it in await db.cart_items(user_id):
        p = await db.get_product(it["product_id"])
        if p and p["kind"] == "digital":
            return True
    return False


async def _cod_allowed(user_id: int, data: dict) -> bool:
    """COD is only valid for physical-only carts with delivery details
    collected. Guards both the payment-method picker and order placement
    against forged callbacks."""
    if data.get("details_skipped"):
        return False
    if data.get("delivery_kind") != "delivery":
        return False
    return not await _cart_has_digital(user_id)


# ------------------------------------------------------------- details ---
def _details_snapshot(data: dict, user: dict):
    """(kind, phone, address, phone_saved, address_saved) for the details screen."""
    kind = data.get("delivery_kind") or "delivery"
    # user is sqlite3.Row: use dict-style access
    u = dict(user)
    phone = data.get("phone") or u.get("phone")
    address = data.get("address") or u.get("address")
    phone_saved = not data.get("phone") and bool(u.get("phone"))
    address_saved = not data.get("address") and bool(u.get("address"))
    return kind, phone, address, phone_saved, address_saved


def _details_text(kind, phone, address, phone_saved, address_saved) -> str:
    phone_disp = html.escape(str(phone or "—")) + (" ✓" if phone_saved and phone else "")
    if kind == "delivery":
        addr_disp = html.escape(str(address or "—")) + (" ✓" if address_saved and address else "")
        address_line = texts.MSG_CO_DETAILS_ADDRESS_LINE.format(address=addr_disp)
    else:
        address_line = ""
    saved_note = texts.MSG_CO_DETAILS_SAVED_NOTE if (phone_saved or address_saved) else ""
    return texts.MSG_CO_DETAILS.format(phone=phone_disp,
                                        address_line=address_line) + saved_note


def _details_prompt(kind, phone, address) -> str:
    need = []
    if not phone:
        need.append("📞 your phone number")
    if kind == "delivery" and not address:
        need.append("📍 your delivery address")
    if not need:
        return "✅ All set — tap Continue, or update with the buttons."
    return "Please share " + " and ".join(need) + "."


@dp.callback_query_handler(text="co", state="*")
async def start_checkout(query: types.CallbackQuery, state: FSMContext):
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    t = await totals(user["id"], state)
    if not t["items"]:
        await query.answer(texts.MSG_CART_EMPTY, show_alert=True)
        return
    for it in t["items"]:
        p = await db.get_product(it["product_id"])
        if not await product_available(p, it["qty"]):
            await query.answer(texts.ERR_OUT_OF_STOCK, show_alert=True)
            return
    # Digital-only bot: delivery details removed from checkout flow.
    # Kept as optional service elsewhere, not in main purchase flow.
    await state.update_data(delivery_kind="pickup", phone=None, address=None,
                            payment_method=None, promo_code=None,
                            details_skipped=True)
    await query.answer()
    await render_payment(query, state, user["id"])


async def cb_delivery_kind(query: types.CallbackQuery, state: FSMContext):
    kind = query.data.split(":")[1]
    if kind not in ("delivery", "pickup"):
        await query.answer(show_alert=False)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await state.update_data(delivery_kind=kind)
    if kind == "pickup":
        await state.update_data(address=None)
    await query.answer()
    await render_details(query, state, user)


async def cb_details_continue(query: types.CallbackQuery, state: FSMContext):
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    u = dict(user)
    data = await state.get_data()
    kind = data.get("delivery_kind") or "delivery"
    phone = data.get("phone") or u.get("phone")
    address = data.get("address") or u.get("address")
    if not phone:
        await query.answer("📞 Please share your phone number first.",
                           show_alert=True)
        return
    if kind == "delivery" and not address:
        await query.answer("📍 Please share your delivery address first.",
                           show_alert=True)
        return
    # Persist for next time ("use saved ✓").
    await state.update_data(phone=phone,
                            address=address if kind == "delivery" else None)
    if u.get("phone") != phone:
        await db.update_user(user["id"], phone=phone)
    if kind == "delivery" and u.get("address") != address:
        await db.update_user(user["id"], address=address)
    await query.answer()
    await _clear_details_prompt(query.message.chat.id, data.get("details_rkb_mid"))
    await render_payment(query, state, user["id"])


async def details_contact_shared(message: types.Message, state: FSMContext):
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    if message.contact.user_id != message.from_user.id:
        await message.answer(texts.MSG_INVALID_PHONE)
        return
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await db.update_user(user["id"], phone=phone)
    try:
        await message.delete()
    except Exception:
        pass
    await _refresh_details(message.chat.id, state, user)


async def details_location_shared(message: types.Message, state: FSMContext):
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    data = await state.get_data()
    if (data.get("delivery_kind") or "delivery") != "delivery":
        try:
            await message.delete()
        except Exception:
            pass
        return
    loc = message.location
    address = f"📍 {loc.latitude:.5f}, {loc.longitude:.5f}"
    await state.update_data(address=address)
    await db.update_user(user["id"], address=address)
    try:
        await message.delete()
    except Exception:
        pass
    await _refresh_details(message.chat.id, state, user)


async def details_typed(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if await handle_escape(message, state):
        await _clear_details_prompt(message.chat.id, data.get("details_rkb_mid"))
        return
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    text = (message.text or "").strip()
    if text == texts.BTN_BACK:
        await _clear_details_prompt(message.chat.id, data.get("details_rkb_mid"))
        await state.finish()
        from .cart import render_cart
        await render_cart(message, user["id"], state)
        try:
            await message.delete()
        except Exception:
            pass
        return
    if not text:
        return
    kind = data.get("delivery_kind") or "delivery"
    phone = data.get("phone") or user.get("phone")
    address = data.get("address") or user.get("address")
    # Fill the first empty field: phone, then address (delivery only).
    # The share buttons above overwrite at any time.
    if not phone:
        if len(text) < 5:
            await message.answer(texts.MSG_INVALID_PHONE)
            return
        await state.update_data(phone=text)
        await db.update_user(user["id"], phone=text)
    elif kind == "delivery" and not address:
        if len(text) < 5:
            await message.answer(texts.MSG_INVALID_ADDRESS)
            return
        await state.update_data(address=text)
        await db.update_user(user["id"], address=text)
    else:
        await message.answer("Tap 📞/📍 to update, or Continue when ready.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    await _refresh_details(message.chat.id, state, user)


# ------------------------------------------------------------- payment ---
async def render_payment(target, state: FSMContext, user_id: int):
    """Payment step: method choice only, no amounts shown (total appears on the confirm step)."""
    await Checkout.payment.set()
    import crypto_payments as cp
    t = await totals(user_id, state, with_delivery=True)
    data = await state.get_data()
    kind = data.get("delivery_kind") or "delivery"
    step = 1  # Digital-only: payment is step 1 (no details step)
    # payment_rails() returns: balance (always) -> stars -> card (if token) ->
    # crypto. The single "crypto" rail opens the crypto submenu.
    rails = await cp.payment_rails(db, t["total"])
    text = texts.MSG_CO_PAYMENT.format(step=step)
    # M7: COD makes no sense for any cart containing digital items (keys would
    # be popped at placement without payment). Hide it for digital-only AND
    # mixed carts, not just when details were skipped.
    show_cod = (kind == "delivery") and not data.get("details_skipped") \
        and not await _cart_has_digital(user_id)
    markup = kb.payment_kb(rails, cod=show_cod)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query_handler(text="co4", state=Checkout.payment)
async def cb_payment_back(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    data = await state.get_data()
    if data.get("details_skipped"):
        # Digital-only: back goes to the cart.
        await state.finish()
        from .cart import render_cart
        await render_cart(query, user["id"], state)
    else:
        # Edit in place — never orphan the payment message.
        await render_details(query, state, user)


# H2: dead "copb" back buttons on crypto invoice/deposit screens left users
# stranded mid-payment with a hanging spinner. Route back to the payment step.
@dp.callback_query_handler(text="copb", state="*")
async def cb_crypto_back(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    data = await state.get_data()
    oid = data.get("order_id")
    if not oid:
        msg = getattr(query, "message", None)
        markup = getattr(msg, "reply_markup", None) if msg else None
        for row in (getattr(markup, "inline_keyboard", None) or []):
            for btn in row:
                cb = getattr(btn, "callback_data", None)
                if cb and cb.startswith("copc:"):
                    try:
                        oid = int(cb.split(":", 1)[1])
                    except (IndexError, ValueError):
                        pass
                    break
            if oid:
                break
    if oid:
        query.data = f"copc:{oid}"
        await cb_change_payment(query, state)
        return
    if data.get("details_skipped"):
        await state.finish()
        from .cart import render_cart
        await render_cart(query, user["id"], state)
    else:
        await render_payment(query, state, user["id"])


@dp.callback_query_handler(text_startswith="cop:", state=Checkout.payment)
async def cb_payment_method(query: types.CallbackQuery, state: FSMContext):
    method = query.data.split(":")[1]
    # Crypto submenu navigation
    if method == "crypto_menu":
        await query.answer()
        await edit_text_safe(
            query, texts.MSG_CRYPTO_MENU,
            kb.crypto_menu_kb())
        return
    if method == "usdt_menu":
        await query.answer()
        await edit_text_safe(
            query, query.message.text or texts.MSG_CRYPTO_MENU,
            kb.usdt_menu_kb())
        return
    if method == "usdc_menu":
        await query.answer()
        await edit_text_safe(
            query, query.message.text or texts.MSG_CRYPTO_MENU,
            kb.usdc_menu_kb())
        return
    if method == "back_to_payment":
        await query.answer()
        user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
        await render_payment(query, state, user["id"])
        return
    if method.startswith("direct_"):
        import crypto_payments as cp
        chain = method.split("_", 1)[1]
        if (chain not in cp.CHAINS or not cp.chain_configured(chain)
                or not await db.crypto_chain_enabled(chain)):
            await query.answer(texts.MSG_CRYPTO_PROVIDER_DOWN, show_alert=True)
            return
    elif method in ("usdt_base", "usdc_base", "usdt_op", "usdc_op",
                    "usdt_polygon", "usdc_polygon"):
        import crypto_payments as cp
        if (method not in cp.CHAINS or not cp.chain_configured(method)
                or not await db.crypto_chain_enabled(method)):
            await query.answer(texts.MSG_CRYPTO_PROVIDER_DOWN, show_alert=True)
            return
    elif method == "card":
        if not config.PAYMENTS_PROVIDER_TOKEN:
            await query.answer(texts.MSG_NEED_CARD_TOKEN, show_alert=True)
            return
    elif method == "cryptobot":
        if not config.CRYPTOBOT_TOKEN:
            await query.answer(texts.MSG_NEED_CRYPTOBOT_TOKEN, show_alert=True)
            return
    elif method == "cod":
        cod_user, _ = await get_or_register(query.from_user.id,
                                            query.from_user.full_name)
        if not await _cod_allowed(cod_user["id"], await state.get_data()):
            await query.answer("🚚 Cash on delivery isn't available for this "
                               "order.", show_alert=True)
            return
    elif method == "balance":
        # Balance is always offered; insufficient funds redirect to top-up.
        bal_user, _ = await get_or_register(query.from_user.id,
                                            query.from_user.full_name)
        t = await totals(bal_user["id"], state, with_delivery=True)
        balance = await db.get_balance(bal_user["id"])
        if balance < t["total"]:
            await query.answer(texts.MSG_INSUFFICIENT_BALANCE, show_alert=True)
            await edit_text_safe(query, texts.MSG_BALANCE_TOPUP,
                                 kb.balance_topup_kb())
            return
    elif method not in ("stars",):
        await query.answer(show_alert=False)
        return
    await state.update_data(payment_method=method)
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_confirm(query, state, user["id"])


# ------------------------------------------------------------- confirm ---
def _confirm_text_and_kb(state_data: dict, t: dict):
    kind = state_data.get("delivery_kind") or "delivery"
    method = state_data.get("payment_method")
    crypto_sub = method in ("direct_btc", "direct_ton", "usdt_base", "usdt_op",
                            "usdt_polygon", "usdc_base", "usdc_op", "usdc_polygon")
    step = 3 if crypto_sub else 2
    if state_data.get("details_skipped"):
        contact_block = ""
    else:
        phone = html.escape(str(state_data.get("phone") or "—"))
        if kind == "delivery":
            address_line = texts.MSG_CO_CONFIRM_ADDRESS_LINE.format(
                address=html.escape(str(state_data.get("address") or "—")))
        else:
            address_line = texts.MSG_CO_CONFIRM_PICKUP_LINE
        contact_block = f"\U0001f4de {phone}\n{address_line}"
    text = texts.MSG_CO_CONFIRM.format(
        step=step, lines=render_lines(t["items"]), contact_block=contact_block,
        payment=payment_label(state_data.get("payment_method"), kind),
        totals=totals_text(t))
    return text, kb.confirm_kb(t["total"])


async def render_confirm(target, state: FSMContext, user_id: int):
    """Merged review & confirm screen. Promo is entered by replying."""
    await Checkout.confirm.set()
    t = await totals(user_id, state, with_delivery=True)
    text, markup = _confirm_text_and_kb(await state.get_data(), t)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
        await state.update_data(confirm_mid=target.message.message_id,
                                confirm_chat=target.message.chat.id)
    else:
        msg = await target.answer(text, reply_markup=markup, parse_mode="HTML")
        await state.update_data(confirm_mid=msg.message_id,
                                confirm_chat=msg.chat.id)


@dp.message_handler(state=Checkout.confirm)
async def confirm_promo_reply(message: types.Message, state: FSMContext):
    """A text reply on the confirm screen is treated as a promo code."""
    if await handle_escape(message, state):
        return
    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    code = (message.text or "").strip()
    if not code:
        return
    t = await totals(user["id"], state, with_delivery=True)
    ok, reason, _discount, promo = await db.validate_promo(code, user["id"],
                                                           t["subtotal"])
    if not ok:
        if reason == "used":
            await message.answer(texts.MSG_PROMO_USED)
        elif reason == "min":
            row = await db.get_promo(code)
            await message.answer(texts.MSG_PROMO_MIN.format(
                minimum=fmt_money(row["min_subtotal_cents"], config.CURRENCY)))
        else:
            await message.answer(texts.MSG_PROMO_INVALID)
        return
    await state.update_data(promo_code=promo["code"])
    try:
        await message.delete()
    except Exception:
        pass
    # Re-render the confirm screen in place with the discount applied.
    t = await totals(user["id"], state, with_delivery=True)
    text, markup = _confirm_text_and_kb(await state.get_data(), t)
    data = await state.get_data()
    try:
        await bot.edit_message_text(
            text, data.get("confirm_chat") or message.chat.id,
            data.get("confirm_mid"), reply_markup=markup, parse_mode="HTML",
            disable_web_page_preview=True)
    except Exception:
        msg = await message.answer(text, reply_markup=markup, parse_mode="HTML")
        await state.update_data(confirm_mid=msg.message_id,
                                confirm_chat=msg.chat.id)


@dp.callback_query_handler(text_startswith="coe:", state=Checkout.confirm)
async def cb_confirm_edit(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    step = query.data.split(":")[1]
    if step == "items":
        await state.finish()
        from .cart import render_cart
        await render_cart(query, user["id"], state)
    elif step == "details":
        await render_details(query, state, user)
    elif step == "payment":
        await render_payment(query, state, user["id"])


@dp.callback_query_handler(text="cob", state=Checkout.confirm)
async def cb_confirm_back(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_payment(query, state, user["id"])


# --------------------------------------------------------- place order ---
@dp.callback_query_handler(text="cok", state=Checkout.confirm)
async def cb_place_order(query: types.CallbackQuery, state: FSMContext):
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    # Double-tap guard: the check + acquire never yields, so exactly one tap wins.
    lock = _place_lock(user["id"])
    if lock.locked():
        await query.answer(texts.MSG_ALREADY_PLACING, show_alert=True)
        return
    await lock.acquire()
    try:
        await _place_order(query, state, user)
    finally:
        lock.release()


# Stateless fallback for the confirm button.  After a restart MemoryStorage
# loses all FSM state, so the state-gated handler above never matches and the
# button appears dead.  This handler is registered *after* the state-gated one,
# so the normal path still wins; it simply answers and restarts checkout.
@dp.callback_query_handler(text="cok", state="*")
async def cb_place_order_stale(query: types.CallbackQuery, state: FSMContext):
    # NOTE: no query.answer() here — start_checkout answers on every path
    # (alert on empty cart, bare answer before rendering payment).
    await start_checkout(query, state)


async def _place_order(query: types.CallbackQuery, state: FSMContext, user: dict):
    data = await state.get_data()
    kind = data.get("delivery_kind") or "delivery"
    method = data.get("payment_method")
    if not method:
        await query.answer(texts.MSG_CHOOSE_PAYMENT_FIRST, show_alert=True)
        return
    # Forged `cop:cod` callbacks must not bypass payment: COD fulfills at
    # placement, so it is only valid for physical-only carts with details.
    if method == "cod" and not await _cod_allowed(user["id"], data):
        await query.answer("🚚 Cash on delivery isn't available for this "
                           "order.", show_alert=True)
        return
    t = await totals(user["id"], state, with_delivery=True)
    if not t["items"]:
        await query.answer(texts.MSG_CART_EMPTY, show_alert=True)
        return
    for it in t["items"]:
        p = await db.get_product(it["product_id"])
        if not await product_available(p, it["qty"]):
            await query.answer(texts.ERR_OUT_OF_STOCK, show_alert=True)
            return
    oid = await db.create_order(
        user_id=user["id"], subtotal_cents=t["subtotal"],
        discount_cents=t["discount"], total_cents=t["total"],
        payment_method=method, delivery_kind=kind,
        address=data.get("address") if kind == "delivery" else None,
        phone=data.get("phone"),
        promo_code=t["promo_code"])
    # Claim the promo use only AFTER the order row exists, so a failure while
    # creating the order can no longer burn the promo with no order to show.
    # If the claim fails (max_uses lost in a race / already used), the promo
    # is dead — cancel the just-created order and re-render confirm at full
    # price instead of placing.
    if t["promo_code"]:
        promo = await db.get_promo(t["promo_code"])
        claimed = await db.record_promo_usage(promo["id"], user["id"]) if promo else False
        if not claimed:
            await db.set_order_status(oid, "cancelled")
            await state.update_data(promo_code=None)
            await query.answer(texts.MSG_PROMO_INVALID, show_alert=True)
            await render_confirm(query, state, user["id"])
            return

    for it in t["items"]:
        await db.add_order_item(oid, it["product_id"], it["name"],
                                it["qty"], it["price_cents"])
    # NOTE: stock is decremented exactly once, atomically, in
    # handlers/common.py::fulfill_order after payment. Do NOT decrement here —
    # a placement-time decrement would double-count (fulfill_order also
    # decrements) and unpaid cancelled orders never restore stock.
    await db.cart_clear(user["id"])
    await state.update_data(promo_code=None)
    await db.audit(query.from_user.id, "order_create",
                   f"order={oid} total={t['total']} method={method}")
    # Push order to the Payload CMS admin panel (best-effort, never raises).
    asyncio.create_task(asyncio.to_thread(
        push_order_to_payload,
        {"orderNumber": f"NS-{oid}", "tgUserId": str(query.from_user.id),
         "customerName": user["name"],
         "items": [{"productName": it["name"], "qty": it["qty"],
                    "priceCents": it["price_cents"]} for it in t["items"]],
         "totalCents": t["total"], "currency": config.CURRENCY,
         "paymentMethod": ("pickup" if (method == "cod" and kind == "pickup")
                           else method),
         "status": "pending",
         "rawPayload": {"bot_order_id": oid, "delivery_kind": kind,
                        "address": data.get("address"),
                        "phone": data.get("phone")}}))
    await query.answer()

    # Fully discounted: nothing to charge — fulfill as a free order.
    if t["total"] <= 0:
        ok, note = await fulfill_order(oid)
        if ok:
            await db.set_order_status(oid, "confirmed")
            await db.audit(user["id"], "order_paid",
                           f"order={oid} method=free total=0")
        # Free physical orders still need admin fulfillment/shipping.
        if not data.get("details_skipped"):
            await notify_admins(
                texts.MSG_COD_ADMIN.format(
                    kind="pickup" if kind == "pickup" else "free",
                    oid=oid, lines=render_lines(t["items"]),
                    name=user["name"], tg_id=user["tg_id"],
                    phone=data.get("phone") or "—",
                    address=(data.get("address") if kind == "delivery" else None) or "—",
                    total=fmt_money(t["total"], config.CURRENCY)),
                min_bit=config.PERM_ORDERS,
                reply_markup=kb.admin_order_detail_kb(oid, "pending"))
        await state.finish()
        values_block = ""
        for it in await db.get_order_items(oid):
            # C5: column is delivered_value, not value (aiosqlite.Row raises
            # on unknown keys — this crashed every fully-discounted order).
            if it["delivered_value"]:
                values_block += (f"\n\n\U0001f4e6 <b>{it['name']}</b>\n"
                                 f"<code>{it['delivered_value']}</code>")
        await edit_text_safe(
            query,
            texts.MSG_FREE_ORDER_PLACED.format(oid=oid, fulfillment=values_block)
            if ok else texts.MSG_FULFILL_FAIL.format(note=note),
            kb.order_success_kb(oid))
        return

    if method == "cod":
        ok, note = await fulfill_order(oid)
        if ok:
            await db.set_order_status(oid, "confirmed")
        admin_text = texts.MSG_COD_ADMIN.format(
            kind="pickup" if kind == "pickup" else "COD",
            oid=oid, lines=render_lines(t["items"]),
            name=user["name"], tg_id=user["tg_id"],
            phone=data.get("phone") or "—",
            address=(data.get("address") if kind == "delivery" else None) or "—",
            total=fmt_money(t["total"], config.CURRENCY))
        if not ok:
            admin_text += "\n\n" + texts.MSG_FULFILL_FAIL.format(note=note)
        await notify_admins(
            admin_text,
            min_bit=config.PERM_ORDERS,
            reply_markup=kb.admin_order_detail_kb(oid, "pending"))
        await state.finish()
        await edit_text_safe(
            query,
            texts.MSG_COD_PLACED.format(
                oid=oid, total=fmt_money(t["total"], config.CURRENCY),
                method="pay on pickup" if kind == "pickup"
                else "pay the courier on delivery") if ok
            else texts.MSG_FULFILL_FAIL.format(note=note),
            kb.order_success_kb(oid))
        return

    if method == "balance":
        # Deduct from prepaid balance and fulfill immediately
        new_bal = await db.deduct_balance(user["id"], t["total"], order_id=oid)
        if new_bal is None:
            await db.set_order_status(oid, "cancelled")
            await db.release_order_promo(oid)  # don't burn promo on failed balance
            await query.answer(texts.MSG_BALANCE_INSUFFICIENT, show_alert=True)
            await render_confirm(query, state, user["id"])
            return
        ok, note = await fulfill_order(oid)
        if ok:
            await db.set_order_status(oid, "confirmed")
            await db.record_payment(
                provider="balance", external_id=f"bal_{oid}_{user['id']}",
                user_id=user["id"], order_id=oid,
                amount_cents=t["total"], currency=config.CURRENCY, status="paid")
            await db.audit(user["tg_id"], "balance_purchase",
                           f"order={oid} total={t['total']} new_bal={new_bal}")
        else:
            # H17: fulfillment failed after deduction — refund and leave a ledger trail
            await db.add_balance(user["id"], t["total"], tx_type="refund", order_id=oid)
            await db.record_payment(
                provider="balance", external_id=f"bal_{oid}_{user['id']}",
                user_id=user["id"], order_id=oid,
                amount_cents=t["total"], currency=config.CURRENCY, status="refunded")
            await db.audit(user["tg_id"], "balance_refund_fulfill_fail",
                           f"order={oid} total={t['total']} note={note}")
        await state.finish()
        values_block = ""
        for it in await db.get_order_items(oid):
            if it["delivered_value"]:
                values_block += (f"\n\n\U0001f4e6 <b>{it['name']}</b>\n"
                                 f"<code>{it['delivered_value']}</code>")
        await edit_text_safe(
            query,
            texts.MSG_BALANCE_ORDER_PLACED.format(
                oid=oid, fulfillment=values_block,
                balance=fmt_money(new_bal, config.CURRENCY))
            if ok else texts.MSG_FULFILL_FAIL.format(note=note),
            kb.order_success_kb(oid))
        return

    # CryptoBot rail: invoice via Crypto Pay API; recovery poller finalizes.
    if method == "cryptobot":
        from .crypto import start_cryptobot_payment
        await start_cryptobot_payment(query, state, user, oid, t["total"])
        return

    # Direct crypto: fresh address per order, watcher detects the deposit.
    # (Stablecoin methods like usdt_base are direct-crypto too — they just
    # don't carry the direct_ prefix.)
    if method.startswith("direct_") or method in (
            "usdt_base", "usdc_base", "usdt_op", "usdc_op",
            "usdt_polygon", "usdc_polygon"):
        from .crypto import start_direct_deposit
        chain = method.split("_", 1)[1] if method.startswith("direct_") else method
        await start_direct_deposit(query, state, user, oid, t["total"], chain)
        return

    # Unknown method: fail loudly instead of silently sending a card invoice.
    if method not in ("card", "stars"):
        logger.error("unknown payment method %r for order %s", method, oid)
        await query.answer(texts.MSG_CRYPTO_PROVIDER_DOWN, show_alert=True)
        return

    # Card / Stars: send invoice, fulfillment happens on successful_payment.
    prices = [LabeledPrice(f"{it['name'][:32]} x{it['qty']}",
                           it["price_cents"] * it["qty"]) for it in t["items"]]
    if t["discount"]:
        # Telegram rejects negative LabeledPrice amounts; apply the discount
        # by reducing the item lines instead of adding a negative one.
        discounted = max(0, t["subtotal"] - t["discount"])
        remaining = discounted
        prices = []
        last = len(t["items"]) - 1
        for i, it in enumerate(t["items"]):
            if i == last:
                amount = remaining
            else:
                amount = (it["price_cents"] * it["qty"] * discounted
                          // t["subtotal"]) if t["subtotal"] else 0
            remaining -= amount
            if amount > 0:
                prices.append(LabeledPrice(
                    f"{it['name'][:32]} x{it['qty']}", amount))
    if t["delivery_fee"]:
        prices.append(LabeledPrice("Delivery", t["delivery_fee"]))
    title = texts.MSG_INVOICE_TITLE.format(oid=oid)
    if method == "stars":
        stars_n = stars_label(t["total"])
        await bot.send_invoice(
            query.message.chat.id, title, texts.MSG_INVOICE_DESC,
            payload=f"order:{oid}", provider_token="",
            currency="XTR", prices=[LabeledPrice(title[:32], stars_n)])
    else:
        await bot.send_invoice(
            query.message.chat.id, title, texts.MSG_INVOICE_DESC,
            payload=f"order:{oid}",
            provider_token=config.PAYMENTS_PROVIDER_TOKEN,
            currency=config.CURRENCY, prices=prices)
    await state.finish()
    await edit_text_safe(query, texts.MSG_PAY_WAITING, kb.waiting_kb(oid))


@dp.callback_query_handler(text_startswith="copc:")
async def cb_change_payment(query: types.CallbackQuery, state: FSMContext):
    """From the payment-waiting screen: cancel the still-pending order, restore
    its items to the cart, and return to the payment step."""
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    try:
        oid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer(texts.MSG_ORDER_NOT_FOUND, show_alert=True)
        return
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.MSG_ORDER_NOT_FOUND, show_alert=True)
        return
    # Atomic conditional cancel: only succeeds if still pending, so a
    # concurrent payment completion can't be overwritten.
    if not await db.set_order_status(oid, "cancelled", only_if_status="pending"):
        await query.answer(texts.MSG_ORDER_ALREADY_PAID, show_alert=True)
        return
    await db.release_order_promo(oid)  # M2: don't burn promo on unpaid cancel
    await db.audit(user["id"], "order_cancel_payment_change",
                   f"order={oid} method={order['payment_method']}")
    restored = 0
    digital_only = True
    for it in await db.get_order_items(oid):
        p = await db.get_product(it["product_id"])
        if not p or not p["is_active"]:
            digital_only = False
            continue
        if p["kind"] != "digital":
            digital_only = False
        await db.cart_add(user["id"], it["product_id"], it["qty"])
        restored += 1
    await query.answer()
    if not restored:
        await state.finish()
        from .cart import render_cart
        await render_cart(query, user["id"], state)
        return
    # Re-enter checkout at the payment step with the order's details.
    # NOTE: a consumed promo stays consumed (one use per user); the new order
    # is placed at full price.
    await state.update_data(
        delivery_kind=order["delivery_kind"], phone=order["phone"],
        address=order["address"], payment_method=None, promo_code=None,
        details_skipped=digital_only)
    await render_payment(query, state, user["id"])
