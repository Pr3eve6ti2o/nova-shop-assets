"""Shop flow: categories -> product list -> product detail -> search."""
import html
from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from states import SearchFlow
from utils import cb, fmt_money, paginate, truncate
from .common import (
    get_or_register, main_reply_kb, edit_text_safe, handle_escape,
    product_available, check_stock_line,
)
from .checkout import start_checkout

PER_PAGE = 6


async def _try_delete_user_tap(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass


# ---------------------------------------------------------- categories ---
@dp.message_handler(text=texts.BTN_SHOP)
async def nav_shop(message: types.Message, state: FSMContext):
    await _try_delete_user_tap(message)
    await state.finish()
    await get_or_register(message.from_user.id, message.from_user.full_name)
    cats = await db.list_categories()
    await message.answer(texts.MSG_CATEGORIES, reply_markup=kb.categories_kb(cats))


@dp.callback_query_handler(text="shop")
async def cb_shop(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await state.finish()
    cats = await db.list_categories()
    await edit_text_safe(query, texts.MSG_CATEGORIES, kb.categories_kb(cats))


# -------------------------------------------------------- product list ---
@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cat:"))
async def cb_category(query: types.CallbackQuery):
    await query.answer()
    _, cid_s, page_s = query.data.split(":")
    cid, page = int(cid_s), int(page_s)
    cat = await db.get_category(cid)
    if not cat:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    total = await db.count_active_products(cid)
    page, _ = paginate(total, page, PER_PAGE)
    items = await db.list_products(cid, PER_PAGE, page * PER_PAGE)
    header = texts.MSG_BREADCRUMB.format(cat=cat["name"])
    if not items:
        await edit_text_safe(
            query,
            f"{header}\n\n" + texts.MSG_CATEGORY_EMPTY.format(name=cat["name"]),
            kb.products_kb([], cid, 0, 0, PER_PAGE),
        )
        return
    await edit_text_safe(query, header, kb.products_kb(items, cid, page, total, PER_PAGE))


# ------------------------------------------------------- product detail ---
async def _qty_in_view(state: FSMContext, pid: int) -> int:
    data = await state.get_data()
    return int(data.get(f"qv:{pid}", 1))


async def _set_qty_in_view(state: FSMContext, pid: int, qty: int):
    await state.update_data(**{f"qv:{pid}": max(1, min(99, qty))})


async def show_product_detail(target, pid: int, user, qty: int = 1):
    """Render product detail; target is CallbackQuery or Message."""
    p = await db.get_product(pid)
    if not p or not p["is_active"]:
        if isinstance(target, types.CallbackQuery):
            await target.answer(texts.ERR_NOT_FOUND, show_alert=True)
        else:
            await target.answer(texts.ERR_NOT_FOUND)
        return
    in_wl = await db.wishlist_has(user["id"], pid)
    old = (texts.MSG_OLD_PRICE.format(price=fmt_money(p["old_price_cents"], config.CURRENCY))
           if p["old_price_cents"] and p["old_price_cents"] > p["price_cents"] else "")
    from utils import h as _h
    caption = texts.MSG_PRODUCT_CAPTION.format(
        name=_h(p["name"]), description=_h(truncate(p["description"] or "", 200)),
        price=fmt_money(p["price_cents"], config.CURRENCY), old_price=old,
        stock_line=await check_stock_line(p), rating_line="")
    markup = kb.product_kb(p, qty, in_wl, 0.0, 0)

    if isinstance(target, types.CallbackQuery):
        msg = target.message
        if p["photo_file_id"]:
            media = types.InputMediaPhoto(p["photo_file_id"], caption=caption)
            try:
                if msg.photo:
                    await msg.edit_media(media, reply_markup=markup)
                else:
                    await msg.delete()
                    await bot.send_photo(msg.chat.id, p["photo_file_id"],
                                         caption=caption, reply_markup=markup)
            except Exception:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await bot.send_photo(msg.chat.id, p["photo_file_id"],
                                     caption=caption, reply_markup=markup)
        else:
            await edit_text_safe(target, caption, markup)
    else:
        if p["photo_file_id"]:
            await target.answer_photo(p["photo_file_id"], caption=caption,
                                      reply_markup=markup)
        else:
            await target.answer(caption, reply_markup=markup,
                                disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("p:"))
async def cb_product(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    pid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    qty = await _qty_in_view(state, pid)
    await show_product_detail(query, pid, user, qty)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("pa:"))
async def cb_stepper(query: types.CallbackQuery, state: FSMContext):
    _, pid_s, delta_s = query.data.split(":")
    pid = int(pid_s)
    delta = 1 if delta_s == "+1" else -1
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    p = await db.get_product(pid)
    if not p or not p["is_active"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    qty = await _qty_in_view(state, pid)
    new_qty = max(1, min(99, qty + delta))
    if new_qty == qty and delta < 0:
        await query.answer(texts.TOAST_QTY_MIN)
        return
    await query.answer()
    await _set_qty_in_view(state, pid, new_qty)
    # rating removed
    in_wl = await db.wishlist_has(user["id"], pid)
    try:
        await query.message.edit_reply_markup(
            kb.product_kb(p, new_qty, in_wl, 0.0, 0))
    except Exception:
        pass


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("a:"))
async def cb_add_cart(query: types.CallbackQuery, state: FSMContext):
    pid = int(query.data.split(":")[1])
    p = await db.get_product(pid)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    qty = await _qty_in_view(state, pid)
    if not product_available(p, qty):
        await query.answer(texts.ERR_OUT_OF_STOCK, show_alert=True)
        return
    await db.cart_add(user["id"], pid, qty)
    await query.answer(texts.TOAST_ADDED_CART)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("pb:"))
async def cb_buy_now(query: types.CallbackQuery, state: FSMContext):
    pid = int(query.data.split(":")[1])
    p = await db.get_product(pid)
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    qty = await _qty_in_view(state, pid)
    if not product_available(p, qty):
        await query.answer(texts.ERR_OUT_OF_STOCK, show_alert=True)
        return
    await db.cart_clear(user["id"])
    await db.cart_add(user["id"], pid, qty)
    await query.answer(texts.TOAST_ADDED_CART)
    await start_checkout(query, state)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("w:"))
async def cb_wishlist(query: types.CallbackQuery, state: FSMContext):
    pid = int(query.data.split(":")[1])
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    p = await db.get_product(pid)
    if not p or not p["is_active"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    now_in = await db.wishlist_toggle(user["id"], pid)
    await query.answer(texts.TOAST_WISH_ADDED if now_in else texts.TOAST_WISH_REMOVED)
    qty = await _qty_in_view(state, pid)
    # rating removed
    try:
        await query.message.edit_reply_markup(
            kb.product_kb(p, qty, now_in, 0.0, 0))
    except Exception:
        pass


# ---------------------------------------------------------------- search ---
@dp.message_handler(text=texts.BTN_SEARCH)
async def nav_search(message: types.Message, state: FSMContext):
    await _try_delete_user_tap(message)
    await get_or_register(message.from_user.id, message.from_user.full_name)
    await SearchFlow.waiting_query.set()
    await message.answer(texts.MSG_SEARCH_ASK, reply_markup=kb.force_reply())


@dp.callback_query_handler(text="snew")
async def cb_search_new(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await SearchFlow.waiting_query.set()
    await query.message.answer(texts.MSG_SEARCH_ASK, reply_markup=kb.force_reply())


@dp.message_handler(state=SearchFlow.waiting_query)
async def search_query(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    q = (message.text or "").strip()
    if not q:
        return
    await state.update_data(q=q)
    await SearchFlow.results.set()
    await render_search(message, state, 0)


async def render_search(target, state: FSMContext, page: int):
    data = await state.get_data()
    q = data.get("q", "")
    total = await db.count_search(q)
    page, _ = paginate(total, page, PER_PAGE)
    items = await db.search_products(q, PER_PAGE, page * PER_PAGE)
    q_escaped = html.escape(q)
    text = texts.MSG_SEARCH_RESULTS.format(query=q_escaped) if items else texts.MSG_SEARCH_EMPTY.format(query=q_escaped)
    markup = kb.search_results_kb(items, q, page, total, PER_PAGE)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("sp:"))
async def cb_search_page(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    if not data.get("q"):
        return
    await render_search(query, state, int(query.data.split(":")[1]))


@dp.callback_query_handler(text="noop")
async def cb_noop(query: types.CallbackQuery):
    await query.answer()
