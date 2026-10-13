"""/admin console + stats dashboard (permission-filtered)."""
from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import db, dp
from utils import fmt_money
from ..common import get_or_register, edit_text_safe, main_reply_kb
from . import mask_of


async def render_console(query_or_msg, tg_id: int):
    mask = await mask_of(tg_id)
    # Opus F13 (P0): defense in depth — never render the console for
    # non-admins even if a caller forgets to check.
    if not mask:
        if isinstance(query_or_msg, types.CallbackQuery):
            await query_or_msg.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
        else:
            await query_or_msg.answer(texts.MSG_ADMIN_DENIED)
        return
    maintenance = await db.maintenance_on()
    text = texts.MSG_ADMIN_CONSOLE.format(
        maintenance_banner=texts.MSG_MAINT_BANNER if maintenance else "")
    markup = kb.admin_console_kb(mask, maintenance)
    if isinstance(query_or_msg, types.CallbackQuery):
        await edit_text_safe(query_or_msg, text, markup)
    else:
        await query_or_msg.answer(text, reply_markup=markup,
                                  disable_web_page_preview=True)


@dp.message_handler(commands=["admin"], state="*")
async def cmd_admin(message: types.Message, state: FSMContext):
    # Opus P1: state="*" + finish() — an admin stuck mid-flow (e.g. broadcast
    # compose) was locked out of /admin, and abandoned flows could misapply
    # later input (e.g. a refund amount) to the wrong operation.
    try:
        await state.finish()
    except Exception:
        pass
    user, _ = await get_or_register(message.from_user.id, message.from_user.full_name)
    if not await mask_of(message.from_user.id):
        await message.answer(texts.MSG_ADMIN_DENIED,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return
    await render_console(message, message.from_user.id)


@dp.message_handler(text=texts.BTN_ADMIN, state="*")
async def btn_admin(message: types.Message, state: FSMContext):
    await cmd_admin(message, state)


@dp.callback_query_handler(text="adm", state="*")
async def cb_admin(query: types.CallbackQuery):
    if not await mask_of(query.from_user.id):
        await query.answer(texts.MSG_ADMIN_DENIED, show_alert=True)
        return
    await query.answer()
    await render_console(query, query.from_user.id)


@dp.callback_query_handler(text="ad:st", is_admin=config.PERM_STATS, state="*")
async def cb_stats(query: types.CallbackQuery):
    await query.answer()
    total = await db.count_users()
    new24 = await db.count_new_users_24h()
    blocked = await db.count_blocked_users()
    rev14, orders14 = await db.revenue(days=14)
    rev_total, _ = await db.revenue()
    avg = await db.avg_check()
    counts = await db.orders_by_status_counts()
    by_status = "\n".join(
        f"{texts.STATUS_EMOJI.get(s, '')} {texts.STATUS_LABEL.get(s, s)}: <b>{counts.get(s, 0)}</b>"
        for s in texts.ORDER_STATUSES)
    top = await db.top_products(5)
    # Opus: HTML-escape product names — unescaped names with <>& break
    # Telegram's HTML parsing and fail the stats message.
    from html import escape as _escape
    top_lines = "\n".join(
        f"\u2022 {_escape(str(t['name']))} \u2014 {t['qty']} sold ({fmt_money(t['revenue'], config.CURRENCY)})"
        for t in top) or "\u2014"
    # Port 6.6: daily revenue for the last 7 days (DoktorShift pattern).
    daily = await db.revenue_by_day(7)
    daily_lines = "\n".join(
        f"\u2022 {d['day']}: {fmt_money(d['cents'], config.CURRENCY)} "
        f"({d['n']} orders)" for d in daily) or "\u2014"
    text = texts.MSG_ADMIN_STATS.format(
        total=total, new24=new24, blocked=blocked,
        rev14=fmt_money(rev14, config.CURRENCY), orders14=orders14,
        rev_total=fmt_money(rev_total, config.CURRENCY),
        avg_check=fmt_money(avg, config.CURRENCY),
        by_status=by_status, top=top_lines)
    text += f"\n\n\U0001f4c5 <b>Revenue by day (last 7 days)</b>\n{daily_lines}"
    back = kb.InlineKeyboardMarkup()
    back.row(kb.InlineKeyboardButton(texts.BTN_BACK, callback_data="adm"))
    await edit_text_safe(query, text, back)
