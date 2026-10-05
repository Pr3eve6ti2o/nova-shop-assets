"""Balance: /balance command, top-up flow, transaction history."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from states import BalanceFlow
from utils import fmt_money
from .common import get_or_register, edit_text_safe


async def cmd_balance(message: types.Message, state: FSMContext):
    await state.finish()
    if message.chat.type != "private":
        await message.answer("Your balance is private — please open me in a private chat.")
        return
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    balance = await db.get_balance(user["id"])
    await message.answer(
        texts.MSG_BALANCE.format(balance=fmt_money(balance, config.CURRENCY)),
        reply_markup=kb.balance_kb())


@dp.callback_query_handler(text="bal:topup")
async def cb_balance_topup(query: types.CallbackQuery):
    await query.answer()
    await edit_text_safe(
        query, texts.MSG_BALANCE_TOPUP,
        kb.balance_topup_kb())


async def _start_topup_invoice(target, amount_cents: int):
    """Shared top-up invoice flow for preset and custom amounts.

    `target` is a CallbackQuery or a Message; the notice is shown by editing
    the originating message when possible.
    """
    if isinstance(target, types.CallbackQuery):
        query = target
        await query.answer(texts.MSG_BALANCE_INVOICE_CREATING)
    else:
        query = None
    user_tg = target.from_user
    user, _ = await get_or_register(user_tg.id, user_tg.full_name)
    # Create a top-up order (no product, just balance credit)
    # This reuses the CryptoBot flow via a special order
    # TODO: integrate with CryptoBot invoice creation
    # For now, direct to support
    text = texts.MSG_BALANCE_TOPUP_MANUAL
    markup = kb.balance_kb()
    if query is not None:
        await edit_text_safe(query, text, markup)
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("bal:amt:"))
async def cb_balance_amount(query: types.CallbackQuery, state: FSMContext):
    """User picked a top-up amount - create CryptoBot invoice."""
    amount_cents = int(query.data.split(":")[2])
    if amount_cents <= 0:
        # Never create invoices for zero/negative amounts, even once the
        # CryptoBot integration below is implemented.
        await query.answer(texts.ERR_INVALID_AMOUNT, show_alert=True)
        return
    await _start_topup_invoice(query, amount_cents)


@dp.callback_query_handler(text="bal:custom")
async def cb_balance_custom(query: types.CallbackQuery, state: FSMContext):
    """User tapped Custom Amount: ask them to type an amount (min $1)."""
    await query.answer()
    prev = await state.get_state()
    await state.update_data(_prev_state=prev)
    await BalanceFlow.topup_custom.set()
    await query.message.answer(
        texts.MSG_BALANCE_CUSTOM_PROMPT,
        reply_markup=types.ForceReply(input_field_placeholder="Minimum $1"))


def _parse_usd_to_cents(raw: str) -> int | None:
    """Parse '$5', '5', '5.50' -> integer cents. None if unparsable."""
    s = (raw or "").strip().lstrip("$").strip().replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if d <= 0:
        return None
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


@dp.message_handler(state=BalanceFlow.topup_custom)
async def cb_balance_custom_amount(message: types.Message, state: FSMContext):
    """User typed a custom top-up amount: validate ($1 min) and proceed."""
    cents = _parse_usd_to_cents(message.text)
    if cents is None:
        await message.answer(texts.MSG_BALANCE_CUSTOM_INVALID, parse_mode="HTML")
        return
    if cents < 100:
        await message.answer(texts.MSG_BALANCE_CUSTOM_TOO_SMALL, parse_mode="HTML")
        return
    data = await state.get_data()
    prev = data.get("_prev_state")
    if prev:
        await state.set_state(prev)
    else:
        await state.finish()
    await _start_topup_invoice(message, cents)


@dp.callback_query_handler(text="bal:topayment")
async def cb_balance_to_payment(query: types.CallbackQuery, state: FSMContext):
    """Continue to Payment: back to checkout's Step 1 when in a checkout,
    otherwise back to the balance screen."""
    from .checkout import render_payment  # local import: avoids any cycle
    await query.answer()
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    cur = await state.get_state() or ""
    prev = (await state.get_data()).get("_prev_state") or ""
    if cur.startswith("Checkout:") or prev.startswith("Checkout:"):
        await render_payment(query, state, user["id"])
    else:
        balance = await db.get_balance(user["id"])
        await edit_text_safe(
            query,
            texts.MSG_BALANCE.format(balance=fmt_money(balance, config.CURRENCY)),
            kb.balance_kb())
