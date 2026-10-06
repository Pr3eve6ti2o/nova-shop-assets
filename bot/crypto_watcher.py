"""Background deposit watcher: direct-crypto sweeps + CryptoBot recovery poller.

Runs as an asyncio task from app.py lifespan. Every 60s:
  1. Sweep `crypto_deposits` WHERE status IN ('pending','underpaid') and not expired:
     fetch chain txs, match, check confirmations, finalize on threshold.
  2. Expire past-TTL deposits -> 'expired' + user notice (named state).
  3. Late-deposit pass: expired <24h without txid -> 'late' bucket for manual review.
  4. CryptoBot recovery: getInvoices(status='paid') for active invoices -> finalize.

Never crashes the loop: per-deposit try/except, per-sweep try/except.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
import crypto_payments as cp
import texts
from loader import bot, db
from utils import fmt_money

logger = logging.getLogger(__name__)

SWEEP_INTERVAL = 60


def _now():
    return datetime.now(timezone.utc)


def _parse_iso(s: str):
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def finalize_crypto_order(order_id: int, *, provider: str, external_id: str,
                                amount_cents: int, currency: str):
    """Shared finalize path: processing payment -> fulfill -> paid -> notify.

    Payment is recorded as 'processing' BEFORE fulfillment. Only after
    fulfill_order succeeds is it marked 'paid'. This ensures failed
    fulfillments can be retried (payment stays 'processing').
    """
    from handlers.common import (fulfill_order, maybe_credit_referral,
                                 notify_admins, render_roadmap)
    order = await db.get_order(order_id)
    if not order:
        logger.error("finalize: unknown order %s", order_id)
        return False
    # Idempotency: if order already confirmed, we're done.
    if order["status"] == "confirmed":
        logger.info("finalize: order %s already confirmed; ignoring duplicate %s/%s",
                    order_id, provider, external_id)
        return True
    # C7: never finalize a cancelled order (e.g. user changed payment method
    # after the deposit was created, then paid the old address).
    if order["status"] == "cancelled":
        logger.warning("finalize: order %s is cancelled, refusing to resurrect",
                       order_id)
        await notify_admins(
            f"⚠️ <b>Payment received for cancelled order #{order_id}</b> "
            f"({provider}/{external_id}). Manual review needed — do not auto-fulfill.",
            min_bit=config.PERM_ORDERS)
        return False
    user = await db.get_user(order["user_id"])
    if not user:
        return False

    # Record as 'processing' first. If this is a duplicate (retry), that's fine.
    is_new = await db.record_payment(
        provider=provider, external_id=str(external_id), user_id=user["id"],
        order_id=order_id, amount_cents=amount_cents, currency=currency,
        status="processing")
    if not is_new:
        logger.info("duplicate crypto payment seen: %s/%s", provider, external_id)
        # Re-check the order; it may have been fulfilled in a previous attempt.
        order = await db.get_order(order_id)
        if order and order["status"] == "confirmed":
            return True
        logger.warning("retrying unfulfilled crypto payment: %s/%s",
                       provider, external_id)

    ok, note = await fulfill_order(order_id)
    # C6: only mark confirmed when fulfillment actually succeeded.
    if not ok:
        logger.error("crypto fulfillment failed order %s: %s", order_id, note)
        await notify_admins(
            f"\u274c <b>Fulfillment failed</b> for order #{order_id}:"
            f" {note}\nManual refund/replacement may be needed.",
            min_bit=config.PERM_ORDERS)
        # Leave payment as 'processing' so it can be retried.
        return False
    # Fulfillment succeeded: mark payment paid, then order confirmed.
    await db.update_payment_status(provider, str(external_id), "paid")
    await db.set_order_status(order_id, "confirmed")

    await db.audit(user["tg_id"], "crypto_payment",
                   f"order={order_id} provider={provider} tx={external_id}")
    await maybe_credit_referral(await db.get_order(order_id))

    items = await db.get_order_items(order_id)
    lines = "\n".join(
        f"\u2022 {it['name']} \u00d7{it['qty']} \u2014 "
        f"{fmt_money(it['price_cents'] * it['qty'], config.CURRENCY)}"
        for it in items)
    digital = "\n".join(
        f"\U0001f511 <code>{it['delivered_value']}</code>"
        for it in items if it["delivered_value"])
    try:
        from keyboards import order_success_kb
        await bot.send_message(
            user["tg_id"],
            texts.MSG_CRYPTO_PAID.format(
                oid=order_id, lines=lines,
                total=fmt_money(order["total_cents"], config.CURRENCY),
                provider=provider.replace("_", " ").title(),
                digital=(f"\n\n{digital}" if digital else ""),
                roadmap=render_roadmap("confirmed")),
            reply_markup=order_success_kb(order_id),
            disable_web_page_preview=True)
    except Exception as e:
        logger.warning("paid notify failed for %s: %s", user["tg_id"], e)
    await notify_admins(
        texts.MSG_CRYPTO_ADMIN_PAID.format(
            oid=order_id, provider=provider, tx=str(external_id)[:24],
            total=fmt_money(order["total_cents"], config.CURRENCY)),
        min_bit=config.PERM_ORDERS)
    return True


async def _fetch_chain_txs(chain: str, address: str):
    if chain == "btc":
        txs, _ = await cp.fetch_btc_txs(address)
        return txs
    if chain == "eth":
        return await cp.fetch_eth_usdt_txs(address)
    if chain == "trx":
        return await cp.fetch_trx_usdt_txs(address)
    if chain == "ton":
        return await cp.fetch_ton_txs(address)
    if chain in ("usdt_base", "usdc_base", "usdt_op", "usdc_op",
                 "usdt_polygon", "usdc_polygon"):
        entry = cp.CHAINS[chain]
        return await cp.fetch_evm_token_txs(
            address, entry["blockscout"], entry["token_contract"])
    return []


def _tx_amount(tx: dict) -> int:
    return int(tx.get("base", tx.get("sats", 0)) or 0)


async def _sweep_direct_deposits():
    deposits = await db.pending_crypto_deposits()
    # include underpaid: still watching until TTL
    underpaid = await db.list_crypto_deposits(status="underpaid", limit=10000)
    # include claimed: stale claims from crashes need finalize retry
    claimed = await db.list_crypto_deposits(status="claimed", limit=10000)
    seen_ids = {d["id"] for d in deposits}
    for d in underpaid + claimed:
        if d["id"] not in seen_ids:
            deposits.append(d)
    now = _now()
    for dep in deposits:
        try:
            await _process_deposit(dep, now)
        except Exception as e:
            logger.warning("deposit %s sweep error: %s", dep["id"], e)
        await asyncio.sleep(0.1)  # yield while reducing cadence drift


async def _process_deposit(dep, now):
    expires = _parse_iso(dep["expires_at"])
    if expires is None or now > expires:
        await db.update_crypto_deposit(dep["id"], status="expired")
        await _notify_expired(dep)
        await db.audit(0, "crypto_expired", f"deposit={dep['id']}")
        return

    chain = dep["chain"]
    txs = await _fetch_chain_txs(chain, dep["address"])
    matches = cp.matching_txs(chain, txs, dep["address"], dep["memo"])
    if not matches:
        return  # still_unpaid — user can hit "Check Again"

    # Total across all payments to the address: customers may top up an
    # underpaid deposit with a second transaction.
    total = sum(_tx_amount(t) for t in matches)
    best = max(matches, key=_tx_amount)  # reference tx for txid display
    expected = int(dep["expected_crypto"])
    if not cp.meets_tolerance(total, expected):
        dust = cp.DUST_BASE_UNITS.get(chain, 0)
        if total < dust:
            # Dust/griefing guard: count toward the total, but never spam the
            # user with an underpaid notice for a dust payment.
            logger.info("deposit %s: dust %d base units (< %d); no notice",
                        dep["id"], total, dust)
            return
        if dep["status"] != "underpaid":
            await db.update_crypto_deposit(dep["id"], status="underpaid",
                                           txid=best["txid"],
                                           seen_amount_crypto=str(total))
            await _notify_underpaid(dep, total, expected, chain)
            await db.audit(0, "crypto_underpaid",
                           f"deposit={dep['id']} seen={total} expected={expected}")
        else:
            # Keep the seen amount fresh while we keep watching.
            await db.update_crypto_deposit(dep["id"],
                                           seen_amount_crypto=str(total),
                                           txid=best["txid"])
        return

    needed = cp.CHAINS[chain]["confirmations"]
    # Conservative: every *material* payment must be confirmed. Sub-dust
    # matches (e.g. a 1-satoshi 0-conf grief tx) are ignored so an attacker
    # can't drag the confirmation floor to 0 and block finalization.
    dust = cp.DUST_BASE_UNITS.get(chain, 0)
    material = [t for t in matches if _tx_amount(t) >= dust] or matches
    conf = min(int(t.get("confirmations", 0) or 0) for t in material)
    if conf < needed:
        await db.update_crypto_deposit(dep["id"], confirmations=conf,
                                       seen_amount_crypto=str(total))
        return  # wait for more confirmations

    claimed = await db.claim_crypto_deposit(dep["id"], best["txid"], str(total), conf)
    if not claimed:
        if dep["status"] != "claimed":
            logger.info("deposit %s already claimed by another worker; skipping", dep["id"])
            return
        # Stale claimed: retry finalization in case a previous attempt failed
        # after recording the payment but before fulfillment succeeded.
        logger.info("deposit %s already claimed; retrying finalize", dep["id"])

    # W1: top-up deposits credit the user's balance instead of fulfilling an order.
    if (dep.get("purpose") or "order") == "topup":
        ok, new_bal, bonus = await db.finalize_topup_payment(
            provider=f"direct_{chain}",
            external_id=best["txid"],
            user_id=dep["topup_user_id"],
            amount_cents=int(dep["expected_usd_cents"]),
            currency=cp.CHAINS[chain]["symbol"])
        if ok:
            await db.update_crypto_deposit(dep["id"], status="paid")
            u = await db.get_user(dep["topup_user_id"])
            if u:
                bonus_line = (f"\n\U0001f381 Deposit bonus (5%): <b>{fmt_money(bonus, config.CURRENCY)}</b>" if bonus else "")
                try:
                    await bot.send_message(u["tg_id"], texts.MSG_TOPUP_CREDITED.format(
                        amount=fmt_money(int(dep["expected_usd_cents"]), config.CURRENCY),
                        bonus_line=bonus_line, balance=fmt_money(new_bal, config.CURRENCY)), parse_mode="HTML")
                except Exception as e:
                    logger.warning("topup notify failed: %s", e)
            await db.audit(dep["topup_user_id"], "topup_paid", f"deposit={dep['id']}")
        else:
            await db.update_crypto_deposit(dep["id"], status="underpaid")
        return

    order = await db.get_order(dep["order_id"])
    ok = await finalize_crypto_order(
        dep["order_id"], provider=f"direct_{chain}", external_id=best["txid"],
        amount_cents=order["total_cents"] if order else 0,
        currency=cp.CHAINS[chain]["symbol"])
    if ok:
        await db.update_crypto_deposit(dep["id"], status="paid")
        logger.info("deposit %s paid via %s (%d txs, ref %s)",
                    dep["id"], chain, len(matches), best["txid"][:16])
    elif order and order["status"] == "cancelled":
        # finalize_crypto_order already alerted admins; do not retry forever.
        await db.update_crypto_deposit(dep["id"], status="manual_review")
        logger.warning("deposit %s for cancelled order %s held for manual review"
                       " (chain=%s ref=%s)",
                       dep["id"], dep["order_id"], chain, best["txid"][:16])
    else:
        # Keep the deposit retryable; the claim is re-entrant above.
        await db.update_crypto_deposit(dep["id"], status="underpaid")
        logger.warning("deposit %s finalize failed; leaving underpaid for retry"
                       " (chain=%s txs=%d ref=%s)",
                       dep["id"], chain, len(matches), best["txid"][:16])


async def _notify_expired(dep):
    order = await db.get_order(dep["order_id"]) if dep["order_id"] else None
    # W2: top-up deposits have no order — send a minimal notice to the topup user.
    if (dep.get("purpose") or "order") == "topup":
        user = (await db.get_user(dep["topup_user_id"])
                if dep.get("topup_user_id") else None)
        if not user:
            return
        try:
            await bot.send_message(
                user["tg_id"],
                "\u23f3 Your top-up payment window expired. "
                "You can start a new top-up anytime from the balance menu.")
        except Exception as e:
            logger.warning("topup expired notify failed: %s", e)
        return
    if not order:
        return
    user = await db.get_user(order["user_id"])
    if not user:
        return
    try:
        from keyboards import crypto_expired_kb
        await bot.send_message(user["tg_id"], texts.MSG_CRYPTO_EXPIRED,
                               reply_markup=crypto_expired_kb())
    except Exception as e:
        logger.warning("expired notify failed: %s", e)


async def _notify_underpaid(dep, seen: int, expected: int, chain: str):
    order = await db.get_order(dep["order_id"]) if dep["order_id"] else None
    # W2: top-up deposits have no order — send a minimal notice to the topup user.
    if (dep.get("purpose") or "order") == "topup":
        user = (await db.get_user(dep["topup_user_id"])
                if dep.get("topup_user_id") else None)
        if not user:
            return
        remaining = expected - seen
        try:
            await bot.send_message(
                user["tg_id"],
                "\u26a0\ufe0f Your top-up was underpaid: received "
                f"{cp.format_crypto(seen, chain)}, expected "
                f"{cp.format_crypto(expected, chain)}. Send the remaining "
                f"{cp.format_crypto(remaining, chain)} to {dep['address']}.",
                disable_web_page_preview=True)
        except Exception as e:
            logger.warning("topup underpaid notify failed: %s", e)
        return
    if not order:
        return
    user = await db.get_user(order["user_id"])
    if not user:
        return
    remaining = expected - seen
    try:
        await bot.send_message(
            user["tg_id"],
            texts.MSG_CRYPTO_UNDERPAID.format(
                seen=cp.format_crypto(seen, chain),
                expected=cp.format_crypto(expected, chain),
                remaining=cp.format_crypto(remaining, chain),
                address=dep["address"]),
            disable_web_page_preview=True)
    except Exception as e:
        logger.warning("underpaid notify failed: %s", e)


async def _sweep_late_deposits():
    """Expired <24h without txid: one more scan -> 'late' bucket for manual review."""
    cutoff = _now() - timedelta(hours=24)
    expired = await db.list_crypto_deposits(status="expired", limit=100)
    for dep in expired:
        if dep["txid"]:
            continue
        created = _parse_iso(dep["created_at"]) if dep["created_at"] else None
        if created is None or created < cutoff:
            continue
        try:
            txs = await _fetch_chain_txs(dep["chain"], dep["address"])
            # Sum ALL matching payments (consistent with the main sweep) —
            # top-ups count together instead of only the largest single tx.
            matches = cp.matching_txs(dep["chain"], txs, dep["address"],
                                      dep["memo"])
            if matches:
                total = sum(_tx_amount(t) for t in matches)
                expected = int(dep["expected_crypto"])
                if not cp.meets_tolerance(total, expected):
                    dust = cp.DUST_BASE_UNITS.get(dep["chain"], 0)
                    if total < dust:
                        logger.info(
                            "late deposit %s: dust %d base units (< %d); no notice",
                            dep["id"], total, dust)
                else:
                    best = max(matches, key=_tx_amount)
                    await db.update_crypto_deposit(dep["id"], status="late",
                                                   txid=best["txid"],
                                                   seen_amount_crypto=str(total))
                    from handlers.common import notify_admins
                    await notify_admins(
                        texts.MSG_CRYPTO_ADMIN_LATE.format(
                            oid=dep["order_id"], chain=dep["chain"],
                            tx=best["txid"][:24]),
                        min_bit=config.PERM_ORDERS)
                    await db.audit(0, "crypto_late", f"deposit={dep['id']}")
        except Exception as e:
            logger.warning("late scan %s error: %s", dep["id"], e)
        await asyncio.sleep(0.1)


async def _sweep_cryptobot():
    """Recovery poller: finalize newly-paid CryptoBot invoices (idempotent)."""
    if not config.CRYPTOBOT_TOKEN:
        return
    try:
        invoices = await db.active_cryptobot_invoices()
        if not invoices:
            return
        ids = [inv["invoice_id"] for inv in invoices]
        paid = await cp.cryptobot_get_invoices(invoice_ids=ids, status="paid")
        paid_ids = {int(p.get("invoice_id")) for p in paid if p.get("invoice_id")}
        for inv in invoices:
            if int(inv["invoice_id"]) in paid_ids:
                order = await db.get_order(inv["order_id"])
                if order and order["status"] == "confirmed":
                    await db.set_cryptobot_status(int(inv["invoice_id"]), "paid")
                    logger.info(
                        "cryptobot invoice %s already fulfilled; marked paid",
                        inv["invoice_id"])
                    continue
                ok = await finalize_crypto_order(
                    inv["order_id"], provider="cryptobot",
                    external_id=f"cb_{inv['invoice_id']}",
                    amount_cents=order["total_cents"] if order else 0,
                    currency="USDT")
                # F1: only mark the invoice 'paid' once the order is
                # finalized. If finalize fails, leave it active so the next
                # sweep retries it instead of stranding the user's payment.
                if not ok:
                    logger.warning(
                        "cryptobot invoice %s paid but finalize failed; "
                        "keeping active for retry", inv["invoice_id"])
                    continue
                await db.set_cryptobot_status(int(inv["invoice_id"]), "paid")
                logger.info("cryptobot invoice %s recovered as paid",
                            inv["invoice_id"])
    except Exception as e:
        logger.warning("cryptobot recovery sweep error: %s", e)
    # M5: expire stale invoices server-side so the poll list stays bounded
    # and dead invoices can't finalize. Runs AFTER the paid-poll above so a
    # paid-but-not-yet-polled invoice is never expired before being credited.
    try:
        n_exp = await db.expire_stale_cryptobot_invoices()
        if n_exp:
            logger.info("expired %d stale cryptobot invoices", n_exp)
    except Exception as e:
        logger.warning("cryptobot expiry error: %s", e)


async def _sweep_tonconnect_pending():
    """Slow path for TON Connect: finalize payments that weren't visible
    on-chain when the user submitted (propagation delay).

    Audit C4: tonconnect_pending_add was called but nothing ever read the
    table — real user funds arrived on-chain with no fulfillment. This sweep
    closes that gap.
    """
    from handlers.miniapp import find_tonconnect_tx, create_tonconnect_order
    from handlers.common import main_reply_kb
    merchant = config.TON_DEPOSIT_ADDRESS
    if not merchant:
        return
    pendings = await db.tonconnect_pending_list()
    for p in pendings:
        try:
            matched = await find_tonconnect_tx(merchant, p["sender"], p["amount_nano"])
            if not matched:
                continue
            user = await db.get_user(p["user_id"])
            if not user:
                await db.tonconnect_pending_remove(p["id"])
                continue
            clean = p.get("items") or []
            order_id, ok = await create_tonconnect_order(
                user, p["sender"], p["amount_nano"], clean,
                p.get("promo_code"), matched)
            if order_id is None or not ok:
                # Blocked (e.g. txid already claimed by another user) or
                # partial/inconsistent state — drop the pending without
                # sending a bogus confirmation.
                logger.warning(
                    "tonconnect slow-path blocked for pending %s (order_id=%s ok=%s)",
                    p["id"], order_id, ok)
                await db.tonconnect_pending_remove(p["id"])
                continue
            await db.tonconnect_pending_remove(p["id"])
            try:
                from keyboards import order_success_kb
                await bot.send_message(
                    user["tg_id"],
                    f"✅ <b>Payment confirmed!</b>\n\nOrder #{order_id} is being "
                    f"prepared. You'll receive your items shortly.",
                    reply_markup=order_success_kb(order_id),
                    parse_mode="HTML")
            except Exception as e:
                logger.warning("tonconnect slow-path notify failed: %s", e)
        except Exception as e:
            logger.warning("tonconnect pending sweep error for %s: %s", p["id"], e)


async def crypto_watcher_loop():
    """Main loop: sweep every 60s, never crash."""
    logger.info("crypto watcher started (60s interval)")
    await asyncio.sleep(10)  # let startup settle
    while True:
        started = _now()
        try:
            await _sweep_direct_deposits()
        except Exception as e:
            logger.warning("direct sweep error: %s", e)
        try:
            await _sweep_late_deposits()
        except Exception as e:
            logger.warning("late sweep error: %s", e)
        try:
            await _sweep_cryptobot()
        except Exception as e:
            logger.warning("cryptobot sweep error: %s", e)
        try:
            await _sweep_tonconnect_pending()
        except Exception as e:
            logger.warning("tonconnect pending sweep error: %s", e)
        elapsed = (_now() - started).total_seconds()
        await asyncio.sleep(max(0, SWEEP_INTERVAL - elapsed))
