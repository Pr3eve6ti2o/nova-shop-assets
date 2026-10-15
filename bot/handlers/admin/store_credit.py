"""Store credit admin workflows (Medusa borrow, plan 2026-10-14).

- Credit / Debit on the admin user card: amount -> mandatory ledger
  note -> confirm. Money moves only through db.adjust_balance, so the
  ledger carries actor/note and debits fail closed at the DB layer.
- Gift cards: create (value -> expiry days -> note), list, detail,
  revoke. Values live in db.giftcard_*; redemption is customer-side in
  handlers/balance.py.
- Manual orders ("Create order" on the user card): tap products to
  build the order, then Comp (free) or Charge balance, via
  db.create_manual_order — catalogue prices only, born confirmed.

Gated by PERM_USERS (credit/debit, manual orders) and PERM_PROMOS
(gift cards), matching the console buttons that lead here.
"""
import html

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from states import AdminCreditFlow, AdminGiftCardFlow, AdminOrderFlow
from utils import fmt_money
from ..common import edit_text_safe, handle_escape
from ..balance import _parse_usd_to_cents
from .users import render_user_card

MAX_ADJUST_CENTS = 1_000_000  # $10,000 per single adjustment / gift card
MAX_PICK_QTY = 99


def _money(cents: int) -> str:
    return fmt_money(int(cents), config.CURRENCY)


# ------------------------------------------------------------ credit/debit
@dp.callback_query_handler(
    lambda q: q.data and (q.data.startswith("ad:ucr:")
                          or q.data.startswith("ad:udb:")
                          or q.data.startswith("ad:uzero:")),
    is_admin=config.PERM_USERS, state="*")
async def cb_credit_start(query: types.CallbackQuery, state: FSMContext):
    try:
        tg_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    user = await db.get_user_by_tg(tg_id)
    if not user:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    if query.data.startswith("ad:ucr:"):
        kind = "credit"
    elif query.data.startswith("ad:uzero:"):
        kind = "zero"
    else:
        kind = "debit"
    if kind in ("debit", "zero") and int(user["balance_cents"]) <= 0:
        return await query.answer("Nothing to debit — balance is zero.",
                                  show_alert=True)
    await query.answer()
    await state.finish()
    await state.update_data(credit_tg=tg_id, credit_kind=kind)
    if kind == "zero":
        # Set-to-zero (2026-10-16 programme): no amount step — the
        # amount is the whole balance, read fresh at confirm time.
        await AdminCreditFlow.note.set()
        return await query.message.answer(
            texts.MSG_ZERO_ASK_NOTE.format(
                name=html.escape(user["name"] or "?"),
                balance=_money(user["balance_cents"])),
            reply_markup=kb.force_reply())
    await AdminCreditFlow.amount.set()
    verb = "Credit" if kind == "credit" else "Debit"
    await query.message.answer(
        texts.MSG_CREDIT_ASK_AMOUNT.format(
            emoji="➕" if kind == "credit" else "➖", verb=verb,
            name=html.escape(user["name"] or "?"),
            balance=_money(user["balance_cents"])),
        reply_markup=kb.force_reply())


@dp.message_handler(state=AdminCreditFlow.amount, is_admin=config.PERM_USERS)
async def msg_credit_amount(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    cents = _parse_usd_to_cents(message.text or "")
    if cents is None or cents > MAX_ADJUST_CENTS:
        return await message.answer(texts.ERR_INVALID_AMOUNT)
    data = await state.get_data()
    if data.get("credit_kind") == "debit":
        user = await db.get_user_by_tg(data["credit_tg"])
        if not user or cents > int(user["balance_cents"]):
            return await message.answer(
                "⚠️ That is more than the customer's balance "
                f"({_money(user['balance_cents']) if user else '—'}).")
    await state.update_data(credit_cents=cents)
    await AdminCreditFlow.note.set()
    await message.answer(texts.MSG_CREDIT_ASK_NOTE,
                         reply_markup=kb.force_reply())


@dp.message_handler(state=AdminCreditFlow.note, is_admin=config.PERM_USERS)
async def msg_credit_note(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    note = (message.text or "").strip()
    if not 1 <= len(note) <= 200:
        return await message.answer(texts.MSG_CREDIT_NOTE_INVALID)
    data = await state.get_data()
    user = await db.get_user_by_tg(data["credit_tg"])
    if not user:
        await state.finish()
        return await message.answer(texts.ERR_NOT_FOUND)
    if data["credit_kind"] == "zero":
        cents = int(user["balance_cents"])
        verb, new_balance = "Set balance to zero", _money(0)
    else:
        cents = int(data["credit_cents"])
        delta = cents if data["credit_kind"] == "credit" else -cents
        verb = "Credit" if delta > 0 else "Debit"
        new_balance = _money(int(user["balance_cents"]) + delta)
    await state.update_data(credit_note=note)
    await AdminCreditFlow.confirm.set()
    await message.answer(
        texts.MSG_CREDIT_CONFIRM.format(
            verb=verb,
            name=html.escape(user["name"] or "?"), amount=_money(cents),
            new_balance=new_balance,
            note=html.escape(note)),
        reply_markup=kb.admin_credit_confirm_kb())


@dp.callback_query_handler(text="ad:ucok", is_admin=config.PERM_USERS,
                           state=AdminCreditFlow.confirm)
async def cb_credit_confirm(query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tg_id = data.get("credit_tg")
    user = await db.get_user_by_tg(tg_id) if tg_id else None
    if not user:
        await state.finish()
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    if data["credit_kind"] == "zero":
        # Re-read at confirm time: zero means the whole CURRENT
        # balance, whatever it is now; adjust_balance fails closed
        # if it moved again underneath us.
        cents = int(user["balance_cents"])
        if cents <= 0:
            await state.finish()
            return await query.answer("Balance is already zero.",
                                      show_alert=True)
    else:
        cents = int(data["credit_cents"])
    delta = cents if data["credit_kind"] == "credit" else -cents
    new_bal = await db.adjust_balance(
        user["id"], delta,
        tx_type="admin_credit" if delta > 0 else "admin_debit",
        actor_type="admin", actor_id=query.from_user.id,
        note=data.get("credit_note"), reference="admin")
    await state.finish()
    if new_bal is None:
        return await query.answer(
            "⚠️ Debit refused — it exceeds the current balance.",
            show_alert=True)
    await query.answer("Done ✅")
    note = data.get("credit_note") or ""
    template = (texts.MSG_CREDIT_NOTIFY_CREDIT if delta > 0
                else texts.MSG_CREDIT_NOTIFY_DEBIT)
    try:
        await bot.send_message(
            user["tg_id"],
            template.format(amount=_money(cents),
                            note=html.escape(note),
                            balance=_money(new_bal)))
    except Exception:
        pass  # customer may not be reachable; the ledger is the record
    await render_user_card(query, tg_id)


@dp.callback_query_handler(text="ad:ucx", is_admin=config.PERM_USERS,
                           state="*")
async def cb_credit_cancel(query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.finish()
    await query.answer("Cancelled")
    if data.get("credit_tg"):
        await render_user_card(query, data["credit_tg"])


# -------------------------------------------------------------- gift cards
@dp.callback_query_handler(text="ad:gcl", is_admin=config.PERM_PROMOS,
                           state="*")
async def cb_giftcard_list(query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await query.answer()
    cards = await db.giftcard_list(limit=20)
    await edit_text_safe(
        query,
        "🎁 <b>Gift cards</b>\n\nTap a card for details, or create a new one.",
        kb.admin_giftcards_kb(cards))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:gc:"),
                           is_admin=config.PERM_PROMOS, state="*")
async def cb_giftcard_detail(query: types.CallbackQuery):
    try:
        card_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    card = await db.giftcard_get_by_id(card_id)
    if not card:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await query.answer()
    lines = ["🎁 <b>Gift card</b>", f"<code>{card['code']}</code>",
             f"Value: {_money(card['value_cents'])} · "
             f"Remaining: {_money(card['remaining_cents'])}",
             f"Status: {card['status']}",
             f"Expires: {card['expires_at'] or 'never'}"]
    if card["note"]:
        lines.append(f"Note: {html.escape(card['note'])}")
    if card["redeemed_by_user_id"]:
        holder = await db.get_user(card["redeemed_by_user_id"])
        if holder:
            lines.append(f"Redeemed by: {html.escape(holder['name'] or '?')} "
                         f"(id <code>{holder['tg_id']}</code>)")
    await edit_text_safe(query, "\n".join(lines), kb.admin_giftcard_kb(card))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:gcrv:"),
                           is_admin=config.PERM_PROMOS, state="*")
async def cb_giftcard_revoke(query: types.CallbackQuery):
    try:
        card_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    if await db.giftcard_revoke(card_id):
        await db.audit(query.from_user.id, "giftcard_revoke",
                       f"card {card_id}")
        await query.answer("Revoked 🗑")
    else:
        await query.answer("Already settled or revoked.", show_alert=True)
    card = await db.giftcard_get_by_id(card_id)
    if card:
        await edit_text_safe(query, "🎁 <b>Gift card</b>\n\n"
                             f"<code>{card['code']}</code>\n"
                             f"Status: {card['status']}",
                             kb.admin_giftcard_kb(card))


@dp.callback_query_handler(text="ad:gcnew", is_admin=config.PERM_PROMOS,
                           state="*")
async def cb_giftcard_new(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await state.finish()
    await AdminGiftCardFlow.amount.set()
    await query.message.answer(texts.MSG_GIFTCARD_ASK_AMOUNT,
                               reply_markup=kb.force_reply())


@dp.message_handler(state=AdminGiftCardFlow.amount,
                    is_admin=config.PERM_PROMOS)
async def msg_giftcard_amount(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    cents = _parse_usd_to_cents(message.text or "")
    if cents is None or cents > MAX_ADJUST_CENTS:
        return await message.answer(texts.ERR_INVALID_AMOUNT)
    await state.update_data(gc_cents=cents)
    await AdminGiftCardFlow.expiry.set()
    await message.answer(texts.MSG_GIFTCARD_ASK_EXPIRY,
                         reply_markup=kb.force_reply())


@dp.message_handler(state=AdminGiftCardFlow.expiry,
                    is_admin=config.PERM_PROMOS)
async def msg_giftcard_expiry(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    try:
        days = int((message.text or "").strip())
    except ValueError:
        days = -1
    if not 0 <= days <= 3650:
        return await message.answer(
            "⚠️ Send a whole number of days (0 = no expiry).")
    await state.update_data(gc_days=days)
    await AdminGiftCardFlow.note.set()
    await message.answer(texts.MSG_GIFTCARD_ASK_NOTE,
                         reply_markup=kb.force_reply())


@dp.message_handler(state=AdminGiftCardFlow.note, is_admin=config.PERM_PROMOS)
async def msg_giftcard_note(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    raw = (message.text or "").strip()
    note = None if raw in ("-", "") else raw[:500]
    data = await state.get_data()
    days = int(data.get("gc_days") or 0)
    card = await db.giftcard_create(
        int(data["gc_cents"]), created_by=f"admin:{message.from_user.id}",
        note=note, expires_days=days or None)
    await db.audit(message.from_user.id, "giftcard_create",
                   f"card {card['id']} value={data['gc_cents']}")
    await state.finish()
    back = InlineKeyboardMarkup()
    back.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="ad:gcl"))
    await message.answer(
        texts.MSG_GIFTCARD_CREATED.format(
            code=card["code"], amount=_money(card["value_cents"]),
            expiry_line=(f"\nExpires: {card['expires_at']}"
                         if card["expires_at"] else "")),
        reply_markup=back)


# ------------------------------------------------------------ manual order
def _pick_text(user, products, picks) -> str:
    lines = [f"🧾 <b>Create order for {html.escape(user['name'] or '?')}</b>",
             f"Customer balance: {_money(user['balance_cents'])}", ""]
    total = 0
    by_id = {p["id"]: p for p in products}
    for pid_s, qty in picks.items():
        p = by_id.get(int(pid_s))
        if not p:
            continue
        total += int(p["price_cents"]) * int(qty)
        lines.append(f"• {html.escape(p['name'])} ×{qty} — "
                     f"{_money(int(p['price_cents']) * int(qty))}")
    if picks:
        lines.append(f"\n<b>Total: {_money(total)}</b>")
    lines.append("\nTap products to add units, then choose how it is paid.")
    return "\n".join(lines)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:uord:"),
                           is_admin=config.PERM_USERS, state="*")
async def cb_manual_start(query: types.CallbackQuery, state: FSMContext):
    try:
        tg_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    user = await db.get_user_by_tg(tg_id)
    if not user:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await query.answer()
    await state.finish()
    await state.update_data(manual_tg=tg_id, picks={})
    await AdminOrderFlow.pick.set()
    products = await db.list_all_active_products(limit=50)
    await edit_text_safe(query, _pick_text(user, products, {}),
                         kb.admin_manual_pick_kb(products, {}))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:mo:"),
                           is_admin=config.PERM_USERS, state="*")
async def cb_manual(query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tg_id = data.get("manual_tg")
    if not tg_id:
        return await query.answer("This picker has expired — reopen it.",
                                  show_alert=True)
    user = await db.get_user_by_tg(tg_id)
    if not user:
        await state.finish()
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    action = query.data.split(":")[2]
    picks = dict(data.get("picks") or {})
    products = await db.list_all_active_products(limit=50)

    if action == "add":
        try:
            pid = int(query.data.split(":")[3])
        except (ValueError, IndexError):
            return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        qty = int(picks.get(str(pid), 0)) + 1
        if qty > MAX_PICK_QTY:
            return await query.answer(f"Max {MAX_PICK_QTY} per product.",
                                      show_alert=True)
        picks[str(pid)] = qty
        await state.update_data(picks=picks)
        await query.answer("Added")
        return await edit_text_safe(
            query, _pick_text(user, products, picks),
            kb.admin_manual_pick_kb(products, picks))

    if action == "clear":
        await state.update_data(picks={})
        await query.answer("Cleared")
        return await edit_text_safe(
            query, _pick_text(user, products, {}),
            kb.admin_manual_pick_kb(products, {}))

    if action in ("comp", "bal"):
        if not picks:
            return await query.answer("Pick at least one product first.",
                                      show_alert=True)
        kind = "comp" if action == "comp" else "balance"
        by_id = {p["id"]: p for p in products}
        lines, total = [], 0
        for pid_s, qty in picks.items():
            p = by_id.get(int(pid_s))
            if not p:
                continue
            total += int(p["price_cents"]) * int(qty)
            lines.append(f"• {html.escape(p['name'])} ×{qty} — "
                         f"{_money(int(p['price_cents']) * int(qty))}")
        if kind == "balance" and total > int(user["balance_cents"]):
            return await query.answer(
                f"⚠️ Total {_money(total)} exceeds the customer's "
                f"balance ({_money(user['balance_cents'])}).",
                show_alert=True)
        await state.update_data(manual_kind=kind)
        await AdminOrderFlow.confirm.set()
        await query.answer()
        return await edit_text_safe(
            query,
            f"🧾 <b>Confirm {'comp (free)' if kind == 'comp' else 'balance-charged'} "
            f"order</b>\n\nCustomer: {html.escape(user['name'] or '?')}\n"
            + "\n".join(lines) + f"\n\n<b>Total: {_money(total)}</b>",
            kb.admin_manual_confirm_kb())

    if action == "ok":
        items = [(int(pid), int(qty)) for pid, qty in picks.items()]
        order_id, reason = await db.create_manual_order(
            user["id"], items, kind=data.get("manual_kind", "comp"),
            actor_tg_id=query.from_user.id, note="admin manual order")
        await state.finish()
        if not order_id:
            msg = ("⚠️ The customer's balance no longer covers this order."
                   if reason == "insufficient_balance"
                   else f"⚠️ Could not create the order ({reason}).")
            return await query.answer(msg, show_alert=True)
        order = await db.get_order(order_id)
        if data.get("manual_kind") == "balance":
            notify = texts.MSG_MANUAL_ORDER_OK_BALANCE.format(
                oid=order_id, amount=_money(order["total_cents"]),
                balance=_money(await db.get_balance(user["id"])))
        else:
            notify = texts.MSG_MANUAL_ORDER_OK_COMP.format(oid=order_id)
        try:
            await bot.send_message(user["tg_id"], notify)
        except Exception:
            pass
        await query.answer("Order created ✅")
        back = InlineKeyboardMarkup()
        back.row(InlineKeyboardButton(
            texts.BTN_BACK, callback_data=f"ad:u:{tg_id}"))
        return await edit_text_safe(
            query,
            f"✅ <b>Order #{order_id} created</b> for "
            f"{html.escape(user['name'] or '?')} — "
            f"{'comp' if data.get('manual_kind') == 'comp' else 'charged to balance'}, "
            f"total {_money(order['total_cents'])}.",
            back)

    if action == "x":
        await state.finish()
        await query.answer("Cancelled")
        return await render_user_card(query, tg_id)

    await query.answer()
