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


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("bal:amt:"))
async def cb_balance_amount(query: types.CallbackQuery, state: FSMContext):
    """User picked a top-up amount - create CryptoBot invoice."""
    amount_cents = int(query.data.split(":")[2])
    if amount_cents <= 0:
        # Never create invoices for zero/negative amounts, even once the
        # CryptoBot integration below is implemented.
        await query.answer(texts.ERR_INVALID_AMOUNT, show_alert=True)
        return
    await state.update_data(topup_cents=amount_cents)
    await edit_text_safe(
        query,
        texts.MSG_TOPUP_METHOD.format(
            amount=fmt_money(amount_cents, config.CURRENCY)),
        kb.topup_method_kb(amount_cents))


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
    await state.update_data(topup_cents=cents)
    await message.answer(
        texts.MSG_TOPUP_METHOD.format(
            amount=fmt_money(cents, config.CURRENCY)),
        reply_markup=kb.topup_method_kb(cents), parse_mode="HTML")


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("tup:"))
async def cb_topup_method(query: types.CallbackQuery, state: FSMContext):
    from .crypto import start_topup_cryptobot, start_topup_deposit  # local import
    data = await state.get_data()
    amount = data.get("topup_cents")
    action = query.data.split(":")[1]
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    if action == "back":
        await query.answer()
        await edit_text_safe(query, texts.MSG_BALANCE_TOPUP, kb.balance_topup_kb())
        return
    if not amount or amount <= 0:
        await query.answer(texts.ERR_INVALID_AMOUNT, show_alert=True)
        return
    if action == "cryptobot":
        await start_topup_cryptobot(query, state, user, int(amount))
        return
    if action == "usdt":
        await query.answer()
        await edit_text_safe(
            query,
            texts.MSG_TOPUP_METHOD.format(
                amount=fmt_money(int(amount), config.CURRENCY)),
            kb.usdt_menu_kb(prefix="tupc"))
        return
    if action == "usdc":
        await query.answer()
        await edit_text_safe(
            query,
            texts.MSG_TOPUP_METHOD.format(
                amount=fmt_money(int(amount), config.CURRENCY)),
            kb.usdc_menu_kb(prefix="tupc"))
        return
    if action == "btc":
        await start_topup_deposit(query, state, user, int(amount), "btc")
        return
    if action == "ton":
        await start_topup_deposit(query, state, user, int(amount), "ton")
        return
    await query.answer()


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("tupc:"))
async def cb_topup_chain(query: types.CallbackQuery, state: FSMContext):
    from .crypto import start_topup_deposit
    data = await state.get_data()
    amount = data.get("topup_cents")
    chain = query.data.split(":")[1]  # e.g. usdt_base
    if not amount or amount <= 0:
        await query.answer(texts.ERR_INVALID_AMOUNT, show_alert=True)
        return
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    await start_topup_deposit(query, state, user, int(amount), chain)

