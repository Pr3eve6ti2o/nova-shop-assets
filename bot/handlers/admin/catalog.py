"""Admin catalog: categories + products CRUD wizards."""
import html
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import keyboards as kb
import texts
from loader import db, dp
from states import CategoryWizard, ProductWizard, ProductPriceEdit, ProductStockEdit, ProductValuesAdd
from utils import fmt_money, paginate
from ..common import edit_text_safe, handle_escape
from . import IsAdmin, mask_of

PER_PAGE = 8


# ------------------------------------------------------------ categories ---
@dp.callback_query_handler(text="ad:cat", is_admin=config.PERM_CATALOG)
async def cb_cat_list(query: types.CallbackQuery):
    await query.answer()
    cats = await db.list_categories()
    lines = []
    for c in cats:
        n = await db.count_products_in_category(c["id"])
        lines.append(texts.MSG_CAT_LINE.format(emoji=html.escape(c["emoji"]), name=html.escape(c["name"]), n=n))
    text = texts.MSG_CAT_LIST.format(lines="\n".join(lines) or "\u2014")
    await edit_text_safe(query, text, kb.admin_categories_kb(cats))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:cl:"),
                           is_admin=config.PERM_CATALOG)
async def cb_cat_detail(query: types.CallbackQuery):
    await query.answer()
    cid = int(query.data.split(":")[2])
    cat = await db.get_category(cid)
    if not cat:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    n = await db.count_products_in_category(cid)
    text = texts.MSG_CAT_LINE.format(emoji=html.escape(cat["emoji"]), name=html.escape(cat["name"]), n=n)
    await edit_text_safe(query, f"\U0001f4e6 <b>Category</b>\n\n{text}",
                         kb.admin_category_kb(cat, n))


@dp.callback_query_handler(text="ac:cadd", is_admin=config.PERM_CATALOG)
async def cb_cat_add(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await CategoryWizard.name.set()
    await query.message.answer(texts.MSG_CAT_ASK_NAME, reply_markup=kb.force_reply())


@dp.message_handler(state=CategoryWizard.name, is_admin=config.PERM_CATALOG)
async def cat_name_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    name = (message.text or "").strip()
    if not name:
        return
    # Optional leading emoji: first token if it looks like emoji.
    emoji = "\U0001f4e6"
    parts = name.split(maxsplit=1)
    if len(parts) == 2 and len(parts[0]) <= 4 and not parts[0][0].isalnum():
        emoji, name = parts[0], parts[1]
    await db.add_category(name, emoji)
    await db.audit(message.from_user.id, "category_add", name)
    await state.finish()
    await message.answer(texts.MSG_CAT_CREATED.format(name=html.escape(name)))
    # Back to list via a synthetic refresh:
    cats = await db.list_categories()
    lines = []
    for c in cats:
        n = await db.count_products_in_category(c["id"])
        lines.append(texts.MSG_CAT_LINE.format(emoji=html.escape(c["emoji"]), name=html.escape(c["name"]), n=n))
    await message.answer(texts.MSG_CAT_LIST.format(lines="\n".join(lines) or "\u2014"),
                         reply_markup=kb.admin_categories_kb(cats))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:cren:"),
                           is_admin=config.PERM_CATALOG)
async def cb_cat_rename(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    cid = int(query.data.split(":")[2])
    cat = await db.get_category(cid)
    await state.update_data(rename_cid=cid)
    await CategoryWizard.rename.set()
    await query.message.answer(texts.MSG_CAT_ASK_RENAME.format(name=cat["name"]),
                               reply_markup=kb.force_reply())


@dp.message_handler(state=CategoryWizard.rename, is_admin=config.PERM_CATALOG)
async def cat_rename_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    name = (message.text or "").strip()
    data = await state.get_data()
    await db.rename_category(data["rename_cid"], name)
    await db.audit(message.from_user.id, "category_rename", f"id={data['rename_cid']} name={name}")
    await state.finish()
    await message.answer(texts.MSG_CAT_RENAMED.format(name=name))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:cdel:"),
                           is_admin=config.PERM_CATALOG)
async def cb_cat_delete_ask(query: types.CallbackQuery):
    await query.answer()
    cid = int(query.data.split(":")[2])
    n = await db.count_products_in_category(cid)
    if n:
        await query.answer(texts.MSG_CAT_DELETE_GUARD.format(n=n), show_alert=True)
        return
    await edit_text_safe(
        query, f"\U0001f5d1\ufe0f <b>Delete this category?</b>",
        kb.confirm_generic_kb(f"ac:cdely:{cid}", f"ac:cl:{cid}"))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:cdely:"),
                           is_admin=config.PERM_CATALOG)
async def cb_cat_delete_yes(query: types.CallbackQuery):
    cid = int(query.data.split(":")[2])
    await db.delete_category(cid)
    await db.audit(query.from_user.id, "category_delete", f"id={cid}")
    await query.answer(texts.MSG_CAT_DELETED)
    cats = await db.list_categories()
    lines = []
    for c in cats:
        n = await db.count_products_in_category(c["id"])
        lines.append(texts.MSG_CAT_LINE.format(emoji=c["emoji"], name=c["name"], n=n))
    await edit_text_safe(query, texts.MSG_CAT_LIST.format(lines="\n".join(lines) or "\u2014"),
                         kb.admin_categories_kb(cats))


# -------------------------------------------------------------- products ---
@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:plist:"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_list(query: types.CallbackQuery):
    await query.answer()
    _, _, cid_s, page_s = query.data.split(":")
    cid, page = int(cid_s), int(page_s)
    total = await db.count_products_in_category(cid)
    page, _ = paginate(total, page, PER_PAGE)
    items = await db.list_all_products_in_category(cid, PER_PAGE, page * PER_PAGE)
    cat = await db.get_category(cid)
    text = f"\U0001f4e6 <b>{html.escape(cat['name'])}</b> \u2014 products"
    await edit_text_safe(query, text, kb.admin_products_kb(items, cid, page, total, PER_PAGE))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:padd"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_add(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    parts = query.data.split(":")
    cid = int(parts[2]) if len(parts) > 2 else 0
    await state.update_data(pw_category=cid)
    await ProductWizard.name.set()
    await query.message.answer(texts.MSG_PROD_WIZ_NAME, reply_markup=kb.force_reply())


@dp.message_handler(state=ProductWizard.name, is_admin=config.PERM_CATALOG)
async def pw_name(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    name = (message.text or "").strip()
    if not name:
        return
    await state.update_data(pw_name=name)
    await ProductWizard.description.set()
    await message.answer(texts.MSG_PROD_WIZ_DESC, reply_markup=kb.force_reply())


@dp.message_handler(state=ProductWizard.description, is_admin=config.PERM_CATALOG)
async def pw_description(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    desc = (message.text or "").strip()
    await state.update_data(pw_description="" if desc == "-" else desc)
    await ProductWizard.photo.set()
    await message.answer(texts.MSG_PROD_WIZ_PHOTO, reply_markup=kb.force_reply())


@dp.message_handler(content_types=types.ContentType.PHOTO, state=ProductWizard.photo, is_admin=config.PERM_CATALOG)
async def pw_photo(message: types.Message, state: FSMContext):
    await state.update_data(pw_photo=message.photo[-1].file_id)
    await ProductWizard.price.set()
    await message.answer(texts.MSG_PROD_WIZ_PRICE.format(currency=config.CURRENCY),
                         reply_markup=kb.force_reply())


@dp.message_handler(state=ProductWizard.photo, is_admin=config.PERM_CATALOG)
async def pw_photo_text(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    if (message.text or "").strip() == "-":
        await state.update_data(pw_photo=None)
        await ProductWizard.price.set()
        await message.answer(texts.MSG_PROD_WIZ_PRICE.format(currency=config.CURRENCY),
                             reply_markup=kb.force_reply())
    else:
        await message.answer(texts.MSG_PROD_WIZ_PHOTO, reply_markup=kb.force_reply())


def _parse_price(text: str):
    try:
        amount = Decimal(text.replace(",", ".").strip())
        cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return cents if cents > 0 else None


@dp.message_handler(state=ProductWizard.price, is_admin=config.PERM_CATALOG)
async def pw_price(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    cents = _parse_price(message.text or "")
    if cents is None:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    await state.update_data(pw_price=cents)
    await ProductWizard.kind.set()
    kbd = InlineKeyboardMarkup()
    kbd.row(
        InlineKeyboardButton("\U0001f4e6 Physical", callback_data="pwk:physical"),
        InlineKeyboardButton("\u267e\ufe0f Digital", callback_data="pwk:digital"),
    )
    await message.answer(texts.MSG_PROD_WIZ_KIND, reply_markup=kbd)


@dp.callback_query_handler(text=["pwk:physical", "pwk:digital"],
                           state=ProductWizard.kind,
                           is_admin=config.PERM_CATALOG)
async def pw_kind(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    kind = query.data.split(":")[1]
    await state.update_data(pw_kind=kind)
    if kind == "digital":
        await ProductWizard.values.set()
        await query.message.answer(texts.MSG_PROD_WIZ_VALUES,
                                   reply_markup=kb.force_reply())
    else:
        await ProductWizard.stock.set()
        await query.message.answer(texts.MSG_PROD_WIZ_STOCK,
                                   reply_markup=kb.force_reply())


@dp.message_handler(state=ProductWizard.stock, is_admin=config.PERM_CATALOG)
async def pw_stock(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    try:
        stock = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    if stock < 0:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    await state.update_data(pw_stock=stock, pw_values=[])
    await _pw_choose_category(message, state)


@dp.message_handler(state=ProductWizard.values, is_admin=config.PERM_CATALOG)
async def pw_values(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    raw = (message.text or "").strip()
    if raw == "-":
        values = []
    else:
        values = [l.strip() for l in raw.splitlines()]
        if any(not l for l in values) or len(values) != len(set(values)):
            await message.answer(texts.ERR_INVALID_QTY)
            return
    await state.update_data(pw_stock=-1, pw_values=values)
    data_kind = (await state.get_data()).get("pw_kind")
    if data_kind == "digital":
        await ProductWizard.unlimited.set()
        kb = InlineKeyboardMarkup(row_width=2)
        kb.insert(InlineKeyboardButton("♾ Unlimited (no keys needed)", callback_data="pwu:1"))
        kb.insert(InlineKeyboardButton("🔑 Key-based (deliver keys)", callback_data="pwu:0"))
        await message.answer("Is this digital product unlimited (delivered without keys)?", reply_markup=kb)
        return
    await _pw_choose_category(message, state)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("pwu:"),
                           state=ProductWizard.unlimited,
                           is_admin=config.PERM_CATALOG)
async def pw_unlimited(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await state.update_data(pw_unlimited=1 if query.data.split(":")[1] == "1" else 0)
    await _pw_choose_category(query.message, state)


async def _pw_choose_category(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("pw_category"):
        await _pw_confirm(message, state)
        return
    await ProductWizard.category.set()
    cats = await db.list_categories()
    kbd = InlineKeyboardMarkup()
    for c in cats:
        kbd.add(InlineKeyboardButton(f"{c['emoji']} {c['name']}",
                                     callback_data=f"pwc:{c['id']}"))
    await message.answer(texts.MSG_PROD_WIZ_CATEGORY, reply_markup=kbd)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("pwc:"),
                           state=ProductWizard.category,
                           is_admin=config.PERM_CATALOG)
async def pw_category(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await state.update_data(pw_category=int(query.data.split(":")[1]))
    await _pw_confirm(query.message, state)


async def _pw_confirm(message: types.Message, state: FSMContext):
    await ProductWizard.confirm.set()
    data = await state.get_data()
    cat = await db.get_category(data["pw_category"])
    summary = (
        f"<b>{html.escape(data['pw_name'])}</b>\n{html.escape(data['pw_description'] or '')}\n\n"
        f"\U0001f4b0 {fmt_money(data['pw_price'], config.CURRENCY)}\n"
        f"\U0001f4e6 {data['pw_kind']} \u00b7 stock: {data['pw_stock']}"
        f" \u00b7 keys: {len(data.get('pw_values') or [])}\n"
        f"\U0001f4c1 {html.escape(cat['name']) if cat else '?'}"
    )
    kbd = InlineKeyboardMarkup()
    kbd.row(
        InlineKeyboardButton(texts.BTN_CANCEL, callback_data="pw:no"),
        InlineKeyboardButton(texts.BTN_CONFIRM, callback_data="pw:yes"),
    )
    await message.answer(texts.MSG_PROD_WIZ_CONFIRM.format(summary=summary),
                         reply_markup=kbd)


@dp.callback_query_handler(text=["pw:yes", "pw:no"], state=ProductWizard.confirm, is_admin=config.PERM_CATALOG)
async def pw_confirm(query: types.CallbackQuery, state: FSMContext):
    if query.data == "pw:no":
        await state.finish()
        await query.answer()
        await query.message.answer(texts.MSG_WIZARD_CANCELLED)
        return
    data = await state.get_data()
    # The category could have been deleted between selection and confirmation.
    cat = await db.get_category(data["pw_category"])
    if not cat:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        await state.finish()
        return
    pid = await db.add_product(
        category_id=data["pw_category"], name=data["pw_name"],
        description=data.get("pw_description", ""),
        photo_file_id=data.get("pw_photo"), price_cents=data["pw_price"],
        kind=data["pw_kind"], stock=data.get("pw_stock", -1),
        is_unlimited=data.get("pw_unlimited", 0))
    if data.get("pw_values"):
        await db.add_product_values(pid, data["pw_values"])
    await db.audit(query.from_user.id, "product_add", f"id={pid} name={data['pw_name']}")
    await state.finish()
    await query.answer()
    await query.message.answer(texts.MSG_PROD_CREATED.format(name=data["pw_name"]))


# ------------------------------------------------------- product manage ---
@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:p:"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_detail(query: types.CallbackQuery):
    await query.answer()
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    if not p:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    unused = await db.unused_values_count(pid) if p["kind"] == "digital" else 0
    extra = f" \u00b7 unlimited: {'yes' if p['is_unlimited'] else 'no'}" if p["kind"] == "digital" else ""
    text = (f"<b>{html.escape(p['name'])}</b> (#{p['id']})\n"
            f"\U0001f4b0 {fmt_money(p['price_cents'], config.CURRENCY)}\n"
            f"\U0001f4e6 {p['kind']} \u00b7 stock: {p['stock']} \u00b7 keys unused: {unused}{extra}\n"
            f"{'active' if p['is_active'] else 'hidden'}")
    await edit_text_safe(query, text, kb.admin_product_kb(p))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:ptog:"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_toggle(query: types.CallbackQuery):
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    await db.update_product(pid, is_active=0 if p["is_active"] else 1)
    await db.audit(query.from_user.id, "product_toggle", f"id={pid}")
    await query.answer(texts.TOAST_SAVED)
    # re-render
    p = await db.get_product(pid)
    unused = await db.unused_values_count(pid) if p["kind"] == "digital" else 0
    extra = f" \u00b7 unlimited: {'yes' if p['is_unlimited'] else 'no'}" if p["kind"] == "digital" else ""
    text = (f"<b>{html.escape(p['name'])}</b> (#{p['id']})\n"
            f"\U0001f4b0 {fmt_money(p['price_cents'], config.CURRENCY)}\n"
            f"\U0001f4e6 {p['kind']} \u00b7 stock: {p['stock']} \u00b7 keys unused: {unused}{extra}\n"
            f"{'active' if p['is_active'] else 'hidden'}")
    await edit_text_safe(query, text, kb.admin_product_kb(p))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:pul:"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_unlimited_toggle(query: types.CallbackQuery):
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    await db.update_product(pid, is_unlimited=0 if p["is_unlimited"] else 1)
    await db.audit(query.from_user.id, "product_unlimited_toggle", f"id={pid}")
    await query.answer(texts.TOAST_SAVED)
    p = await db.get_product(pid)
    unused = await db.unused_values_count(pid) if p["kind"] == "digital" else 0
    extra = f" \u00b7 unlimited: {'yes' if p['is_unlimited'] else 'no'}" if p["kind"] == "digital" else ""
    text = (f"<b>{html.escape(p['name'])}</b> (#{p['id']})\n"
            f"\U0001f4b0 {fmt_money(p['price_cents'], config.CURRENCY)}\n"
            f"\U0001f4e6 {p['kind']} \u00b7 stock: {p['stock']} \u00b7 keys unused: {unused}{extra}\n"
            f"{'active' if p['is_active'] else 'hidden'}")
    await edit_text_safe(query, text, kb.admin_product_kb(p))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:pdel:"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_del_ask(query: types.CallbackQuery):
    await query.answer()
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    await edit_text_safe(
        query, texts.MSG_PROD_DELETE_ASK.format(name=html.escape(p["name"])),
        kb.confirm_generic_kb(f"ac:pdely:{pid}", f"ac:p:{pid}"))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:pdely:"),
                           is_admin=config.PERM_CATALOG)
async def cb_product_del_yes(query: types.CallbackQuery):
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    cid = p["category_id"] if p else 0
    await db.delete_product(pid)
    await db.audit(query.from_user.id, "product_delete", f"id={pid}")
    await query.answer(texts.TOAST_DELETED)
    # Return to the product list of the deleted product's category,
    # not the top-level category list.
    cat = await db.get_category(cid)
    if not cat:
        await edit_text_safe(query, texts.MSG_CAT_LIST.format(lines=""),
                             kb.admin_categories_kb(await db.list_categories()))
        return
    total = await db.count_products_in_category(cid)
    page, _ = paginate(total, 0, PER_PAGE)
    items = await db.list_all_products_in_category(cid, PER_PAGE, 0)
    text = f"\U0001f4e6 <b>{html.escape(cat['name'])}</b> \u2014 products"
    await edit_text_safe(query, text,
                         kb.admin_products_kb(items, cid, page, total, PER_PAGE))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:ppr:"),
                           is_admin=config.PERM_CATALOG)
async def cb_price_ask(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    await state.update_data(edit_pid=pid)
    await ProductPriceEdit.value.set()
    await query.message.answer(
        texts.MSG_PROD_ASK_PRICE.format(currency=config.CURRENCY, name=html.escape(p["name"])),
        reply_markup=kb.force_reply())


@dp.message_handler(state=ProductPriceEdit.value, is_admin=config.PERM_CATALOG)
async def price_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    cents = _parse_price(message.text or "")
    if cents is None:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    data = await state.get_data()
    await db.update_product(data["edit_pid"], price_cents=cents)
    await db.audit(message.from_user.id, "product_price",
                   f"id={data['edit_pid']} cents={cents}")
    await state.finish()
    await message.answer(texts.MSG_PROD_PRICE_SET.format(
        price=fmt_money(cents, config.CURRENCY)))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:pst:"),
                           is_admin=config.PERM_CATALOG)
async def cb_stock_ask(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    pid = int(query.data.split(":")[2])
    p = await db.get_product(pid)
    await state.update_data(edit_pid=pid)
    await ProductStockEdit.value.set()
    await query.message.answer(texts.MSG_PROD_ASK_STOCK.format(name=html.escape(p["name"])),
                               reply_markup=kb.force_reply())


@dp.message_handler(state=ProductStockEdit.value, is_admin=config.PERM_CATALOG)
async def stock_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    try:
        stock = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    data = await state.get_data()
    p = await db.get_product(data["edit_pid"])
    if p and p["kind"] != "digital" and stock < 0:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    await db.update_product(data["edit_pid"], stock=stock)
    await db.audit(message.from_user.id, "product_stock",
                   f"id={data['edit_pid']} stock={stock}")
    await state.finish()
    await message.answer(texts.MSG_PROD_STOCK_SET)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:pv:"),
                           is_admin=config.PERM_CATALOG)
async def cb_values_ask(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    pid = int(query.data.split(":")[2])
    await state.update_data(edit_pid=pid)
    await ProductValuesAdd.values.set()
    await query.message.answer(texts.MSG_PROD_ASK_VALUES,
                               reply_markup=kb.force_reply())


@dp.message_handler(state=ProductValuesAdd.values, is_admin=config.PERM_CATALOG)
async def values_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    values = [l.strip() for l in (message.text or "").splitlines()]
    if any(not l for l in values) or len(values) != len(set(values)):
        await message.answer(texts.ERR_INVALID_QTY)
        return
    data = await state.get_data()
    await db.add_product_values(data["edit_pid"], values)
    total = await db.unused_values_count(data["edit_pid"])
    await db.audit(message.from_user.id, "product_values",
                   f"id={data['edit_pid']} added={len(values)}")
    await state.finish()
    await message.answer(texts.MSG_PROD_VALUES_ADDED.format(n=len(values), total=total))
