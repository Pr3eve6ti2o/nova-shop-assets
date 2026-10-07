"""Mini App bridge: handles WebApp sendData payloads.

The static Mini App (miniapp/) sends {items: [{id, qty}], promo} via
Telegram.WebApp.sendData(). Everything is re-validated server-side:
unknown ids, inactive products, absurd quantities are rejected, and prices
always come from the DB — never from the payload.
"""
import json
import logging
import math

from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import db, dp
from utils import fmt_money
from .checkout import _cart_is_digital_only, render_payment
from .common import (get_or_register, main_reply_kb, product_available,
                     render_lines, totals)

logger = logging.getLogger(__name__)

MAX_ITEMS = 50


async def find_tonconnect_tx(merchant: str, sender: str, amount_nano: int,
                             claim_code: str = None):
    """Find a matching TON tx: from sender, >= amount, within 15 min.

    When claim_code is given, the tx memo must equal it exactly (C3 wallet-
    ownership binding). Shared by the fast path (handle_tonconnect_paid) and
    the slow path (crypto watcher sweep of tonconnect_pending). Returns the
    tx dict or None.
    """
    import time
    import crypto_payments as cp
    txs = await cp.fetch_ton_txs(merchant)
    # SECURITY (audit C3/M6): match on sender + amount + recency.
    now = int(time.time())
    for tx in txs:
        if not tx.get("source") or tx["source"] != sender:
            continue
        try:
            base = int(tx.get("base", 0))
        except (TypeError, ValueError):
            continue
        if base < amount_nano:
            continue
        utime = tx.get("utime") or 0
        if not utime or (now - utime) > 15 * 60:
            continue
        txid = str(tx.get("txid") or "")
        if not txid:
            continue
        # Skip txs already claimed (by anyone) — prevents double-matching.
        existing = await db.get_payment_by_external_id("tonconnect", txid)
        if existing:
            continue
        # C3: claim-code binding. The tx memo must equal the claimant's
        # per-user code — only the wallet owner could have put it there.
        # Fail closed: no match, no attribution.
        if claim_code and str(tx.get("memo") or "") != claim_code:
            continue
        return tx
    return None


async def create_tonconnect_order(user: dict, sender: str,
                                  clean: list, promo_code: str, matched: dict):
    """Create + fulfill a TON Connect order. Returns (order_id, ok).

    Shared by the fast path and the watcher slow path. Idempotent on the
    txid via record_payment's UNIQUE(provider, external_id).
    """
    # SECURITY: bind the claim to the paying user. If this txid was already
    # recorded under a different user, refuse (front-running attempt).
    txid = str(matched.get("txid") or "")
    if txid:
        existing = await db.get_payment_by_external_id("tonconnect", txid)
        if existing and existing["user_id"] != user["id"]:
            logger.warning("tonconnect order creation blocked: txid=%s existing_user=%s claiming_user=%s",
                           txid, existing["user_id"], user["id"])
            from handlers.common import notify_admins
            await notify_admins(f"⚠️ TON Connect claim blocked: txid {txid} already claimed by user {existing['user_id']}, attempted by user {user['id']}")
            return None, False
    subtotal = sum(it["qty"] * it["price"] for it in clean)
    discount_cents = 0
    promo_row = None
    if promo_code:
        ok_promo, _, promo_discount, promo_row = await db.validate_promo(
            promo_code, user["id"], subtotal)
        if ok_promo:
            discount_cents = promo_discount
        else:
            promo_code = None
            promo_row = None
    total = subtotal - discount_cents
    # SECURITY (audit C3): verify the on-chain tx covers the server-side total.
    import crypto_payments as cp
    rates = await cp.get_rates()
    ton_usd = rates.get("ton")
    if not ton_usd or ton_usd <= 0:
        # Fail closed: cannot verify amount without a rate.
        return None, False
    expected_nano = math.ceil(total / 100 / ton_usd * 1e9)
    # C4: require the FULL amount — no tolerance for underpayment.
    if matched.get("base", 0) < expected_nano:
        return None, False
    # C3: defense in depth — re-verify the claim-code memo binding here too.
    claim_code = await db.tonconnect_claim_code(user["id"])
    if str(matched.get("memo") or "") != claim_code:
        logger.warning("tonconnect memo mismatch: txid=%s user=%s",
                       matched.get("txid"), user["id"])
        return None, False
    order_id = await db.create_order(
        user_id=user["id"], subtotal_cents=subtotal, discount_cents=discount_cents,
        total_cents=total, payment_method="tonconnect",
        delivery_kind="pickup", address="", phone="",
        promo_code=promo_code)
    for it in clean:
        await db.add_order_item(order_id, it["pid"], it["name"],
                                it["qty"], it["price"])
    # NOTE: stock is decremented exactly once, atomically, in
    # handlers/common.py::fulfill_order after payment. Do NOT decrement here.
    claimed = await db.record_payment(provider="tonconnect",
                                      external_id=matched["txid"],
                                      user_id=user["id"], order_id=order_id,
                                      amount_cents=total,
                                      currency=config.CURRENCY)
    if not claimed:
        await db.set_order_status(order_id, "cancelled")
        return order_id, False
    from handlers.common import fulfill_order, maybe_credit_referral, notify_admins
    ok, note = await fulfill_order(order_id)
    if ok:
        await db.set_order_status(order_id, "confirmed")
        if promo_row:
            await db.record_promo_usage(promo_row["id"], user["id"])
        try:
            order_dict = await db.get_order(order_id)
            if order_dict:
                await maybe_credit_referral(order_dict)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("referral credit skipped for order %s: %s", order_id, e)
        except Exception as e:
            logger.warning("referral credit failed for order %s: %s", order_id, e)
            await notify_admins(f"Referral credit failed for order {order_id}: {e}")
    await db.audit(user["tg_id"], "tonconnect_paid",
                   f"order={order_id} tx={matched['txid'][:16]}… ok={ok}")
    return order_id, ok


@dp.message_handler(content_types=types.ContentType.WEB_APP_DATA, state="*")
async def webapp_data(message: types.Message, state: FSMContext):
    raw = (message.web_app_data.data or "") if message.web_app_data else ""
    if not raw or len(raw.encode("utf-8")) > 4096:
        await message.answer(texts.MSG_MINIAPP_BAD_PAYLOAD,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    try:
        payload = json.loads(raw)
    except Exception:
        await message.answer(texts.MSG_MINIAPP_BAD_PAYLOAD,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    # Get order history (from Mini App "My Orders").
    if payload.get("type") == "get_orders":
        user, _ = await get_or_register(message.from_user.id,
                                        message.from_user.full_name)
        orders = await db.list_user_orders(user["id"], limit=5, offset=0)
        if not orders:
            await message.answer(
                "📦 <b>No orders yet.</b>\n\nYour order history will appear here.",
                reply_markup=await main_reply_kb(message.from_user.id),
                parse_mode="HTML")
        else:
            lines = []
            for o in orders:
                status_emoji = {"paid": "✅", "pending": "⏳", "cancelled": "❌"}.get(o["status"], "📦")
                lines.append(f"{status_emoji} <b>Order #{o['id']}</b> — "
                             f"{fmt_money(o['total_cents'], config.CURRENCY)} — {o['status']}")
            await message.answer(
                "📦 <b>Your recent orders:</b>\n\n" + "\n".join(lines),
                reply_markup=await main_reply_kb(message.from_user.id),
                parse_mode="HTML")
        await db.audit(user["tg_id"], "orders_viewed", "")
        return
    # Get referral link (from Mini App "Refer & Earn").
    if payload.get("type") == "get_referral":
        user, _ = await get_or_register(message.from_user.id,
                                        message.from_user.full_name)
        ref_code = user["ref_code"] or ""
        try:
            me = await message.bot.get_me()
            bot_username = me.username or ""
        except Exception:
            bot_username = ""
        link = f"https://t.me/{bot_username}?start=ref_{ref_code}"
        pct = await db.referral_percent()
        await message.answer(
            f"🎁 <b>Your referral link:</b>\n\n<code>{link}</code>\n\n"
            f"Share it with friends. When they make their first purchase, "
            f"you earn {pct}% of their order value as store credit.",
            reply_markup=await main_reply_kb(message.from_user.id),
            parse_mode="HTML")
        await db.audit(user["tg_id"], "referral_link_requested", "")
        return
    # TON Connect payment (from Mini App "Pay with TON" button).
    # The wallet already broadcast the tx; we verify via toncenter.
    if payload.get("type") == "tonconnect_paid":
        user, _ = await get_or_register(message.from_user.id,
                                        message.from_user.full_name)
        await handle_tonconnect_paid(message, user, payload, state)
        return
    # Stock alert subscription (from Mini App "Notify me" button).
    if payload.get("type") == "stock_alert":
        user, _ = await get_or_register(message.from_user.id,
                                        message.from_user.full_name)
        try:
            pid = int(payload.get("id"))
        except (TypeError, ValueError):
            return
        p = await db.get_product(pid)
        if not p or not p["is_active"]:
            return
        if payload.get("on"):
            await db.stock_alert_add(user["id"], pid)
            from utils import h as _h
            await message.answer(f"🔔 You'll be notified when <b>{_h(p['name'])}</b> is back in stock.",
                                 reply_markup=await main_reply_kb(message.from_user.id),
                                 parse_mode="HTML")
        else:
            await db.stock_alert_remove(user["id"], pid)
        return
    items = payload.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        await message.answer(texts.MSG_MINIAPP_BAD_PAYLOAD,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return

    user, _ = await get_or_register(message.from_user.id,
                                    message.from_user.full_name)
    # Process piggybacked stock-alert syncs (Mini App queues these because
    # sendData closes the app, so it can't sync fire-and-forget).
    alert_sync = payload.get("alert_sync")
    if isinstance(alert_sync, dict):
        for pid_raw, on in alert_sync.items():
            try:
                pid = int(pid_raw)
            except (TypeError, ValueError):
                continue
            p = await db.get_product(pid)
            if not p:
                continue
            if on:
                await db.stock_alert_add(user["id"], pid)
            else:
                await db.stock_alert_remove(user["id"], pid)
    # Server-side validation of every line.
    clean = []
    for it in items:
        try:
            pid = int(it.get("id"))
            qty = int(it.get("qty"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 1 <= qty <= 99:
            continue
        p = await db.get_product(pid)
        if not p or not p["is_active"]:
            continue
        if p["stock"] != -1:
            qty = min(qty, p["stock"])
        if qty < 1:
            continue
        clean.append({"pid": pid, "qty": qty, "name": p["name"],
                      "price": p["price_cents"]})
    if not clean:
        await message.answer(texts.MSG_MINIAPP_BAD_PAYLOAD,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return

    # Replace the bot cart with the store cart (the user checked out with these).
    await db.cart_clear(user["id"])
    for it in clean:
        await db.cart_add(user["id"], it["pid"], it["qty"])

    # Optional promo code from the Mini App.
    promo_code = None
    promo_raw = str(payload.get("promo") or "").strip().upper()[:32]
    if promo_raw:
        promo = await db.get_promo(promo_raw)
        if promo:
            ok, _msg, _disc, _row = await db.validate_promo(
                promo_raw, user["id"],
                sum(i["price"] * i["qty"] for i in clean))
            if ok:
                promo_code = promo_raw

    await state.update_data(delivery_kind="delivery", phone=None, address=None,
                            payment_method=None, promo_code=promo_code)
    t = await totals(user["id"], state)
    if not t["items"]:
        await message.answer(texts.MSG_CART_EMPTY,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    for it in t["items"]:
        p = await db.get_product(it["product_id"])
        if not await product_available(p, it["qty"]):
            await message.answer(texts.ERR_OUT_OF_STOCK,
                                 reply_markup=await main_reply_kb(message.from_user.id))
            return
    await message.answer(
        texts.MSG_MINIAPP_CART_IMPORTED.format(
            lines=render_lines(t["items"]),
            total=fmt_money(t["total"], config.CURRENCY)),
        reply_markup=await main_reply_kb(message.from_user.id))
    # Drop into the sleek checkout flow (straight to payment - digital-only).
    await state.update_data(details_skipped=True)
    await render_payment(message, state, user["id"])
    await db.audit(user["tg_id"], "miniapp_import",
                   f"items={len(clean)} promo={promo_code}")


async def handle_tonconnect_paid(message: types.Message, user: dict,
                                 payload: dict, state: FSMContext):
    """Verify a TON Connect payment and create the order.

    The Mini App's wallet already broadcast the tx. We verify via toncenter:
    look for an incoming tx to our TON address FROM THE CLAIMED SENDER with
    value >= expected amount within the last 15 minutes. The matched txid is
    persisted via record_payment (UNIQUE provider+external_id) to prevent
    double-claim / replay.
    """
    import crypto_payments as cp
    import time

    sender = str(payload.get("sender") or "")
    promo_code = str(payload.get("promo") or "").strip().upper()[:32] or None
    items = payload.get("items")
    if not sender or not isinstance(items, list) or not items:
        await message.answer(texts.MSG_MINIAPP_BAD_PAYLOAD,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return

    # Validate items server-side (same as regular checkout).
    clean = []
    for it in items:
        try:
            pid = int(it.get("id"))
            qty = int(it.get("qty"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 1 <= qty <= 99:
            continue
        p = await db.get_product(pid)
        if not p or not p["is_active"]:
            continue
        if p["stock"] != -1:
            qty = min(qty, p["stock"])
        if qty < 1:
            continue
        clean.append({"pid": pid, "qty": qty, "name": p["name"],
                      "price": p["price_cents"]})
    if not clean:
        await message.answer(texts.MSG_MINIAPP_BAD_PAYLOAD,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return

    # Server-side expected amount: recompute from validated items + promo.
    # Never trust the client's amount_nano (the Mini App doesn't send one).
    subtotal = sum(it["qty"] * it["price"] for it in clean)
    if promo_code:
        ok_promo, _, promo_discount, _ = await db.validate_promo(
            promo_code, user["id"], subtotal)
        if ok_promo:
            subtotal -= promo_discount
        else:
            promo_code = None
    ton_usd = (await cp.get_rates()).get("ton")
    if not ton_usd or ton_usd <= 0:
        await message.answer("TON rate unavailable — please try again in a minute.",
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    expected_nano = math.ceil(subtotal / 100 / ton_usd * 1e9)
    # C3: per-user claim code; the on-chain tx memo must equal it.
    claim_code = await db.tonconnect_claim_code(user["id"])

    # Verify the TON transaction via toncenter.
    merchant = config.TON_DEPOSIT_ADDRESS
    if not merchant:
        await message.answer("TON payments are not configured yet.",
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    matched = await find_tonconnect_tx(merchant, sender, expected_nano, claim_code)
    if not matched:
        # Not found yet — the tx may still be propagating. Tell the user
        # we're watching; the 60s crypto watcher will finalize when seen.
        await message.answer(
            "⏳ Payment submitted! We're confirming it on-chain — this usually takes "
            "under a minute. You'll get your order confirmation here automatically.",
            reply_markup=await main_reply_kb(message.from_user.id))
        # Store as a pending TON Connect deposit for the watcher to pick up.
        await db.tonconnect_pending_add(user["id"], sender, expected_nano,
                                        clean, promo_code, claim_code)
        await db.audit(user["tg_id"], "tonconnect_pending",
                       f"sender={sender[:12]}… amount={expected_nano}")
        return

    # Matched! Create + fulfill via the shared helper (audit C2/C3).
    # SECURITY: bind the claim to the paying user (front-running guard).
    existing = await db.get_payment_by_external_id("tonconnect", matched["txid"])
    if existing and existing["user_id"] != user["id"]:
        from handlers.common import notify_admins
        txid = matched["txid"]
        logger.warning("tonconnect fast-path claim blocked: txid=%s existing_user=%s claiming_user=%s",
                       txid, existing["user_id"], user["id"])
        await notify_admins(f"⚠️ TON Connect claim blocked: txid {txid} already claimed by user {existing['user_id']}, attempted by user {user['id']}")
        await message.answer("❌ This payment was already claimed.",
                             reply_markup=await main_reply_kb(message.from_user.id))
        return

    order_id, ok = await create_tonconnect_order(
        user, sender, clean, promo_code, matched)
    if order_id is None:
        await message.answer(
            "⚠️ Payment amount did not cover the order total. Please contact support.",
            reply_markup=await main_reply_kb(message.from_user.id))
        return
    if not ok and (await db.get_order(order_id))["status"] == "cancelled":
        # The tx was already claimed by another order — don't fulfill twice.
        await message.answer(
            "⚠️ This payment was already used for another order. "
            "Please contact support with your transaction hash.",
            reply_markup=await main_reply_kb(message.from_user.id))
        return
    await message.answer(
        f"✅ <b>Payment confirmed!</b>\n\nOrder #{order_id} is being prepared. "
        f"You'll receive your items shortly.",
        reply_markup=await main_reply_kb(message.from_user.id),
        parse_mode="HTML")
