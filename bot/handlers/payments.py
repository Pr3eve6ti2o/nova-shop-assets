"""Payments: pre-checkout verification, successful payment, fulfillment."""
import logging

from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from utils import fmt_money
from .common import (
    get_or_register, fulfill_order, maybe_credit_referral, render_lines,
    totals_text, render_roadmap, notify_admins,
)

logger = logging.getLogger(__name__)


@dp.pre_checkout_query_handler()
async def pre_checkout(query: types.PreCheckoutQuery):
    """MUST be fast: DB checks only, answered within seconds."""
    ok = False
    try:
        _, oid_s = (query.invoice_payload or "").split(":")
        order = await db.get_order(int(oid_s))
        user = await db.get_user_by_tg(query.from_user.id)
        if order and user and order["user_id"] == user["id"] \
                and order["status"] == "pending":
            if query.currency == "XTR":
                from .common import stars_label
                expected = stars_label(order["total_cents"])
            else:
                expected = order["total_cents"]
            ok = (query.total_amount == expected)
    except Exception as e:
        logger.warning("pre_checkout verify error: %s", e)
    if ok:
        await bot.answer_pre_checkout_query(query.id, ok=True)
    else:
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message=texts.MSG_PRECHECKOUT_FAIL)


@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT, state="*")
async def payment_success(message: types.Message, state: FSMContext):
    await state.finish()
    sp = message.successful_payment
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    provider = "stars" if sp.currency == "XTR" else "telegram"

    try:
        oid = int(sp.invoice_payload.split(":")[1])
    except (ValueError, IndexError, AttributeError):
        logger.error("successful_payment with malformed payload: %r",
                     getattr(sp, "invoice_payload", None))
        return

    # Idempotency: UNIQUE(provider, external_id).
    is_new = await db.record_payment(
        provider=provider, external_id=sp.telegram_payment_charge_id,
        user_id=user["id"], order_id=oid,
        amount_cents=sp.total_amount, currency=sp.currency, status="paid")
    if not is_new:
        logger.info("duplicate successful_payment ignored: %s",
                    sp.telegram_payment_charge_id)
        return

    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        logger.error("payment for unknown/foreign order: %s", sp.invoice_payload)
        return

    if order["status"] == "cancelled":
        # Paid after the user cancelled: do NOT deliver goods. The payment
        # is already recorded above, so it stays on file for a manual refund.
        logger.warning("payment %s arrived for cancelled order %s",
                       sp.telegram_payment_charge_id, oid)
        await notify_admins(
            texts.MSG_ADMIN_PAID_AFTER_CANCEL.format(oid=oid),
            min_bit=config.PERM_ORDERS)
        return

    ok, note = await fulfill_order(oid)
    if not ok:
        logger.error("fulfillment failed for order %s: %s", oid, note)
        await notify_admins(
            texts.MSG_ADMIN_FULFILL_FAILED.format(oid=oid, note=note),
            min_bit=config.PERM_ORDERS)
        await message.answer(texts.MSG_PAY_FAIL_STOCK)
        return
    await db.set_order_status(oid, "confirmed")

    await db.audit(user["tg_id"], "payment_success",
                   f"order={oid} provider={provider} amount={sp.total_amount}")
    await maybe_credit_referral(await db.get_order(oid))

    # Receipt (new message).
    items = await db.get_order_items(oid)
    lines = render_lines([{"name": i["name"], "qty": i["qty"],
                           "price_cents": i["price_cents"]} for i in items])
    method = texts.PAY_METHOD_LABEL.get(provider, provider)
    values_block = ""
    dvals = [(i["name"], i["qty"], i["delivered_value"]) for i in items
             if i["delivered_value"]]
    if dvals:
        values_block = texts.MSG_FULFILL_DIGITAL.format(values="\n".join(
            texts.MSG_FULFILL_VALUE_LINE.format(name=n, qty=q,
                                                code=f"<code>{v}</code>")
            for n, q, v in dvals))
    else:
        values_block = texts.MSG_FULFILL_PHYSICAL
    t = {"subtotal": order["subtotal_cents"], "discount": order["discount_cents"],
         "promo_code": order["promo_code"],
         "delivery_fee": order["total_cents"] - order["subtotal_cents"]
                        + order["discount_cents"],
         "total": order["total_cents"]}
    await message.answer(
        texts.MSG_PAY_OK.format(oid=oid, fulfillment=values_block) + "\n\n" +
        totals_text(t) + f"\n\n{render_roadmap('confirmed')}",
        reply_markup=kb.order_success_kb(oid),
        disable_web_page_preview=True)
