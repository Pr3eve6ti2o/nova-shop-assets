"""Admin users: lookup by id, block/unblock, role bitmask."""
import html
from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import db, dp
from states import UserSearch
from utils import fmt_money
from ..common import edit_text_safe, handle_escape


@dp.callback_query_handler(text="ad:usr", is_admin=config.PERM_USERS)
async def cb_users_home(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await UserSearch.query.set()
    await query.message.answer(texts.MSG_USER_SEARCH_ASK, reply_markup=kb.force_reply())


@dp.message_handler(state=UserSearch.query)
async def user_search_received(message: types.Message, state: FSMContext):
    if await handle_escape(message, state):
        return
    try:
        tg_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(texts.MSG_USER_NOT_FOUND)
        return
    await state.finish()
    await render_user_card(message, tg_id)


async def render_user_card(target, tg_id: int):
    user = await db.get_user_by_tg(tg_id)
    if not user:
        text, markup = texts.MSG_USER_NOT_FOUND, None
    else:
        orders_n = await db.count_user_orders(user["id"])
        spent = await db.user_spent(user["id"])
        ref = await db.get_user(user["referred_by"]) if user["referred_by"] else None
        bits = [n for b, n in sorted(config.PERM_NAMES.items()) if user["role_mask"] & b]
        text = texts.MSG_USER_CARD.format(
            name=html.escape(user["name"] or "?"), tg_id=user["tg_id"], orders=orders_n,
            spent=fmt_money(spent, config.CURRENCY),
            ref=(html.escape(ref["name"]) if ref else "\u2014"),
            role=", ".join(bits) if bits else "\u2014",
            blocked="yes" if user["is_blocked"] else "no")
        markup = kb.admin_user_kb(user)
    if isinstance(target, types.CallbackQuery):
        await edit_text_safe(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:u:"),
                           is_admin=config.PERM_USERS)
async def cb_user_card(query: types.CallbackQuery):
    await query.answer()
    await render_user_card(query, int(query.data.split(":")[2]))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:ub:"),
                           is_admin=config.PERM_USERS)
async def cb_user_block(query: types.CallbackQuery):
    tg_id = int(query.data.split(":")[2])
    if str(tg_id) in {str(a) for a in config.ADMINS}:
        await query.answer("Cannot block a config admin.", show_alert=True)
        return
    if tg_id == query.from_user.id:
        await query.answer("You cannot block yourself.", show_alert=True)
        return
    user = await db.get_user_by_tg(tg_id)
    if not user:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    new_blocked = 0 if user["is_blocked"] else 1
    await db.update_user_admin(user["id"], is_blocked=new_blocked)
    await db.audit(query.from_user.id, "user_block" if new_blocked else "user_unblock",
                   f"tg_id={tg_id}")
    await query.answer(texts.TOAST_USER_BLOCKED if new_blocked else texts.TOAST_USER_UNBLOCKED)
    await render_user_card(query, tg_id)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:ur:"),
                           is_admin=config.PERM_USERS)
async def cb_role_edit(query: types.CallbackQuery):
    await query.answer()
    tg_id = int(query.data.split(":")[2])
    user = await db.get_user_by_tg(tg_id)
    if not user:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    await edit_text_safe(query, texts.MSG_ROLE_PICK.format(name=user["name"] or "?"),
                         kb.admin_role_kb(tg_id, user["role_mask"]))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:urc:"),
                           is_admin=config.PERM_USERS)
async def cb_role_toggle(query: types.CallbackQuery):
    _, _, tg_id_s, bit_s = query.data.split(":")
    tg_id, bit = int(tg_id_s), int(bit_s)
    if bit not in config.PERM_NAMES:
        await query.answer("Invalid permission bit.", show_alert=True)
        return
    if str(tg_id) in {str(a) for a in config.ADMINS}:
        await query.answer("Config admins always keep full rights.", show_alert=True)
        return
    user = await db.get_user_by_tg(tg_id)
    if not user:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    is_grant = (user["role_mask"] & bit) == 0
    if is_grant:
        actor_is_config = str(query.from_user.id) in {str(a) for a in config.ADMINS}
        if not actor_is_config:
            actor = await db.get_user_by_tg(query.from_user.id)
            if not actor or not (actor["role_mask"] & bit):
                await query.answer("You cannot grant a permission you do not have.", show_alert=True)
                return
        if tg_id == query.from_user.id:
            await query.answer("You cannot grant permissions to yourself.", show_alert=True)
            return
        if bit == config.PERM_USERS and not actor_is_config:
            await query.answer("Only config admins can delegate user management.", show_alert=True)
            return
    new_mask = user["role_mask"] ^ bit
    await db.update_user_admin(user["id"], role_mask=new_mask)
    await db.audit(query.from_user.id, "user_role", f"tg_id={tg_id} mask={new_mask}")
    await query.answer(texts.MSG_ROLE_SAVED)
    await edit_text_safe(query, texts.MSG_ROLE_PICK.format(name=user["name"] or "?"),
                         kb.admin_role_kb(tg_id, new_mask))
