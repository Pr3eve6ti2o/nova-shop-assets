"""Merchant tooling (port plan Part 6): payment review queue, refunds,
provider status.

/payreview — quarantined payments (money that arrived but could not be
attached to an order). Settle = credit the customer's balance by an
admin-entered amount with a mandatory audit note; dismiss also needs a
note. The anomaly row is claimed (status flip) BEFORE any money moves.

/refund — two-tap full refund of an order to the customer's balance,
guarded by the refunds ledger (never more than the order total).

/providers — read-only rail status from config (no secrets shown).

Gated by PERM_ORDERS (providers: PERM_STATS).
"""
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import texts
from loader import bot, db, dp
from states import AdminPayreviewFlow, AdminRefundFlow
from utils import fmt_money
from handlers.balance import _parse_usd_to_cents


# ------------------------------------------------------------- payreview
def _anomaly_kb(a):
    kb = InlineKeyboardMarkup(row_width=2)
    if a["status"] == "open":
        kb.add(InlineKeyboardButton(
            "💸 Settle (credit balance)",
            callback_data=f"ad:pr:set:{a['id']}"),
            InlineKeyboardButton(
                "🗑 Dismiss", callback_data=f"ad:pr:dis:{a['id']}"))
    kb.add(InlineKeyboardButton("⬅️ Review queue", callback_data="ad:pr:list"))
    return kb


async def _render_queue(target):
    rows = await db.anomalies_open(limit=15)
    if not rows:
        text = "🔍 <b>Payment review</b>\n\nQueue is empty — every payment found its order. 🎉"
        kb = None
    else:
        text = ("🔍 <b>Payment review</b>\n\nPayments that arrived but "
                "couldn't be attached to an order. Oldest first.")
        kb = InlineKeyboardMarkup(row_width=1)
        for a in rows:
            kb.add(InlineKeyboardButton(
                f"#{a['id']} · {a['provider']} · "
                f"{a['amount_text'] or 'amount unknown'}",
                callback_data=f"ad:pr:v:{a['id']}"))
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@dp.message_handler(commands=["payreview"], is_admin=config.PERM_ORDERS,
                    state="*")
async def cmd_payreview(message: types.Message, state: FSMContext):
    await state.finish()
    await _render_queue(message)


@dp.callback_query_handler(lambda q: q.data in ("ad:pr:list",),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_queue(query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await query.answer()
    await _render_queue(query)


async def _render_anomaly(query, aid: int):
    a = await db.anomaly_get(aid)
    if not a:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    lines = [f"🔍 <b>Anomaly #{a['id']}</b> — {a['status']}",
             f"Provider: {a['provider']}",
             f"Amount: {a['amount_text'] or '—'}"
             + (f" ({fmt_money(a['amount_cents'])})"
                if a["amount_cents"] else ""),
             f"External id: <code>{a['external_id'] or '—'}</code>",
             f"Recorded: {a['created_at']}",
             f"\n<b>Why it's here:</b>\n{a['reason']}"]
    if a["raw"]:
        lines.append(f"\n<code>{a['raw'][:300]}</code>")
    resolutions = await db.anomaly_resolutions(aid)
    for r in resolutions:
        lines.append(f"\n— {r['action']} by admin {r['admin_id']}: "
                     f"{r['note']}")
    await query.answer()
    try:
        await query.message.edit_text("\n".join(lines),
                                      reply_markup=_anomaly_kb(a))
    except Exception:
        await query.message.answer("\n".join(lines),
                                   reply_markup=_anomaly_kb(a))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:pr:v:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_anomaly_view(query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await _render_anomaly(query, int(query.data.split(":")[3]))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:pr:set:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_settle_start(query: types.CallbackQuery, state: FSMContext):
    aid = int(query.data.split(":")[3])
    a = await db.anomaly_get(aid)
    if not a or a["status"] != "open":
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await AdminPayreviewFlow.settle_amount.set()
    await state.update_data(settle_anomaly=aid)
    await query.answer()
    await bot.send_message(
        query.from_user.id,
        f"💸 Settling anomaly #{aid} — how much should be credited to "
        "the customer's balance, in USD? (e.g. 12.50)")


@dp.message_handler(state=AdminPayreviewFlow.settle_amount,
                    is_admin=config.PERM_ORDERS)
async def msg_settle_amount(message: types.Message, state: FSMContext):
    cents = _parse_usd_to_cents(message.text or "")
    if not cents:
        return await message.answer("⚠️ Enter a valid amount, e.g. 12.50")
    await state.update_data(settle_cents=cents)
    await AdminPayreviewFlow.settle_note.set()
    await message.answer(
        "📝 Now the audit note — what was this payment and why is it "
        "being credited? (required)")


@dp.message_handler(state=AdminPayreviewFlow.settle_note,
                    is_admin=config.PERM_ORDERS)
async def msg_settle_note(message: types.Message, state: FSMContext):
    data = await state.get_data()
    aid, cents = data.get("settle_anomaly"), data.get("settle_cents")
    note = (message.text or "").strip()
    await state.finish()
    if not aid or not cents or not note:
        return await message.answer(texts.ERR_GENERIC)
    admin = await db.get_user_by_tg(message.from_user.id)
    # Claim FIRST: if the flip fails, no money moves.
    if not await db.anomaly_resolve(aid, admin["id"] if admin else 0,
                                    "settled", note=note,
                                    amount_cents=cents):
        return await message.answer("⚠️ Already resolved by someone else.")
    a = await db.anomaly_get(aid)
    credited = False
    if a and a["user_id"]:
        await db.add_balance(a["user_id"], cents,
                             tx_type="anomaly_credit")
        credited = True
        customer = await db.get_user(a["user_id"])
        if customer:
            try:
                await bot.send_message(
                    customer["tg_id"],
                    f"💸 <b>Good news</b>\n\nWe found your payment and "
                    f"credited {fmt_money(cents, config.CURRENCY)} to your "
                    "balance. Sorry for the wait.")
            except Exception:
                pass
    await message.answer(
        f"✅ Anomaly #{aid} settled — {fmt_money(cents, config.CURRENCY)}"
        + (" credited to the customer." if credited
           else " recorded (no customer attached)."))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:pr:dis:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_dismiss_start(query: types.CallbackQuery, state: FSMContext):
    aid = int(query.data.split(":")[3])
    a = await db.anomaly_get(aid)
    if not a or a["status"] != "open":
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    await AdminPayreviewFlow.dismiss_note.set()
    await state.update_data(dismiss_anomaly=aid)
    await query.answer()
    await bot.send_message(
        query.from_user.id,
        f"🗑 Dismissing anomaly #{aid} — type the reason (it stays on "
        "the record).")


@dp.message_handler(state=AdminPayreviewFlow.dismiss_note,
                    is_admin=config.PERM_ORDERS)
async def msg_dismiss_note(message: types.Message, state: FSMContext):
    data = await state.get_data()
    aid = data.get("dismiss_anomaly")
    note = (message.text or "").strip()
    await state.finish()
    if not aid or not note:
        return await message.answer(texts.ERR_GENERIC)
    admin = await db.get_user_by_tg(message.from_user.id)
    if await db.anomaly_resolve(aid, admin["id"] if admin else 0,
                                 "dismissed", note=note):
        await message.answer(f"🗑 Anomaly #{aid} dismissed.")
    else:
        await message.answer("⚠️ Already resolved by someone else.")


# ---------------------------------------------------------------- refund
@dp.message_handler(commands=["refund"], is_admin=config.PERM_ORDERS,
                    state="*")
async def cmd_refund(message: types.Message, state: FSMContext):
    await AdminRefundFlow.order_id.set()
    await message.answer(
        "💸 <b>Refund an order</b>\n\nType the order id. You'll see the "
        "order and its refund history before anything is credited.")


@dp.message_handler(state=AdminRefundFlow.order_id,
                    is_admin=config.PERM_ORDERS)
async def msg_refund_order(message: types.Message, state: FSMContext):
    await state.finish()
    try:
        oid = int((message.text or "").strip())
    except ValueError:
        return await message.answer("⚠️ That isn't an order id.")
    order = await db.get_order(oid)
    if not order:
        return await message.answer(texts.ERR_NOT_FOUND)
    refunds = await db.refunds_for_order(oid)
    already = sum(int(r["amount_cents"]) for r in refunds)
    remaining = int(order["total_cents"]) - already
    lines = [f"💸 <b>Refund order #{oid}</b>",
             f"Status: {order['status']} · total "
             f"{fmt_money(order['total_cents'], config.CURRENCY)}",
             f"Already refunded: {fmt_money(already, config.CURRENCY)}",
             f"Refundable now: {fmt_money(remaining, config.CURRENCY)}"]
    kb = InlineKeyboardMarkup()
    if remaining > 0 and order["status"] != "refunded":
        kb.add(InlineKeyboardButton(
            f"✅ Credit {fmt_money(remaining, config.CURRENCY)} to balance",
            callback_data=f"ad:rf:go:{oid}"))
    await message.answer("\n".join(lines), reply_markup=kb)


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("ad:rf:go:"),
                           is_admin=config.PERM_ORDERS, state="*")
async def cb_refund_go(query: types.CallbackQuery):
    oid = int(query.data.split(":")[3])
    order = await db.get_order(oid)
    if not order:
        return await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
    refunds = await db.refunds_for_order(oid)
    remaining = int(order["total_cents"]) - sum(
        int(r["amount_cents"]) for r in refunds)
    if remaining <= 0:
        return await query.answer("⚠️ Nothing left to refund.",
                                  show_alert=True)
    admin = await db.get_user_by_tg(query.from_user.id)
    try:
        await db.record_refund(oid, order["user_id"], remaining, "balance",
                               admin_id=admin["id"] if admin else None,
                               note="admin /refund")
    except ValueError as e:
        return await query.answer(f"⚠️ {e}", show_alert=True)
    await db.add_balance(order["user_id"], remaining, tx_type="refund",
                         order_id=oid, actor_type="admin",
                         actor_id=query.from_user.id, note="admin /refund",
                         reference="refund", reference_id=str(oid))
    await db.set_order_status(oid, "refunded")
    await query.answer("Refunded 💸")
    customer = await db.get_user(order["user_id"])
    if customer:
        try:
            await bot.send_message(
                customer["tg_id"],
                f"💸 <b>Refund</b>\n\nOrder #{oid} — "
                f"{fmt_money(remaining, config.CURRENCY)} has been "
                "credited to your balance.")
        except Exception:
            pass
    await query.message.answer(
        f"✅ Order #{oid} refunded "
        f"{fmt_money(remaining, config.CURRENCY)} to the customer's "
        "balance.")


# -------------------------------------------------------------- providers
@dp.message_handler(commands=["providers"], is_admin=config.PERM_STATS,
                    state="*")
async def cmd_providers(message: types.Message, state: FSMContext):
    await state.finish()

    def yn(v):
        return "✅" if v else "—"

    lines = [
        "🔌 <b>Payment providers & services</b>",
        "",
        f"Telegram Payments token: {yn(config.PAYMENTS_PROVIDER_TOKEN)}",
        f"CryptoBot: {yn(config.CRYPTOBOT_TOKEN)}",
        f"BTC xpub: {yn(config.XPUB_BTC)} · ETH xpub: {yn(config.XPUB_ETH)}"
        f" · TRX xpub: {yn(config.XPUB_TRX)}",
        f"TON deposit address: {yn(config.TON_DEPOSIT_ADDRESS)}",
        f"Etherscan key: {yn(getattr(config, 'ETHERSCAN_API_KEY', None))}",
        f"Mini App URL: {yn(config.MINIAPP_URL)}",
        f"Payload CMS: {yn(getattr(config, 'PAYLOAD_URL', None))}",
        f"Rental control plane: {yn(config.NOVA_API_URL)}",
        f"Webhook mode: {'✅ ' + str(config.WEBHOOK_HOST) if config.WEBHOOK_HOST else '— (polling)'}",
        f"Watcher: {'standalone' if config.WATCHER_STANDALONE else 'in-process'}",
        f"Campaigns: {yn(config.CAMPAIGNS_ENABLED)} · "
        f"Maintenance: {yn(await db.maintenance_on())}",
        f"Open payment anomalies: {len(await db.anomalies_open(limit=100))}",
    ]
    await message.answer("\n".join(lines))
