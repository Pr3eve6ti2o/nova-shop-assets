"""User order history: list, detail with roadmap, buy-again, self-cancel."""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton

import config
import keyboards as kb
import texts
from loader import db, dp
from utils import fmt_money, paginate
from .common import (
    get_or_register, edit_text_safe, totals_text, render_lines, render_roadmap,
    product_available,
)

PER_PAGE = 6


async def _try_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


@dp.message_handler(text=texts.BTN_ORDERS)
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


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ord"))
async def cb_orders(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    parts = query.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 0
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
        return
    items = await db.get_order_items(oid)
    lines = render_lines([{"name": i["name"], "qty": i["qty"],
                           "price_cents": i["price_cents"]} for i in items])
    t = {"subtotal": order["subtotal_cents"], "discount": order["discount_cents"],
         "promo_code": order["promo_code"],
         "delivery_fee": order["total_cents"] - order["subtotal_cents"]
                         + order["discount_cents"],
         "total": order["total_cents"]}
    pay_label = texts.PAY_METHOD_LABEL.get(order["payment_method"],
                                             order["payment_method"])
    # Include delivered digital keys if available
    values_block = ""
    dvals = [(i["name"], i["qty"], i["delivered_value"]) for i in items
             if i["delivered_value"]]
    if dvals:
        values_block = "\n\n" + texts.MSG_FULFILL_DIGITAL.format(values="\n".join(
            texts.MSG_FULFILL_VALUE_LINE.format(name=n, qty=q,
                                                code=f"<code>{v}</code>")
            for n, q, v in dvals))
    text = texts.MSG_ORDER_DETAIL.format(
        oid=oid, lines=lines, totals=totals_text(t), payment=pay_label,
        delivery=order["delivery_kind"] or "\u2014",
        roadmap=render_roadmap(order["status"])) + values_block
    markup = kb.order_detail_kb(oid)
    if order["status"] == "pending":
        markup.inline_keyboard.insert(
            2, [InlineKeyboardButton(texts.BTN_CANCEL_ORDER,
                                    callback_data=f"oc:{oid}")])
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup,
                            disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("o:"))
async def cb_order_detail(query: types.CallbackQuery):
    await query.answer()
    oid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await show_order_detail(query, oid, user)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ob:"))
async def cb_buy_again(query: types.CallbackQuery):
    oid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    added = 0
    for it in await db.get_order_items(oid):
        p = await db.get_product(it["product_id"])
        if product_available(p, it["qty"]):
            await db.cart_add(user["id"], it["product_id"], it["qty"])
            added += 1
    await query.answer(texts.MSG_REORDER_DONE if added else texts.ERR_OUT_OF_STOCK,
                       show_alert=not added)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("oc:"))
async def cb_order_cancel_ask(query: types.CallbackQuery):
    """Ask for confirmation before the user cancels their own pending order."""
    await query.answer()
    oid = int(query.data.split(":")[1])
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


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ocx:"))
async def cb_order_cancel_do(query: types.CallbackQuery):
    """Execute the cancellation. Only pending orders; nothing was charged."""
    oid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    order = await db.get_order(oid)
    if not order or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    if order["status"] != "pending":
        await query.answer(texts.MSG_ORDER_CANCEL_DENIED, show_alert=True)
        return
    await db.set_order_status(oid, "cancelled")
    await db.release_order_promo(oid)  # M2: don't burn promo on unpaid cancel
    await db.audit(user["tg_id"], "order_cancel_self", f"order={oid}")
    await query.answer(texts.TOAST_ORDER_CANCELLED)
    await edit_text_safe(query, texts.MSG_ORDER_CANCELLED.format(oid=oid),
                         kb.main_menu_inline())
