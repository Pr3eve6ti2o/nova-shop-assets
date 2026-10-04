"""Legal commands: /terms, /privacy, /refund.

Plain-language shop policies. These are honest summaries of how the shop
operates — not legal advice.
"""
from aiogram import types

import texts
from loader import dp
from .common import get_or_register


async def _send_policy(message: types.Message, text: str):
    await get_or_register(message.from_user.id, message.from_user.full_name)
    await message.answer(text, disable_web_page_preview=True)


@dp.message_handler(commands=["terms"])
async def cmd_terms(message: types.Message):
    await _send_policy(message, texts.MSG_TERMS)


@dp.message_handler(commands=["privacy"])
async def cmd_privacy(message: types.Message):
    await _send_policy(message, texts.MSG_PRIVACY)


@dp.message_handler(commands=["refund"])
async def cmd_refund(message: types.Message):
    await _send_policy(message, texts.MSG_REFUND)
