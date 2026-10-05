"""Admin promos: list, create wizard, toggle, delete."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape as html_escape

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import keyboards as kb
import texts
from loader import db, dp
from states import PromoWizard
from ..common import edit_text_safe, handle_escape


@dp.callback_query_handler(text="ad:pro", is_admin=config.PERM_PROMOS)
async def cb_promo_list(query: types.CallbackQuery):
    await query.answer()
    promos = await db.list_promos()
    await edit_text_safe(query, texts.MSG_PROMO_LIST, kb.admin_promos_kb(promos))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:pr:"),
                           is_admin=config.PERM_PROMOS)
async def cb_promo_detail(query: types.CallbackQuery):
    await query.answer()
    pid = int(query.data.split(":")[2])
    promos = {p["id"]: p for p in await db.list_promos()}
    pr = promos.get(pid)
    if not pr:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    desc = (f"{pr['value']}% off" if pr["kind"] == "percent"
            else f"fixed {pr['value']} cents off")
    text = (f"\U0001f39f\ufe0f <code>{html_escape(pr['code'])}</code>\n{desc}\n"
            f"Uses: {pr['used_count']}/{pr['max_uses'] or '\u221e'}\n"
            f"Expires: {pr['expires_at'] or '\u2014'}")
    await edit_text_safe(query, text, kb.admin_promo_kb(pr))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:prt:"),
                           is_admin=config.PERM_PROMOS)
async def cb_promo_toggle(query: types.CallbackQuery):
    pid = int(query.data.split(":")[2])
    promos = {p["id"]: p for p in await db.list_promos()}
    pr = promos.get(pid)
    if not pr:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await db.set_promo_active(pid, not pr["is_active"])
    await db.audit(query.from_user.id, "promo_toggle", f"id={pid}")
    await query.answer(texts.TOAST_SAVED)
    promos = await db.list_promos()
    await edit_text_safe(query, texts.MSG_PROMO_LIST, kb.admin_promos_kb(promos))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:prd:"),
                           is_admin=config.PERM_PROMOS)
async def cb_promo_del_ask(query: types.CallbackQuery):
    await query.answer()
    pid = int(query.data.split(":")[2])
    promos = {p["id"]: p for p in await db.list_promos()}
    pr = promos.get(pid)
    if not pr:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await edit_text_safe(
        query, texts.MSG_PROMO_ASK_DELETE.format(code=pr["code"]),
        kb.confirm_generic_kb(f"ac:prdy:{pid}", f"ac:pr:{pid}"))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ac:prdy:"),
                           is_admin=config.PERM_PROMOS)
async def cb_promo_del_yes(query: types.CallbackQuery):
    pid = int(query.data.split(":")[2])
    promos = {p["id"]: p for p in await db.list_promos()}
    pr = promos.get(pid)
    if not pr:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    if pr["used_count"]:
        await db.set_promo_active(pid, False)
        await db.audit(query.from_user.id, "promo_deactivate", f"id={pid}")
        await query.answer(texts.TOAST_SAVED)
    else:
        await db.delete_promo(pid)
        await db.audit(query.from_user.id, "promo_delete", f"id={pid}")
        await query.answer(texts.MSG_PROMO_DELETED)
    promos = await db.list_promos()
    await edit_text_safe(query, texts.MSG_PROMO_LIST, kb.admin_promos_kb(promos))


# ---------------------------------------------------------------- wizard ---
@dp.callback_query_handler(text="ac:pradd", is_admin=config.PERM_PROMOS)
async def cb_promo_add(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await PromoWizard.code.set()
    await query.message.answer(texts.MSG_PROMO_WIZ_CODE, reply_markup=kb.force_reply())


@dp.message_handler(state=PromoWizard.code, is_admin=config.PERM_PROMOS)
async def pw_code(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    code = (message.text or "").strip().upper()
    if not code or len(code) > 24 or not code.isascii() or not code.isalnum():
        await message.answer(texts.ERR_INVALID_QTY)
        return
    if await db.get_promo(code):
        await message.answer(texts.MSG_PROMO_INVALID)
        return
    await state.update_data(pr_code=code)
    await PromoWizard.kind.set()
    kbd = InlineKeyboardMarkup()
    kbd.row(
        InlineKeyboardButton("Percent %", callback_data="prw:percent"),
        InlineKeyboardButton("Fixed amount", callback_data="prw:fixed"),
    )
    await message.answer(texts.MSG_PROMO_WIZ_KIND, reply_markup=kbd)


@dp.callback_query_handler(text=["prw:percent", "prw:fixed"], state=PromoWizard.kind, is_admin=config.PERM_PROMOS)
async def pw_kind(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    kind = query.data.split(":")[1]
    await state.update_data(pr_kind=kind)
    await PromoWizard.value.set()
    hint = (texts.MSG_PROMO_WIZ_VALUE_PCT if kind == "percent"
            else texts.MSG_PROMO_WIZ_VALUE_FIXED.format(currency=config.CURRENCY))
    await query.message.answer(texts.MSG_PROMO_WIZ_VALUE.format(hint=hint),
                               reply_markup=kb.force_reply())


@dp.message_handler(state=PromoWizard.value, is_admin=config.PERM_PROMOS)
async def pw_value(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    data = await state.get_data()
    raw = (message.text or "").strip().replace(",", ".")
    try:
        if data["pr_kind"] == "percent":
            value = int(raw)
            if not 1 <= value <= 90:
                raise ValueError
        else:
            try:
                value = int((Decimal(raw) * 100).to_integral_value(
                    rounding=ROUND_HALF_UP))
            except (InvalidOperation, OverflowError, ValueError):
                raise ValueError
            if value <= 0:
                raise ValueError
    except ValueError:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    await state.update_data(pr_value=value)
    await PromoWizard.max_uses.set()
    await message.answer(texts.MSG_PROMO_WIZ_MAXUSES, reply_markup=kb.force_reply())


@dp.message_handler(state=PromoWizard.max_uses, is_admin=config.PERM_PROMOS)
async def pw_max_uses(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    try:
        max_uses = int((message.text or "").strip())
        if max_uses < 0:
            raise ValueError
    except ValueError:
        await message.answer(texts.ERR_INVALID_QTY)
        return
    await state.update_data(pr_max_uses=max_uses)
    await PromoWizard.expiry.set()
    await message.answer(texts.MSG_PROMO_WIZ_EXPIRY, reply_markup=kb.force_reply())


@dp.message_handler(state=PromoWizard.expiry, is_admin=config.PERM_PROMOS)
async def pw_expiry(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    raw = (message.text or "").strip()
    expires_at = None
    if raw != "-":
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59)
            expires_at = dt.isoformat()
        except ValueError:
            await message.answer(texts.ERR_INVALID_QTY)
            return
    await state.update_data(pr_expiry=expires_at)
    await PromoWizard.confirm.set()
    data = await state.get_data()
    desc = (f"{data['pr_value']}% off" if data["pr_kind"] == "percent"
            else f"{data['pr_value']} cents off")
    kbd = InlineKeyboardMarkup()
    kbd.row(
        InlineKeyboardButton(texts.BTN_CANCEL, callback_data="prw:no"),
        InlineKeyboardButton(texts.BTN_CONFIRM, callback_data="prw:yes"),
    )
    await message.answer(
        f"\U0001f39f\ufe0f <code>{html_escape(data['pr_code'])}</code> \u2014 {desc}\n"
        f"Max uses: {data['pr_max_uses'] or '\u221e'} \u00b7 "
        f"Expires: {data['pr_expiry'] or '\u2014'}",
        reply_markup=kbd)


@dp.callback_query_handler(text=["prw:yes", "prw:no"], state=PromoWizard.confirm, is_admin=config.PERM_PROMOS)
async def pw_confirm(query: types.CallbackQuery, state: FSMContext):
    if query.data == "prw:no":
        await state.finish()
        await query.answer()
        await query.message.answer(texts.MSG_WIZARD_CANCELLED)
        return
    data = await state.get_data()
    try:
        pid = await db.add_promo(code=data["pr_code"], kind=data["pr_kind"],
                                 value=data["pr_value"], max_uses=data["pr_max_uses"],
                                 expires_at=data["pr_expiry"])
    except Exception:
        await state.finish()
        await query.answer(texts.MSG_PROMO_INVALID, show_alert=True)
        return
    await db.audit(query.from_user.id, "promo_add", f"id={pid} code={data['pr_code']}")
    await state.finish()
    await query.answer()
    await query.message.answer(texts.MSG_PROMO_CREATED.format(code=html_escape(data["pr_code"])))
