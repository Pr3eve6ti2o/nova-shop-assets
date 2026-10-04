"""Info and Rent: about the bot/team, and feature rental plans."""
from aiogram import types
from aiogram.dispatcher import FSMContext

import keyboards as kb
import texts
from loader import dp


@dp.message_handler(text=texts.BTN_INFO)
async def nav_info(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer(
        texts.MSG_INFO,
        reply_markup=kb.info_kb(),
        disable_web_page_preview=True,
    )


@dp.message_handler(text=texts.BTN_RENT)
async def nav_rent(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer(
        texts.MSG_RENT,
        reply_markup=kb.rent_kb(),
        disable_web_page_preview=True,
    )
