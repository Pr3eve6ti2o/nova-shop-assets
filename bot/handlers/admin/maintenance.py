"""Admin maintenance-mode toggle."""
from aiogram import types

import config
import keyboards as kb
import texts
from loader import db, dp
from ..common import edit_text_safe
from . import IsAdmin


@dp.callback_query_handler(text="ad:mnt", is_admin=config.PERM_MAINTENANCE, state="*")
async def cb_maint_home(query: types.CallbackQuery):
    await query.answer()
    is_on = await db.maintenance_on()
    await edit_text_safe(query, texts.MSG_MAINT_ASK, kb.maintenance_kb(is_on))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("mnt:"),
                           is_admin=config.PERM_MAINTENANCE, state="*")
async def cb_maint_toggle(query: types.CallbackQuery):
    # Audit 20261015 06-admin: strict parse — any value other than
    # exactly "1"/"0" used to mean OFF, so a malformed or replayed
    # callback could silently flip the global kill-switch off.
    parts = query.data.split(":")
    if len(parts) != 2 or parts[1] not in ("1", "0"):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    turn_on = parts[1] == "1"
    await db.kv_set("maintenance_mode", "1" if turn_on else "0")
    await db.audit(query.from_user.id, "maintenance",
                   "on" if turn_on else "off")
    await query.answer(texts.TOAST_MAINT_ON if turn_on else texts.TOAST_MAINT_OFF)
    await edit_text_safe(query, texts.MSG_MAINT_ASK, kb.maintenance_kb(turn_on))
