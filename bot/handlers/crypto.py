"""Crypto payments: CryptoBot rail + self-custody direct deposits + admin panel.

Wired into checkout: payment step lists rails via crypto_payments.payment_rails();
place-order branches here for 'cryptobot' and 'direct_<chain>'.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import crypto_payments as cp
import keyboards as kb
import texts
from crypto_watcher import finalize_crypto_order
from loader import bot, db, dp
from utils import cb, fmt_money
from .common import edit_text_safe, get_or_register, notify_admins

logger = logging.getLogger(__name__)

# Manual "Check My Deposit" rate limit: 1 per 30s per user.
_last_deposit_check: dict = {}


def _ttl_line(expires_iso: str) -> str:
    try:
        exp = datetime.fromisoformat(expires_iso)
        if not exp.tzinfo:
            exp = exp.replace(tzinfo=timezone.utc)
        left = exp - datetime.now(timezone.utc)
        mins = max(0, int(left.total_seconds() // 60))
        return exp.strftime("%H:%M UTC") + f" ({mins} min left)"
    except Exception:
        return "—"


# ------------------------------------------------------- CryptoBot rail ---
async def start_cryptobot_payment(query: types.CallbackQuery, state: FSMContext,
                                  user, order_id: int, total_cents: int):
    """Create the CryptoBot invoice and show pay + check buttons."""
    fee_pct = config.CRYPTOBOT_FEE_PERCENT
    fee_cents = (int(total_cents) * fee_pct + 99) // 100
    gross_cents = int(total_cents) + fee_cents
    try:
        inv = await cp.cryptobot_create_invoice(order_id=order_id,
                                                usd_cents=total_cents)
        invoice_id = int(inv["invoice_id"])
        pay_url = inv["bot_invoice_url"]
    except Exception as e:
        logger.warning("cryptobot createInvoice failed: %s", e)
        # Don't orphan the order: cancel it and drop the stale wizard state.
        await db.set_order_status(order_id, "cancelled")
        await db.release_order_promo(order_id)  # M2: don't burn promo on unpaid cancel
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.crypto_other_methods_kb())
        await db.audit(user["tg_id"], "cryptobot_error", f"order={order_id}: {e}")
        return
    await db.create_cryptobot_invoice(order_id=order_id, invoice_id=invoice_id,
                                      asset=inv.get("asset", "USDT"),
                                      amount=str(inv.get("amount", "")))
    await db.audit(user["tg_id"], "cryptobot_invoice",
                   f"order={order_id} invoice={invoice_id}")
    await state.finish()
    await edit_text_safe(
        query,
        texts.MSG_CRYPTOBOT_CREATED.format(
            total=fmt_money(total_cents, config.CURRENCY),
            fee=fmt_money(fee_cents, config.CURRENCY),
            gross=fmt_money(gross_cents, config.CURRENCY)),
        kb.cryptobot_pay_kb(pay_url, invoice_id))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cokb:"))
async def cb_cryptobot_check(query: types.CallbackQuery):
    """"I've Paid — Check": poll CryptoBot for this invoice (named states).

    Exactly one query.answer() per path — Telegram allows a single answer
    per callback; a second one raises and swallows the informative toast.
    """
    try:
        invoice_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer()
        return
    inv = await db.get_cryptobot_invoice(invoice_id)
    if not inv:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    if inv["status"] == "paid":
        await query.answer(texts.TOAST_CRYPTO_ALREADY)
        return
    try:
        items = await cp.cryptobot_get_invoices(invoice_ids=[invoice_id])
    except Exception as e:
        logger.warning("cryptobot check failed: %s", e)
        await query.answer()  # dismiss loading; the error replaces the view
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.crypto_other_methods_kb())
        return
    paid = any(str(p.get("invoice_id")) == str(invoice_id)
               and p.get("status") == "paid" for p in items)
    if not paid:
        # still_unpaid — named state with the next action.
        await query.answer()  # dismiss loading; the status message follows
        await query.message.answer(texts.MSG_CRYPTO_STILL_UNPAID)
        return
    await db.set_cryptobot_status(invoice_id, "paid")
    order = await db.get_order(inv["order_id"])
    await finalize_crypto_order(inv["order_id"], provider="cryptobot",
                                external_id=f"cb_{invoice_id}",
                                amount_cents=order["total_cents"] if order else 0,
                                currency="USDT")
    await query.answer()  # dismiss loading before removing the message
    try:
        await query.message.delete()
    except Exception:
        pass


# ------------------------------------------------- direct deposit rail ---
async def start_direct_deposit(query: types.CallbackQuery, state: FSMContext,
                               user, order_id: int, total_cents: int, chain: str):
    """Allocate a fresh address, store the deposit, show the deposit screen."""
    rates = await cp.get_rates()
    price = rates.get(chain)
    if not price:
        logger.warning("no %s rate — hiding direct crypto", chain)
        # Don't orphan the order: cancel it and drop the stale wizard state.
        await db.set_order_status(order_id, "cancelled")
        await db.release_order_promo(order_id)  # M2: don't burn promo on unpaid cancel
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.crypto_other_methods_kb())
        return
    try:
        address, index, _ = await cp.next_deposit_address(db, chain)
    except Exception as e:
        logger.error("address derivation failed for %s: %s", chain, e)
        # Don't orphan the order: cancel it and drop the stale wizard state.
        await db.set_order_status(order_id, "cancelled")
        await db.release_order_promo(order_id)  # M2: don't burn promo on unpaid cancel
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.crypto_other_methods_kb())
        return
    expected = cp.usd_cents_to_base_units(int(total_cents), price, chain)
    memo = f"NOVA-{order_id}" if chain == "ton" else None
    ttl_min = config.CRYPTO_TTL_MINUTES
    expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_min)).isoformat()
    dep_id = await db.create_crypto_deposit(
        order_id=order_id, chain=chain, address=address,
        derivation_index=index, memo=memo, expected_crypto=str(expected),
        expected_usd_cents=int(total_cents), expires_at=expires)
    await db.audit(user["tg_id"], "crypto_deposit",
                   f"order={order_id} chain={chain} addr={address[:12]}…")
    await notify_admins(
        texts.MSG_CRYPTO_ADMIN_DEPOSIT.format(
            oid=order_id, chain=cp.CHAINS[chain]["name"], address=address,
            amount=cp.format_crypto(expected, chain)),
        min_bit=config.PERM_ORDERS)
    await state.finish()
    memo_line = texts.MSG_DEPOSIT_MEMO_LINE.format(memo=memo) if memo else ""
    await edit_text_safe(
        query,
        texts.MSG_DEPOSIT_SCREEN.format(
            amount=cp.format_crypto(expected, chain), address=address,
            memo_line=memo_line,
            total=fmt_money(total_cents, config.CURRENCY),
            confs=cp.CHAINS[chain]["confirmations"],
            ttl=_ttl_line(expires)),
        kb.deposit_kb(dep_id))


async def _manual_deposit_scan(deposit_id: int) -> str:
    """One manual re-scan. Returns 'paid' | 'underpaid' | 'unpaid' | 'expired'."""
    from crypto_watcher import _fetch_chain_txs, _tx_amount, _process_deposit, _now
    dep = await db.get_crypto_deposit(deposit_id)
    if not dep or dep["status"] not in ("pending", "underpaid"):
        return "expired" if dep and dep["status"] == "expired" else "unpaid"
    await _process_deposit(dep, _now())
    dep = await db.get_crypto_deposit(deposit_id)
    return {"paid": "paid", "underpaid": "underpaid"}.get(dep["status"], "unpaid")


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("codc:"))
async def cb_deposit_check(query: types.CallbackQuery):
    """"Check My Deposit" — manual re-scan, rate-limited 1/30s per user."""
    now = time.time()
    last = _last_deposit_check.get(query.from_user.id, 0)
    if now - last < 30:
        await query.answer(texts.ERR_RATE_LIMITED)
        return
    _last_deposit_check[query.from_user.id] = now
    try:
        deposit_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer()
        return
    dep = await db.get_crypto_deposit(deposit_id)
    if not dep:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # Single answer for this callback: the scanning toast.
    await query.answer(texts.TOAST_SCANNING)
    user = await db.get_user_by_tg(query.from_user.id)
    order = await db.get_order(dep["order_id"])
    if not user or not order or order["user_id"] != user["id"]:
        return
    result = await _manual_deposit_scan(deposit_id)
    if result == "paid":
        await query.message.answer(texts.MSG_CRYPTO_PAID.split("\n\n")[0])
    elif result == "underpaid":
        dep = await db.get_crypto_deposit(deposit_id)
        chain = dep["chain"]
        seen = int(dep["seen_amount_crypto"] or 0)
        expected = int(dep["expected_crypto"])
        await query.message.answer(texts.MSG_CRYPTO_UNDERPAID.format(
            seen=cp.format_crypto(seen, chain),
            expected=cp.format_crypto(expected, chain),
            remaining=cp.format_crypto(expected - seen, chain),
            address=dep["address"]))
    elif result == "expired":
        await query.message.answer(texts.MSG_CRYPTO_EXPIRED,
                                   reply_markup=kb.crypto_expired_kb())
    else:
        chain = dep["chain"]
        await query.message.answer(texts.MSG_CRYPTO_STILL_UNPAID.format(
            confs=cp.CHAINS[chain]["confirmations"]))


# ------------------------------------------------------- admin panel ---
async def _crypto_counts():
    pending = await db.list_crypto_deposits(status="pending", limit=1000)
    late = await db.list_crypto_deposits(status="late", limit=1000)
    underpaid = await db.list_crypto_deposits(status="underpaid", limit=1000)
    return len(pending), len(late), len(underpaid)


@dp.callback_query_handler(text="cry:panel", is_admin=config.PERM_ORDERS)
async def cb_crypto_panel(query: types.CallbackQuery):
    await query.answer()
    p, l, u = await _crypto_counts()
    await edit_text_safe(query, texts.MSG_CRYPTO_PANEL.format(
        pending=p, late=l, underpaid=u), kb.crypto_admin_kb(p, l, u))


@dp.callback_query_handler(
    lambda q: q.data and q.data.startswith("cry:") and q.data != "cry:panel",
    is_admin=config.PERM_ORDERS)
async def cb_crypto_view(query: types.CallbackQuery):
    await query.answer()
    view = query.data.split(":")[1]
    if view == "chains":
        states = [(c, await db.crypto_chain_enabled(c)) for c in cp.CHAINS]
        await edit_text_safe(query, texts.MSG_CRYPTO_CHAINS,
                             kb.crypto_chains_kb(states))
        return
    await _render_deposits(query, view, 0)


async def _render_deposits(query, view: str, page: int, per_page: int = 6):
    rows = await db.list_crypto_deposits(status=view, limit=500)
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = rows[page * per_page:(page + 1) * per_page]
    text = texts.MSG_CRYPTO_DEPOSITS_TITLE.format(view=view, n=len(rows))
    if not chunk:
        text += "\n\n" + texts.MSG_CRYPTO_DEPOSITS_EMPTY
    await edit_text_safe(query, text, kb.crypto_deposits_kb(chunk, page, total_pages, view))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cryp:"),
                           is_admin=config.PERM_ORDERS)
async def cb_crypto_page(query: types.CallbackQuery):
    await query.answer()
    _, view, page_s = query.data.split(":")
    await _render_deposits(query, view, int(page_s))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cryd:"),
                           is_admin=config.PERM_ORDERS)
async def cb_crypto_detail(query: types.CallbackQuery):
    await query.answer()
    dep = await db.get_crypto_deposit(int(query.data.split(":")[1]))
    if not dep:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    chain = dep["chain"]
    text = texts.MSG_CRYPTO_DEPOSIT_ROW.format(
        id=dep["id"], chain=cp.CHAINS[chain]["name"], address=dep["address"],
        amount=cp.format_crypto(int(dep["expected_crypto"]), chain),
        oid=dep["order_id"], status=dep["status"])
    if dep["txid"]:
        text += f"\nTx: <code>{dep['txid'][:32]}…</code>"
    if dep["memo"]:
        text += f"\nMemo: <code>{dep['memo']}</code>"
    await edit_text_safe(query, text,
                         kb.crypto_deposit_detail_kb(dep["id"], dep["status"]))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cryok:"),
                           is_admin=config.PERM_ORDERS)
async def cb_crypto_confirm(query: types.CallbackQuery):
    """Manual confirm: finalize the order for this deposit.

    Exactly one query.answer() per path, and the "confirmed" toast is shown
    only when this admin actually won the claim — never on a lost race.
    """
    try:
        dep_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer()
        return
    dep = await db.get_crypto_deposit(dep_id)
    if not dep or dep["status"] == "paid":
        await query.answer(texts.TOAST_CRYPTO_ALREADY)
        return
    claimed = await db.claim_crypto_deposit(dep_id, f"manual_{dep_id}",
                                            dep["seen_amount_crypto"] or "0", 999)
    if claimed:
        await db.update_crypto_deposit(dep_id, status="paid")
        order = await db.get_order(dep["order_id"])
        await finalize_crypto_order(
            dep["order_id"], provider=f"direct_{dep['chain']}",
            external_id=f"manual_{dep_id}",
            amount_cents=order["total_cents"] if order else 0,
            currency=cp.CHAINS[dep["chain"]]["symbol"])
        await db.audit(query.from_user.id, "crypto_manual_confirm",
                       f"deposit={dep_id}")
        await query.answer(texts.TOAST_CRYPTO_CONFIRMED)
    else:
        # Lost the race (worker or another admin claimed it first) — do NOT
        # show the confirmed toast.
        await query.answer(texts.TOAST_CRYPTO_ALREADY)
    p, l, u = await _crypto_counts()
    await edit_text_safe(query, texts.MSG_CRYPTO_PANEL.format(
        pending=p, late=l, underpaid=u), kb.crypto_admin_kb(p, l, u))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cryno:"),
                           is_admin=config.PERM_ORDERS)
async def cb_crypto_reject(query: types.CallbackQuery):
    """Reject a deposit: cancel deposit AND order (no orphaned pending order)."""
    try:
        dep_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer()
        return
    await db.update_crypto_deposit(dep_id, status="cancelled")
    await db.audit(query.from_user.id, "crypto_manual_reject", f"deposit={dep_id}")
    dep = await db.get_crypto_deposit(dep_id)
    order = await db.get_order(dep["order_id"]) if dep else None
    if order:
        await db.set_order_status(order["id"], "cancelled")
        await db.release_order_promo(order["id"])  # M2
        user = await db.get_user(order["user_id"])
        if user:
            try:
                await bot.send_message(
                    user["tg_id"], texts.MSG_CRYPTO_EXPIRED,
                    reply_markup=kb.crypto_expired_kb())
            except Exception as e:
                logger.warning("reject notify failed: %s", e)
    await query.answer(texts.TOAST_CRYPTO_REJECTED)
    p, l, u = await _crypto_counts()
    await edit_text_safe(query, texts.MSG_CRYPTO_PANEL.format(
        pending=p, late=l, underpaid=u), kb.crypto_admin_kb(p, l, u))


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("cryc:"),
                           is_admin=config.PERM_ORDERS)
async def cb_crypto_chain_toggle(query: types.CallbackQuery):
    # Exactly one answer per callback (see cb_cryptobot_check).
    try:
        chain = query.data.split(":")[1]
    except (ValueError, IndexError):
        await query.answer()
        return
    if chain in cp.CHAINS:
        cur = await db.crypto_chain_enabled(chain)
        await db.set_crypto_chain_enabled(chain, not cur)
        await db.audit(query.from_user.id, "crypto_chain_toggle",
                       f"{chain} -> {not cur}")
        await query.answer(texts.TOAST_CHAIN_ON.format(chain=chain) if not cur
                           else texts.TOAST_CHAIN_OFF.format(chain=chain))
    else:
        await query.answer()
    states = [(c, await db.crypto_chain_enabled(c)) for c in cp.CHAINS]
    await edit_text_safe(query, texts.MSG_CRYPTO_CHAINS,
                         kb.crypto_chains_kb(states))
