"""Admin broadcast: compose -> preview -> send with live progress."""
import asyncio

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.utils.exceptions import RetryAfter, BotBlocked, ChatNotFound, UserDeactivated

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from states import BroadcastFlow
from ..common import edit_text_safe, handle_escape

# run flag per admin (single process): {admin_tg_id: bool}
_broadcast_running = {}


@dp.callback_query_handler(text="ad:bc", is_admin=config.PERM_BROADCAST)
async def cb_broadcast(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await BroadcastFlow.content.set()
    await query.message.answer(texts.MSG_BROADCAST_ASK, reply_markup=kb.force_reply())


@dp.message_handler(state=BroadcastFlow.content,
                    content_types=types.ContentType.ANY)
async def bc_content(message: types.Message, state: FSMContext):
    if message.text and await handle_escape(message, state):
        return
    photo = message.photo[-1].file_id if message.photo else None
    text = message.text or message.caption or ""
    if not text and not photo:
        return
    users = list(dict.fromkeys(await db.all_active_tg_ids()))
    await state.update_data(bc_text=text, bc_photo=photo, bc_tg_ids=users)
    await BroadcastFlow.confirm.set()
    if photo:
        await message.answer_photo(photo, caption=text)
    await message.answer(texts.MSG_BROADCAST_PREVIEW.format(n=len(users)),
                         reply_markup=kb.broadcast_confirm_kb())


@dp.callback_query_handler(text="bcx", state=BroadcastFlow.confirm)
async def bc_cancel(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    await state.finish()
    await edit_text_safe(query, texts.MSG_WIZARD_CANCELLED, None)


@dp.callback_query_handler(text="bcy", state=BroadcastFlow.confirm)
async def bc_send(query: types.CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    await state.finish()
    text, photo = data.get("bc_text", ""), data.get("bc_photo")
    tg_ids = data.get("bc_tg_ids", [])
    total = len(tg_ids)
    admin_id = query.from_user.id
    _broadcast_running[admin_id] = True

    progress = await query.message.answer(
        texts.MSG_BROADCAST_PROGRESS.format(done=0, total=total, errors=0),
        reply_markup=kb.broadcast_stop_kb())
    done, errors = 0, 0
    await db.audit(admin_id, "broadcast_start", f"audience={total}")

    stopped = False
    try:
        for tg_id in tg_ids:
            if not _broadcast_running.get(admin_id):
                stopped = True
                break
            try:
                if photo:
                    await bot.send_photo(tg_id, photo, caption=text)
                else:
                    await bot.send_message(tg_id, text, disable_web_page_preview=True)
                done += 1
            except RetryAfter as e:
                await asyncio.sleep(e.timeout)
                try:
                    if photo:
                        await bot.send_photo(tg_id, photo, caption=text)
                    else:
                        await bot.send_message(tg_id, text, disable_web_page_preview=True)
                    done += 1
                except Exception:
                    errors += 1
            except (BotBlocked, ChatNotFound, UserDeactivated):
                errors += 1
            except Exception:
                errors += 1
            if (done + errors) % 10 == 0:
                try:
                    await progress.edit_text(
                        texts.MSG_BROADCAST_PROGRESS.format(done=done, total=total,
                                                           errors=errors),
                        reply_markup=kb.broadcast_stop_kb())
                except Exception:
                    pass
            await asyncio.sleep(0.05)  # gentle pacing
    finally:
        _broadcast_running.pop(admin_id, None)

    if stopped:
        await progress.edit_text(
            texts.MSG_BROADCAST_STOPPED.format(done=done, total=total),
            reply_markup=None)
        await db.audit(admin_id, "broadcast_stop", f"done={done}/{total}")
    else:
        try:
            await progress.edit_text(
                texts.MSG_BROADCAST_DONE.format(done=done, errors=errors),
                reply_markup=None)
        except Exception:
            pass
        await db.audit(admin_id, "broadcast_done", f"sent={done} errors={errors}")


@dp.callback_query_handler(text="bcstop", is_admin=config.PERM_BROADCAST)
async def bc_stop(query: types.CallbackQuery):
    _broadcast_running[query.from_user.id] = False
    await query.answer(texts.TOAST_BROADCAST_STOPPED)
