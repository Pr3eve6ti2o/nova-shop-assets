"""Admin maintenance-mode toggle."""
from aiogram import types

import config
import keyboards as kb
import texts
from loader import db, dp
from ..common import edit_text_safe
from . import IsAdmin


@dp.callback_query_handler(text="ad:mnt", is_admin=config.PERM_MAINTENANCE)
async def cb_maint_home(query: types.CallbackQuery):
    await query.answer()
    is_on = await db.maintenance_on()
    await edit_text_safe(query, texts.MSG_MAINT_ASK, kb.maintenance_kb(is_on))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("mnt:"),
                           is_admin=config.PERM_MAINTENANCE)
async def cb_maint_toggle(query: types.CallbackQuery):
    turn_on = query.data.split(":")[1] == "1"
    await db.kv_set("maintenance_mode", "1" if turn_on else "0")
    await db.audit(query.from_user.id, "maintenance",
                   "on" if turn_on else "off")
    await query.answer(texts.TOAST_MAINT_ON if turn_on else texts.TOAST_MAINT_OFF)
    await edit_text_safe(query, texts.MSG_MAINT_ASK, kb.maintenance_kb(turn_on))
