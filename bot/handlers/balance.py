"""Balance: /balance command, top-up flow, transaction history."""
from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from utils import fmt_money
from .common import get_or_register, edit_text_safe


@dp.message_handler(commands=["balance"])
async def cmd_balance(message: types.Message, state: FSMContext):
    await state.finish()
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
    user, _ = await get_or_register(query.from_user.id, query.from_user.full_name)
    # Create a top-up order (no product, just balance credit)
    # This reuses the CryptoBot flow via a special order
    await query.answer(texts.MSG_BALANCE_INVOICE_CREATING)
    # TODO: integrate with CryptoBot invoice creation
    # For now, direct to support
    await edit_text_safe(
        query, texts.MSG_BALANCE_TOPUP_MANUAL,
        kb.balance_kb())
