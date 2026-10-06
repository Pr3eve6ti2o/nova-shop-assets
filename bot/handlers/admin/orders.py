"""Admin orders: filter by status, detail, status transitions with user notify."""
from aiogram import types

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from utils import fmt_money, paginate
from ..common import edit_text_safe, render_lines, totals_text, fulfill_order, maybe_credit_referral
from . import IsAdmin

PER_PAGE = 8


async def _order_is_paid(order) -> bool:
    """True when money is on record for this order (any rail)."""
    method = order["payment_method"] or ""
    oid = order["id"]
    if method in ("stars", "card"):
        async with db._db() as conn:
            async with conn.execute(
                    "SELECT id FROM payments WHERE order_id=? AND status='paid'"
                    " LIMIT 1", (oid,)) as cur:
                return await cur.fetchone() is not None
    if method == "cryptobot":
        async with db._db() as conn:
            async with conn.execute(
                    "SELECT id FROM cryptobot_invoices WHERE order_id=?"
                    " AND status='paid' LIMIT 1", (oid,)) as cur:
                return await cur.fetchone() is not None
    if method.startswith("direct_"):
        dep = await db.get_deposit_by_order(oid)
        return bool(dep and dep["status"] == "paid")
    # M3: tonconnect rail records into payments (provider="tonconnect").
    if method == "tonconnect":
        async with db._db() as conn:
            async with conn.execute(
                    "SELECT id FROM payments WHERE order_id=? AND status='paid'"
                    " LIMIT 1", (oid,)) as cur:
                return await cur.fetchone() is not None
    return False


@dp.callback_query_handler(text="ad:ordf", is_admin=config.PERM_ORDERS)
async def cb_orders_home(query: types.CallbackQuery):
    await query.answer()
    counts = await db.orders_by_status_counts()
    await edit_text_safe(query, texts.MSG_ORDERS_ADMIN_TITLE,
                         kb.admin_orders_filter_kb(counts))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:ord:"),
                           is_admin=config.PERM_ORDERS)
async def cb_orders_list(query: types.CallbackQuery):
    await query.answer()
    _, _, status, page_s = query.data.split(":")
    if status not in texts.ORDER_STATUSES:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    page = int(page_s)
    total = await db.count_orders_by_status(status)
    page, _ = paginate(total, page, PER_PAGE)
    orders = await db.list_orders_by_status(status, PER_PAGE, page * PER_PAGE)
    await edit_text_safe(
        query,
        f"\U0001f9fe <b>Orders \u2014 {texts.STATUS_LABEL[status]}</b>",
        kb.admin_orders_list_kb(orders, status, page, total, PER_PAGE))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:o:"),
                           is_admin=config.PERM_ORDERS)
async def cb_order_detail(query: types.CallbackQuery):
    await query.answer()
    oid = int(query.data.split(":")[2])
    order = await db.get_order(oid)
    if not order:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user = await db.get_user(order["user_id"])
    items = await db.get_order_items(oid)
    lines = render_lines([{"name": i["name"], "qty": i["qty"],
                           "price_cents": i["price_cents"]} for i in items])
    t = {"subtotal": order["subtotal_cents"], "discount": order["discount_cents"],
         "promo_code": order["promo_code"],
         "delivery_fee": order["total_cents"] - order["subtotal_cents"]
                         + order["discount_cents"],
         "total": order["total_cents"]}
    text = texts.MSG_ORDER_ADMIN_DETAIL.format(
        oid=oid, status=texts.STATUS_LABEL.get(order["status"], order["status"]),
        lines=lines, totals=totals_text(t),
        name=(user["name"] if user else "?"),
        tg_id=(user["tg_id"] if user else "?"),
        phone=order["phone"] or "\u2014", address=order["address"] or "\u2014",
        payment=order["payment_method"] or "\u2014",
        delivery=order["delivery_kind"] or "\u2014")
    await edit_text_safe(query, text, kb.admin_order_detail_kb(oid, order["status"]))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:os:"),
                           is_admin=config.PERM_ORDERS)
async def cb_order_set_status(query: types.CallbackQuery):
    _, _, oid_s, status = query.data.split(":")
    oid = int(oid_s)
    if status not in texts.ORDER_STATUSES:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    order = await db.get_order(oid)
    if not order:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # COD orders: fulfill stock/keys when first confirmed by admin.
    # Other rails: never move an unpaid order into a fulfillment-bearing
    # status — that releases goods free. H18: gate EVERY transition into
    # confirmed (not just from pending/processing). H20: same gate for
    # delivered/shipped/completed.
    if status in ("confirmed", "delivered", "shipped", "completed"):
        if (order["payment_method"] or "") != "cod" \
                and not await _order_is_paid(order):
            await query.answer(texts.MSG_ADMIN_CONFIRM_UNPAID, show_alert=True)
            return
    if status in ("confirmed", "delivered", "shipped", "completed") \
            and order["status"] in ("pending", "processing"):
        # First entry into a fulfillment-bearing status: claim + fulfill.
        # Atomic claim pending -> processing so two concurrent admin confirms
        # cannot both fulfill the same order (double keys/stock/referral).
        claimed = await db.claim_order_processing(oid)
        if not claimed:
            order = await db.get_order(oid)
            if not order or order["status"] != "processing":
                await query.answer("Order status changed \u2014 please refresh.",
                                   show_alert=True)
                return
            # H13: another admin may be fulfilling RIGHT NOW — only retry a
            # STALE claim, otherwise report in-flight.
            if not await db.order_claim_stale(oid, minutes=5):
                await query.answer("Another admin is fulfilling this order.",
                                   show_alert=True)
                return
            logger.warning("admin confirm retrying fulfillment of stuck "
                           "processing order %s", oid)
        ok, note = await fulfill_order(oid)
        if not ok:
            await query.answer(f"\u26a0\ufe0f {note}", show_alert=True)
            return
        await maybe_credit_referral(await db.get_order(oid))
    await db.set_order_status(oid, status)
    if status == "cancelled":
        await db.release_order_promo(oid)  # M2: don't burn promo on cancel
    await db.audit(query.from_user.id, "order_status", f"order={oid} status={status}")
    user = await db.get_user(order["user_id"])
    if user:
        try:
            await bot.send_message(
                user["tg_id"],
                texts.MSG_ORDER_NOTIFIED.format(
                    oid=oid, status=texts.STATUS_LABEL.get(status, status)))
        except Exception:
            pass
    await query.answer(texts.TOAST_ORDER_STATUS.format(
        oid=oid, status=texts.STATUS_LABEL.get(status, status)))
    # Re-render detail.
    order = await db.get_order(oid)
    items = await db.get_order_items(oid)
    lines = render_lines([{"name": i["name"], "qty": i["qty"],
                           "price_cents": i["price_cents"]} for i in items])
    t = {"subtotal": order["subtotal_cents"], "discount": order["discount_cents"],
         "promo_code": order["promo_code"],
         "delivery_fee": order["total_cents"] - order["subtotal_cents"]
                         + order["discount_cents"],
         "total": order["total_cents"]}
    text = texts.MSG_ORDER_ADMIN_DETAIL.format(
        oid=oid, status=texts.STATUS_LABEL.get(order["status"], order["status"]),
        lines=lines, totals=totals_text(t),
        name=(user["name"] if user else "?"),
        tg_id=(user["tg_id"] if user else "?"),
        phone=order["phone"] or "\u2014", address=order["address"] or "\u2014",
        payment=order["payment_method"] or "\u2014",
        delivery=order["delivery_kind"] or "\u2014")
    await edit_text_safe(query, text, kb.admin_order_detail_kb(oid, order["status"]))
