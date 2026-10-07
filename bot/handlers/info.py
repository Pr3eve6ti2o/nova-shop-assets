"""Info: about the bot/team."""
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

# Note: the Rent button (texts.BTN_RENT) is owned by bot/handlers/rent.py,
# which renders live plans from the control plane. (The old static rent
# page was removed to avoid two handlers racing on the same button.)
