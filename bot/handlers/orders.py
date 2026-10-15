"""User order history: list, detail with roadmap, buy-again, self-cancel."""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from utils import fmt_money, h, paginate
from .common import (
    get_or_register, edit_text_safe, totals_text, render_lines, render_roadmap,
    notify_admins, product_available,
)

PER_PAGE = 6

# Post-purchase plan Phase 2: one plain next-step line per status (and
# delivery kind where it changes the meaning), so the order page itself
# answers "what happens now?".
_NEXT_STEP = {
    ("pending", None):
        "⏳ Awaiting payment — complete payment to confirm your order.",
    ("confirmed", "pickup"):
        "We're getting it ready — we'll message you when it's ready "
        "for pickup.",
    ("confirmed", "delivery"):
        "We're preparing your order — we'll message you when it ships.",
    ("confirmed", None):
        "We're preparing your order — we'll message you with the "
        "next step.",
    ("preparing", "pickup"):
        "Being prepared — we'll message you when it's ready for pickup.",
    ("preparing", "delivery"):
        "Being prepared — we'll message you when it ships.",
    ("preparing", None):
        "Being prepared — we'll message you with the next step.",
    ("shipped", "pickup"):
        "Ready for pickup. Tap “I've received it” once you've "
        "collected it.",
    ("shipped", "delivery"):
        "On its way to you. Tap “I've received it” when it arrives.",
    ("shipped", None):
        "On its way. Tap “I've received it” when it arrives.",
    ("delivered", None):
        "Delivered — enjoy! You can rate the items or request a "
        "return below.",
    ("cancelled", None):
        "This order was cancelled.",
    ("refunded", None):
        "This order was refunded to your balance.",
}


_bot_username = None


async def _bot_username() -> str:
    """Cached bot username for deep links (one get_me call ever)."""
    global _bot_username
    if not _bot_username:
        _bot_username = (await bot.get_me()).username
    return _bot_username


async def _try_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


@dp.message_handler(text=texts.BTN_ORDERS, state="*")
async def nav_orders(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("Your orders are private — please open me in a private chat.")
        return
    await _try_delete(message)
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    await render_orders(message, user["id"], 0)


async def render_orders(target, user_id: int, page: int):
    total = await db.count_user_orders(user_id)
    page, _ = paginate(total, page, PER_PAGE)
    orders = await db.list_user_orders(user_id, PER_PAGE, page * PER_PAGE)
    if not orders:
        text, markup = texts.MSG_ORDERS_EMPTY, kb.main_menu_inline()
    else:
        text, markup = texts.MSG_ORDERS_TITLE, kb.orders_kb(orders, page, total, PER_PAGE)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ord"), state="*")
async def cb_orders(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    parts = query.data.split(":")
    # Opus: guard the page parse — "ord:abc" raised ValueError, negative
    # page flowed into offset unchecked.
    try:
        page = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        page = 0
    if page < 0:
        page = 0
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await render_orders(query, user["id"], page)


async def show_order_detail(target, oid: int, user: dict):
    """Show order detail; target is CallbackQuery or Message (for deep links)."""
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        if isinstance(target, types.CallbackQuery):
            await target.answer(texts.ERR_NOT_FOUND, show_alert=True)
        else:
            await target.answer(texts.ERR_NOT_FOUND)
        return True  # answered (callback) — caller must not answer again
    # H4: never render delivered keys outside a private chat (group deep links).
    if isinstance(target, types.Message) and target.chat.type != "private":
        username = await _bot_username()
        btn = InlineKeyboardMarkup().add(InlineKeyboardButton(
            "🔒 Open in private chat",
            url=f"https://t.me/{username}?start=o_{oid}"))
        await target.answer(
            "🔒 For your security, order details with digital keys can only be viewed in a private chat with the bot.",
            reply_markup=btn)
        return
    items = await db.get_order_items(oid)
    lines = render_lines([{"name": i["name"], "qty": i["qty"],
                           "price_cents": i["price_cents"]} for i in items])
    t = {"subtotal": order["subtotal_cents"], "discount": order["discount_cents"],
         "promo_code": order["promo_code"],
         "delivery_fee": order["total_cents"] - order["subtotal_cents"]
                         + order["discount_cents"],
         "total": order["total_cents"]}
    pay_label = texts.PAY_METHOD_LABEL.get(order["payment_method"])
    if pay_label is None:
        pay_label = "—"
    # Include delivered digital keys if available
    values_block = ""
    dvals = [(i["name"], i["qty"], i["delivered_value"]) for i in items
             if i["delivered_value"]]
    if dvals:
        # Opus: escape delivered values — a "<" in a key broke HTML parsing
        # and hid the keys from the buyer.
        from html import escape as _escape
        values_block = "\n\n" + texts.MSG_FULFILL_DIGITAL.format(values="\n".join(
            texts.MSG_FULFILL_VALUE_LINE.format(name=n, qty=q,
                                                code=f"<code>{_escape(v)}</code>")
            for n, q, v in dvals))
    # Post-purchase plan: two fulfilment paths. Physical goods get the
    # Medusa flow (preparing -> shipped -> customer confirms receipt);
    # digital goods are delivered at fulfilment and skip all of it, so
    # the page stays sleek and never asks a digital buyer to confirm
    # receipt of a key they already have.
    physical = await db.order_has_physical(oid)
    # Phase 2: delivery block = kind label, the address/phone on file,
    # and the next-step line for this status.
    kind = order["delivery_kind"] or None
    if physical:
        d_lines = [{"pickup": "🤝 Pickup",
                    "delivery": "🚚 Delivery"}.get(kind, kind or "—")]
        if order["address"]:
            d_lines.append(f"📍 {h(order['address'])}")
        if order["phone"]:
            d_lines.append(f"📞 {h(order['phone'])}")
        hint = _NEXT_STEP.get((order["status"], kind),
                              _NEXT_STEP.get((order["status"], None)))
    else:
        d_lines = ["⚡ Digital delivery"]
        if order["status"] in ("cancelled", "refunded"):
            hint = _NEXT_STEP.get((order["status"], None))
        elif order["fulfilled_at"]:
            hint = ("✅ Delivered digitally — your keys are shown "
                    "on this page.")
        elif order["status"] == "pending":
            hint = _NEXT_STEP.get(("pending", None))
        else:
            hint = _NEXT_STEP.get(("confirmed", None))
    delivery_block = "\n".join(d_lines)
    if hint:
        delivery_block += f"\n\n{hint}"
    text = texts.MSG_ORDER_DETAIL.format(
        oid=oid, lines=lines, totals=totals_text(t), payment=pay_label,
        delivery=delivery_block,
        roadmap=render_roadmap(order["status"], order,
                               digital=not physical)) + values_block
    markup = kb.order_detail_kb(oid)
    if order["status"] == "pending":
        markup.inline_keyboard.insert(
            1, [InlineKeyboardButton(texts.BTN_CANCEL_ORDER,
                                     callback_data=f"oc:{oid}")])
    # Post-purchase plan Phase 3 (physical path only): receipt + rating
    # are fulfilment-gated (Medusa: returns and reviews start after
    # delivery). Digital orders were delivered at fulfilment, so their
    # rating is available straight away and no receipt step exists.
    if physical and order["status"] == "shipped":
        markup.inline_keyboard.insert(
            1, [InlineKeyboardButton("✅ I've received it",
                                     callback_data=f"rcv:{oid}")])
    if order["status"] == "delivered" or (
            not physical
            and order["status"] not in ("pending", "cancelled",
                                        "refunded")):
        markup.inline_keyboard.insert(
            1, [InlineKeyboardButton(texts.BTN_RATE_ITEMS,
                                     callback_data=f"or:{oid}")])
    # Port 1.1: append a return entry point for returnable orders with no
    # open return. Existing buttons are not modified. Phase 3 gate: on
    # the physical path the customer entry appears once the order has
    # shipped — you cannot return what has not arrived. Digital orders
    # keep the original gate (they were delivered at fulfilment).
    # Admin-side returns are unchanged either way.
    if order["status"] in (("shipped", "delivered") if physical
                           else db.RETURNABLE_STATUSES):
        _open = await db.get_open_return(oid)
        if not _open:
            markup.inline_keyboard.append([InlineKeyboardButton(
                "↩️ Request return", callback_data=f"rtn:new:{oid}")])
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup,
                            disable_web_page_preview=True)
    return False


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("o:"), state="*")
async def cb_order_detail(query: types.CallbackQuery):
    # Audit 20261015 07-users: no entry answer — show_order_detail
    # answers the not-found alert itself, and a callback query can only
    # be answered once (both alerts used to be rejected by Telegram).
    try:
        oid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if not await show_order_detail(query, oid, user):
        await query.answer()


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("or:"), state="*")
async def cb_order_rate(query: types.CallbackQuery):
    """Rate items (post-purchase plan Phase 3): the button used to be
    rendered with no handler behind it. Lists the order's items; each
    opens the existing product rating picker (rvl:). The button itself
    is only rendered on delivered orders."""
    try:
        oid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    user, _ = await get_or_register(query.from_user.id,
                                    query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await query.answer()
    markup = InlineKeyboardMarkup()
    seen = set()
    for it in await db.get_order_items(oid):
        pid = it["product_id"]
        if pid and pid not in seen:
            seen.add(pid)
            markup.add(InlineKeyboardButton(
                f"⭐ {h(it['name'])}", callback_data=f"rvl:{pid}"))
    markup.row(InlineKeyboardButton(texts.BTN_BACK,
                                    callback_data=f"o:{oid}"))
    await edit_text_safe(
        query,
        f"⭐ <b>Rate items — order #{oid}</b>\n\nPick an item to rate:",
        markup)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("rcv:"), state="*")
async def cb_order_received(query: types.CallbackQuery):
    """Customer confirms receipt (post-purchase plan Phase 3):
    shipped -> delivered via compare-and-set, so the delivered stamp —
    and the rating/return windows — start at the real handover."""
    try:
        oid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    user, _ = await get_or_register(query.from_user.id,
                                    query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    won = await db.set_order_status(oid, "delivered",
                                    only_if_status="shipped")
    if not won:
        return await query.answer(
            "This order isn't awaiting receipt.", show_alert=True)
    await query.answer("✅ Marked as delivered — thank you!")
    await notify_admins(
        f"📦 Order #{oid}: customer confirmed receipt (delivered).")
    await show_order_detail(query, oid, user)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ob:"), state="*")
async def cb_buy_again(query: types.CallbackQuery, state: FSMContext):
    try:
        oid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    added = 0
    for it in await db.get_order_items(oid):
        p = await db.get_product(it["product_id"])
        if await product_available(p, it["qty"]):
            await db.cart_add(user["id"], it["product_id"], it["qty"])
            added += 1
    if not added:
        return await query.answer(texts.ERR_OUT_OF_STOCK, show_alert=True)
    await query.answer(texts.MSG_REORDER_DONE)
    # Post-purchase plan Phase 3: land the customer in the cart they
    # just filled, instead of leaving them on the order page.
    from .cart import render_cart
    await render_cart(query, user["id"], state)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("oc:"), state="*")
async def cb_order_cancel_ask(query: types.CallbackQuery):
    """Ask for confirmation before the user cancels their own pending order."""
    # Audit 20261015 07-users: no entry answer — every error branch below
    # answers with an alert, and a callback query can only be answered
    # once (all three alerts used to be dead code).
    try:
        oid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    if order["status"] != "pending":
        await query.answer(texts.MSG_ORDER_CANCEL_DENIED, show_alert=True)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(texts.BTN_YES_CANCEL,
                                   callback_data=f"ocx:{oid}"))
    markup.row(InlineKeyboardButton(texts.BTN_KEEP_ORDER,
                                   callback_data=f"o:{oid}"))
    await edit_text_safe(query, texts.MSG_ORDER_CANCEL_ASK.format(oid=oid),
                         markup)
    await query.answer()


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ocx:"), state="*")
async def cb_order_cancel_do(query: types.CallbackQuery):
    """Execute the cancellation. Only pending orders; nothing was charged."""
    try:
        oid = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    if order["status"] != "pending":
        await query.answer(texts.MSG_ORDER_CANCEL_DENIED, show_alert=True)
        return
    # Opus P0: atomic conditional claim — the unconditional set_order_status
    # could clobber "processing"/"paid" if a payment landed between the read
    # and the write. Only the winner proceeds; the loser sees the denied
    # message. This also makes double promo release impossible.
    claimed = await db.set_order_status(oid, "cancelled",
                                        only_if_status="pending")
    if not claimed:
        await query.answer(texts.MSG_ORDER_CANCEL_DENIED, show_alert=True)
        return
    await db.release_order_promo(oid)  # M2: don't burn promo on unpaid cancel
    await db.audit(user["tg_id"], "order_cancel_self", f"order={oid}")
    await query.answer(texts.TOAST_ORDER_CANCELLED)
    await edit_text_safe(query, texts.MSG_ORDER_CANCELLED.format(oid=oid),
                         kb.main_menu_inline())
