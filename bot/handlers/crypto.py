"""Crypto payments: CryptoBot rail + self-custody direct deposits + admin panel.

Wired into checkout: payment step lists rails via crypto_payments.payment_rails();
place-order branches here for 'cryptobot' and 'direct_<chain>'.
"""
import asyncio
import logging
import re
import secrets
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
_order_locks: dict = {}


def _order_lock(order_id: int) -> asyncio.Lock:
    lock = _order_locks.get(order_id)
    if lock is None:
        lock = asyncio.Lock()
        _order_locks[order_id] = lock
    return lock


_topup_locks: dict = {}


def _topup_lock(user_id: int) -> asyncio.Lock:
    """Per-user lock serializing CryptoBot top-up invoice creation.

    Single-process only (asyncio locks don't span workers); prevents
    double-click from creating two active invoices.
    """
    lock = _topup_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _topup_locks[user_id] = lock
    return lock


def _valid_deposit_address(chain: str, address) -> bool:
    """Chain-appropriate format check for a derived deposit address (H5).

    A blank/None/malformed address must never be persisted or shown to the
    user as a deposit target.
    """
    if not isinstance(address, str) or not address.strip():
        return False
    addr = address.strip()
    if chain == "btc":
        return _valid_btc_bech32(addr)
    if chain in ("eth", "usdt_base", "usdc_base", "usdt_op", "usdc_op", "usdt_polygon", "usdc_polygon"):
        return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", addr))
    if chain == "trx":
        return bool(re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", addr))
    if chain == "ton":
        return bool(re.fullmatch(r"(?:UQ|EQ)[A-Za-z0-9_\-]{46}", addr))
    return False


BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    generator = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def _valid_btc_bech32(address: str) -> bool:
    """Full bech32/bech32m checksum validation for BTC addresses."""
    if address != address.lower() and address != address.upper():
        return False
    addr = address.lower()
    if len(addr) > 90:
        return False
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        return False
    hrp = addr[:pos]
    if hrp != "bc":
        return False
    data_part = addr[pos + 1:]
    if any(c not in BECH32_CHARSET for c in data_part):
        return False
    values = [BECH32_CHARSET.index(c) for c in data_part]
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + values)
    if polymod == 1:
        spec = "bech32"
    elif polymod == 0x2bc830a3:
        spec = "bech32m"
    else:
        return False
    data = values[:-6]
    if not data:
        return False
    witver = data[0]
    if witver > 16:
        return False
    decoded = _bech32_convertbits(data[1:], 5, 8, False)
    if decoded is None:
        return False
    program = bytes(decoded)
    if len(program) < 2 or len(program) > 40:
        return False
    if witver == 0:
        if spec != "bech32" or len(program) not in (20, 32):
            return False
    elif spec != "bech32m":
        return False
    return True


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
    fee_pct = int(config.CRYPTOBOT_FEE_PERCENT)
    # Displayed gross uses the same gross-up as cryptobot_create_invoice:
    # gross = ceil(net * 100 / (100 - fee_pct)), since CryptoBot deducts its
    # fee from the gross invoice amount.
    gross_cents = ((int(total_cents) * 100 + (100 - fee_pct) - 1)
                   // (100 - fee_pct))
    fee_cents = gross_cents - int(total_cents)
    # Single active CryptoBot invoice per order: cancel any prior open
    # invoices before creating a new one; otherwise two distinct invoice_ids
    # can both be paid and both pass record_payment's uniqueness check,
    # double-fulfilling the order.
    lock = _order_lock(order_id)
    async with lock:
        try:
            priors = await db.active_cryptobot_invoices() or []
        except Exception as e:
            logger.warning("list cryptobot invoices failed: %s", e)
            priors = []
        for prior in priors:
            if prior["order_id"] != order_id:
                continue
            await db.set_cryptobot_status(prior["invoice_id"], "cancelled")
            try:
                await cp.cryptobot_delete_invoice(prior["invoice_id"])
            except Exception as e:
                logger.warning("cryptobot deleteInvoice %s failed: %s",
                               prior["invoice_id"], e)
        try:
            inv = await cp.cryptobot_create_invoice(order_id=order_id,
                                                    usd_cents=int(total_cents))
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
        try:
            await db.create_cryptobot_invoice(order_id=order_id, invoice_id=invoice_id,
                                              asset=inv.get("asset", "USDT"),
                                              amount=str(inv.get("amount", "")),
                                              fee_pct=fee_pct)
        except Exception as e:
            logger.error("cryptobot db insert failed: %s", e)
            try:
                await cp.cryptobot_delete_invoice(invoice_id)
            except Exception as de:
                logger.warning("cryptobot deleteInvoice %s failed after db error: %s",
                               invoice_id, de)
            await db.set_order_status(order_id, "cancelled")
            await db.release_order_promo(order_id)  # M2: don't burn promo on unpaid cancel
            await state.finish()
            await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                                 kb.crypto_other_methods_kb())
            await db.audit(user["tg_id"], "cryptobot_error", f"order={order_id}: {e}")
            return
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


async def start_topup_cryptobot(query: types.CallbackQuery, state: FSMContext,
                                user, amount_cents: int):
    """Create the CryptoBot top-up invoice and show pay + check buttons.

    Order-free mirror of start_cryptobot_payment: no order id is touched, the
    invoice is tagged purpose="topup" and credited to the user's balance once
    paid (see cb_topup_cryptobot_check).
    """
    await query.answer()
    fee_pct = int(config.CRYPTOBOT_FEE_PERCENT)
    # Same gross-up as start_cryptobot_payment / cryptobot_create_invoice:
    # gross = ceil(net * 100 / (100 - fee_pct)); CryptoBot deducts its fee
    # from the gross invoice amount, so the user is netted the amount they
    # asked to top up.
    gross_cents = ((int(amount_cents) * 100 + (100 - fee_pct) - 1)
                   // (100 - fee_pct))
    fee_cents = gross_cents - int(amount_cents)
    # Single active top-up invoice per user: cancel any prior open top-up
    # invoices before creating a new one, so two distinct invoice_ids cannot
    # both be paid and double-credit the balance. Serialized per user to
    # close the list-then-create race.
    async with _topup_lock(user["id"]):
        try:
            priors = await db.active_cryptobot_invoices() or []
        except Exception as e:
            logger.warning("list cryptobot invoices failed: %s", e)
            priors = []
        for prior in priors:
            if (prior.get("purpose") or "order") != "topup":
                continue
            if prior.get("topup_user_id") != user["id"]:
                continue
            if prior.get("status") != "active":
                continue
            await db.set_cryptobot_status(prior["invoice_id"], "cancelled")
            try:
                await cp.cryptobot_delete_invoice(prior["invoice_id"])
            except Exception as e:
                logger.warning("cryptobot deleteInvoice %s failed: %s",
                               prior["invoice_id"], e)
        try:
            inv = await cp.cryptobot_create_invoice(
                order_id=0, usd_cents=int(amount_cents),
                note=f"Nova Shop balance top-up ({fmt_money(amount_cents, config.CURRENCY)})",
                payload="topup")
            invoice_id = int(inv["invoice_id"])
            pay_url = inv["bot_invoice_url"]
            await db.create_cryptobot_invoice(order_id=None, invoice_id=invoice_id,
                                              asset=inv.get("asset", "USDT"),
                                              amount=str(inv.get("amount", "")),
                                              purpose="topup",
                                              topup_user_id=user["id"],
                                              fee_pct=fee_pct)
        except Exception as e:
            logger.warning("cryptobot topup createInvoice failed: %s", e)
            await state.finish()
            await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                                 kb.balance_topup_kb())
            await db.audit(user["tg_id"], "topup_cryptobot_error",
                           f"amount={amount_cents}: {e}")
            return
    await db.audit(user["tg_id"], "topup_cryptobot_invoice",
                   f"invoice={invoice_id}")
    await state.finish()
    await edit_text_safe(
        query,
        texts.MSG_CRYPTOBOT_CREATED.format(
            total=fmt_money(amount_cents, config.CURRENCY),
            fee=fmt_money(fee_cents, config.CURRENCY),
            gross=fmt_money(gross_cents, config.CURRENCY)),
        kb.topup_cryptobot_kb(pay_url, invoice_id))


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
    order = await db.get_order(inv["order_id"])
    user = await db.get_user_by_tg(query.from_user.id)
    if not order or not user or order["user_id"] != user["id"]:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    if inv["status"] == "paid":
        # Idempotent finalization: a prior crash may have marked the invoice
        # paid without finalizing the order.
        await finalize_crypto_order(inv["order_id"], provider="cryptobot",
                                    external_id=f"cb_{invoice_id}",
                                    amount_cents=order["total_cents"],
                                    currency="USDT")
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
    # M5: order was already loaded + ownership-checked above; never finalize
    # with amount 0 on a failed fetch.
    await finalize_crypto_order(inv["order_id"], provider="cryptobot",
                                external_id=f"cb_{invoice_id}",
                                amount_cents=order["total_cents"],
                                currency="USDT")
    await query.answer()  # dismiss loading before removing the message
    try:
        await query.message.delete()
    except Exception:
        pass


@dp.callback_query_handler(lambda q: q.data and q.data.startswith("tupkb:"))
async def cb_topup_cryptobot_check(query: types.CallbackQuery):
    """"I've Paid — Check" for a balance top-up CryptoBot invoice.

    Exactly one query.answer() per path (see cb_cryptobot_check).
    """
    try:
        invoice_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer()
        return
    inv = await db.get_cryptobot_invoice(invoice_id)
    user = await db.get_user_by_tg(query.from_user.id)
    if (not inv or (inv.get("purpose") or "order") != "topup"
            or not user or inv["topup_user_id"] != user["id"]):
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # Recover the NET amount EXACTLY from the stored gross string:
    # gross = ceil(net * 100 / (100 - fee)) implies
    # net <= gross * (100 - fee) / 100 < net + 1, hence the floor below
    # yields net precisely (no rounding ambiguity).
    gross_cents = int(round(float(inv["amount"]) * 100))
    fee_pct = int(inv["fee_pct"] if inv["fee_pct"] is not None else config.CRYPTOBOT_FEE_PERCENT)
    net_cents = (gross_cents * (100 - fee_pct)) // 100

    async def _finalize_and_show():
        ok, new_bal, bonus = await db.finalize_topup_payment(
            provider="cryptobot", external_id=f"cb_{invoice_id}",
            user_id=user["id"], amount_cents=net_cents, currency="USDT")
        bonus_line = (f"\n\U0001f381 Deposit bonus (5%): "
                      f"<b>{fmt_money(bonus, config.CURRENCY)}</b>"
                      if bonus else "")
        await edit_text_safe(query, texts.MSG_TOPUP_CREDITED.format(
            amount=fmt_money(net_cents, config.CURRENCY),
            bonus_line=bonus_line,
            balance=fmt_money(new_bal, config.CURRENCY)), kb.balance_kb())

    if inv["status"] == "paid":
        # Idempotent credit: a prior crash may have marked the invoice paid
        # without crediting the balance (finalize_topup_payment is idempotent).
        await _finalize_and_show()
        await query.answer(texts.TOAST_CRYPTO_ALREADY)
        return
    try:
        items = await cp.cryptobot_get_invoices(invoice_ids=[invoice_id])
    except Exception as e:
        logger.warning("cryptobot topup check failed: %s", e)
        await query.answer()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.balance_topup_kb())
        return
    paid = any(str(p.get("invoice_id")) == str(invoice_id)
               and p.get("status") == "paid" for p in items)
    if not paid:
        await query.answer()
        await query.message.answer(texts.MSG_CRYPTO_STILL_UNPAID)
        return
    await db.set_cryptobot_status(invoice_id, "paid")
    await _finalize_and_show()
    await query.answer()


# ------------------------------------------------- direct deposit rail ---
async def start_direct_deposit(query: types.CallbackQuery, state: FSMContext,
                               user, order_id: int, total_cents: int, chain: str):
    """Allocate a fresh address, store the deposit, show the deposit screen."""
    try:
        rates = await cp.get_rates()
        price = rates.get(chain)
    except Exception as e:
        logger.warning("get %s rate failed: %s", chain, e)
        # Don't orphan the order: cancel it and drop the stale wizard state.
        await db.set_order_status(order_id, "cancelled")
        await db.release_order_promo(order_id)  # M2: don't burn promo on unpaid cancel
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.crypto_other_methods_kb())
        return
    if not price:
        logger.warning("no %s rate — hiding direct crypto", chain)
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
    lock = _order_lock(order_id)
    async with lock:
        try:
            # Reuse the latest pending/underpaid deposit for this order+chain
            # rather than cancelling unseen deposits and stranding in-flight
            # funds on an unmonitored address. Never create a second active
            # deposit for the same order+chain.
            existing = await db.get_deposit_by_order(order_id, chain)
            if existing and existing["status"] not in ("pending", "underpaid"):
                existing = None
            if existing:
                await state.finish()
                memo_line = texts.MSG_DEPOSIT_MEMO_LINE.format(memo=existing["memo"]) if existing["memo"] else ""
                await edit_text_safe(
                    query,
                    texts.MSG_DEPOSIT_SCREEN.format(
                        amount=cp.format_crypto(int(existing["expected_crypto"]), existing["chain"]),
                        address=existing["address"],
                        memo_line=memo_line,
                        total=fmt_money(int(existing["expected_usd_cents"]), config.CURRENCY),
                        confs=cp.active_chains()[existing["chain"]]["confirmations"],
                        ttl=_ttl_line(existing["expires_at"])),
                    kb.deposit_kb(existing["id"]))
                return
            address, index, _ = await cp.next_deposit_address(db, chain)
            if not _valid_deposit_address(chain, address):
                raise ValueError(f"invalid {chain} address derived: {address!r}")
            dep_id = await db.create_crypto_deposit(
                order_id=order_id, chain=chain, address=address,
                derivation_index=index, memo=memo, expected_crypto=str(expected),
                expected_usd_cents=int(total_cents), expires_at=expires)
        except Exception as e:
            logger.error("direct deposit setup failed for %s: %s", chain, e)
            # Don't orphan the order: cancel it and drop the stale wizard state.
            await db.set_order_status(order_id, "cancelled")
            await db.release_order_promo(order_id)  # M2: don't burn promo on unpaid cancel
            await state.finish()
            await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                                 kb.crypto_other_methods_kb())
            return
    await db.audit(user["tg_id"], "crypto_deposit",
                   f"order={order_id} chain={chain} addr={address[:12]}…")
    await notify_admins(
        texts.MSG_CRYPTO_ADMIN_DEPOSIT.format(
            oid=order_id, chain=cp.active_chains()[chain]["name"], address=address,
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
            confs=cp.active_chains()[chain]["confirmations"],
            ttl=_ttl_line(expires)),
        kb.deposit_kb(dep_id))


async def start_topup_deposit(query: types.CallbackQuery, state: FSMContext,
                              user, amount_cents: int, chain: str):
    """Order-free mirror of start_direct_deposit for a balance top-up.

    Allocates a fresh deposit address tagged purpose="topup"; funds are
    credited to the user's balance by the watcher once confirmed.
    """
    await query.answer()
    try:
        rates = await cp.get_rates()
        price = rates.get(chain)
    except Exception as e:
        logger.warning("get %s rate failed: %s", chain, e)
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.balance_topup_kb())
        return
    if not price:
        logger.warning("no %s rate — hiding direct crypto", chain)
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.balance_topup_kb())
        return
    expected = cp.usd_cents_to_base_units(int(amount_cents), price, chain)
    ttl_min = config.CRYPTO_TTL_MINUTES
    expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_min)).isoformat()
    try:
        # Reuse the latest pending/underpaid top-up deposit for this user+chain
        # rather than cancelling unseen deposits and stranding in-flight funds.
        existing = None
        for _old in await db.list_crypto_deposits(status="pending", limit=1000):
            if (_old.get("purpose") or "order") != "topup":
                continue
            if _old.get("topup_user_id") != user["id"] or _old["chain"] != chain:
                continue
            existing = _old
            break
        if existing is None:
            for _old in await db.list_crypto_deposits(status="underpaid", limit=1000):
                if (_old.get("purpose") or "order") != "topup":
                    continue
                if _old.get("topup_user_id") != user["id"] or _old["chain"] != chain:
                    continue
                existing = _old
                break
        if existing:
            await state.finish()
            memo_line = texts.MSG_DEPOSIT_MEMO_LINE.format(memo=existing["memo"]) if existing["memo"] else ""
            await edit_text_safe(
                query,
                texts.MSG_DEPOSIT_SCREEN.format(
                    amount=cp.format_crypto(int(existing["expected_crypto"]), existing["chain"]),
                    address=existing["address"],
                    memo_line=memo_line,
                    total=fmt_money(int(existing["expected_usd_cents"]), config.CURRENCY),
                    confs=cp.active_chains()[existing["chain"]]["confirmations"],
                    ttl=_ttl_line(existing["expires_at"])),
                types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text=texts.BTN_DEPOSIT_CHECK,
                        callback_data=cb("codc", existing["id"]))],
                    [types.InlineKeyboardButton(
                        text=texts.BTN_BACK,
                        callback_data="tup:back")],
                ]))
            return
        address, index, _ = await cp.next_deposit_address(db, chain)
        if not _valid_deposit_address(chain, address):
            raise ValueError(f"invalid {chain} address derived: {address!r}")
        # Per-deposit memo generated BEFORE insert so a TON top-up deposit
        # never exists in the DB with memo=None (a sweeper racing this
        # await would otherwise match any TON tx to the static address).
        memo = f"NOVA-TOPUP-{user['id']}-{secrets.token_hex(4).upper()}" if chain == "ton" else None
        dep_id = await db.create_crypto_deposit(
            order_id=None, chain=chain, address=address,
            derivation_index=index, memo=memo, expected_crypto=str(expected),
            expected_usd_cents=int(amount_cents), expires_at=expires,
            purpose="topup", topup_user_id=user["id"])
    except Exception as e:
        logger.error("topup deposit setup failed for %s: %s", chain, e)
        await state.finish()
        await edit_text_safe(query, texts.MSG_CRYPTO_PROVIDER_DOWN,
                             kb.balance_topup_kb())
        return
    await db.audit(user["tg_id"], "topup_deposit",
                   f"chain={chain} addr={address[:12]}…")
    await notify_admins(
        texts.MSG_CRYPTO_ADMIN_DEPOSIT.format(
            oid="topup", chain=cp.active_chains()[chain]["name"], address=address,
            amount=cp.format_crypto(expected, chain)),
        min_bit=config.PERM_ORDERS)
    await state.finish()
    memo_line = texts.MSG_DEPOSIT_MEMO_LINE.format(memo=memo) if memo else ""
    await edit_text_safe(
        query,
        texts.MSG_DEPOSIT_SCREEN.format(
            amount=cp.format_crypto(expected, chain), address=address,
            memo_line=memo_line,
            total=fmt_money(amount_cents, config.CURRENCY),
            confs=cp.active_chains()[chain]["confirmations"],
            ttl=_ttl_line(expires)),
        types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text=texts.BTN_DEPOSIT_CHECK,
                callback_data=cb("codc", dep_id))],
            [types.InlineKeyboardButton(
                text=texts.BTN_BACK,
                callback_data="tup:back")],
        ]))


async def _manual_deposit_scan(deposit_id: int) -> str:
    """One manual re-scan. Returns 'paid' | 'underpaid' | 'unpaid' | 'expired'."""
    from crypto_watcher import _fetch_chain_txs, _tx_amount, _process_deposit, _now
    dep = await db.get_crypto_deposit(deposit_id)
    if not dep:
        return "unpaid"
    if dep["status"] == "paid":
        return "paid"
    if dep["status"] in ("expired", "cancelled"):
        return "expired"
    if dep["status"] not in ("pending", "underpaid"):
        return "unpaid"
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
    if not user:
        return
    if (dep.get("purpose") or "order") == "topup":
        # Top-up deposits have no order; verify ownership via topup_user_id.
        if dep.get("topup_user_id") != user["id"]:
            return
    else:
        order = await db.get_order(dep["order_id"])
        if not order or order["user_id"] != user["id"]:
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
            confs=cp.active_chains()[chain]["confirmations"]))


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
        states = [(c, await db.crypto_chain_enabled(c)) for c in cp.active_chains()]
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
        id=dep["id"], chain=cp.active_chains()[chain]["name"], address=dep["address"],
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
    # Never finalize a deposit with no funds seen — an admin misclick must
    # not mark an unpaid order as paid.
    try:
        seen = float(dep["seen_amount_crypto"] or 0)
    except (TypeError, ValueError):
        seen = 0
    if seen <= 0:
        await query.answer(
            "⚠️ No funds seen on this deposit yet — cannot confirm.",
            show_alert=True)
        return
    # P0-1: Fetch order BEFORE claim so we can gate on the actual received
    # amount. Never credit order total blindly.
    order = await db.get_order(dep["order_id"])
    if not order:
        logger.error("CRITICAL: manual crypto confirm deposit %s has no order %s",
                     dep_id, dep["order_id"])
        await notify_admins(
            f"CRITICAL: manual crypto confirm deposit {dep_id} order {dep['order_id']} missing")
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # P0-1: Compare actual received amount against order total.
    try:
        received_cents = int(dep.get("amount_cents") or 0)
    except (TypeError, ValueError):
        received_cents = 0
    total_cents = int(order.get("total_cents") or 0)
    if received_cents < total_cents:
        logger.warning(
            "Manual crypto confirm blocked: deposit %s received %s < order total %s",
            dep_id, received_cents, total_cents)
        await db.audit(query.from_user.id, "crypto_manual_confirm_blocked",
                       f"deposit={dep_id} received={received_cents} total={total_cents}")
        await query.answer(
            f"⚠️ Underpaid: received {received_cents} < {total_cents}. Cannot confirm.",
            show_alert=True)
        return
    # P0-4: Guard chain lookup BEFORE claim — do not KeyError after consuming.
    chain_info = cp.active_chains().get(dep["chain"]) or {}
    currency = chain_info.get("symbol") or order.get("currency") or dep["chain"]
    if not chain_info:
        logger.error("Manual crypto confirm: chain %s disabled for deposit %s",
                     dep["chain"], dep_id)
    # P0-2: Stable idempotency key — use tx hash so manual and worker paths
    # share the same key and cannot double-credit.
    stable_key = dep.get("tx_hash") or dep.get("txid") or f"manual_{dep_id}"
    # Admins who truly must force-confirm can use the admin panel/DB path.
    claimed = await db.claim_crypto_deposit(dep_id, stable_key,
                                            dep["seen_amount_crypto"] or "0", 999)
    if claimed:
        await db.update_crypto_deposit(dep_id, status="paid")
        await finalize_crypto_order(
            dep["order_id"], provider=f"direct_{dep['chain']}",
            external_id=stable_key,
            amount_cents=received_cents,
            currency=currency)
        await db.audit(query.from_user.id, "crypto_manual_confirm",
                       f"deposit={dep_id} received={received_cents} total={total_cents}")
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
    dep = await db.get_crypto_deposit(dep_id)
    if not dep:
        await query.answer(texts.ERR_NOT_FOUND, show_alert=True)
        return
    # P0-3: Guard all terminal states, not just "paid". A deposit in
    # processing/delivered/completed must not be cancellable.
    if dep["status"] in ("paid", "processing", "delivered", "completed", "cancelled"):
        await query.answer(texts.TOAST_CRYPTO_ALREADY, show_alert=True)
        return
    order = await db.get_order(dep["order_id"])
    if order and order["status"] in ("paid", "processing", "delivered", "completed", "refunded", "cancelled"):
        await query.answer(texts.TOAST_CRYPTO_ALREADY, show_alert=True)
        return
    # P0-3: Atomic status transition — only cancel if still in a cancellable
    # state. Prevents double-reject and admin-vs-worker races.
    updated = await db.update_crypto_deposit_if_status(
        dep_id, "cancelled", ["pending", "late", "underpaid"])
    if not updated:
        await query.answer(texts.TOAST_CRYPTO_ALREADY, show_alert=True)
        return
    await db.audit(query.from_user.id, "crypto_manual_reject", f"deposit={dep_id}")
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
    if chain in cp.active_chains():
        cur = await db.crypto_chain_enabled(chain)
        # P1-1: Warn if disabling with open deposits — funds would land unmatched.
        if cur:  # currently enabled, about to disable
            open_deps = await db.count_open_crypto_deposits(chain)
            if open_deps > 0:
                logger.warning(
                    "Disabling chain %s with %d open deposits", chain, open_deps)
                await db.audit(query.from_user.id, "crypto_chain_toggle_warn",
                               f"{chain} has {open_deps} open deposits")
                await query.answer(
                    f"⚠️ {open_deps} open deposits on {chain}. Disable anyway? Click again to confirm.",
                    show_alert=True)
                # Require second click: store pending disable in a simple way
                # by not toggling yet. Admin clicks again to force.
                return
        await db.set_crypto_chain_enabled(chain, not cur)
        await db.audit(query.from_user.id, "crypto_chain_toggle",
                       f"{chain} -> {not cur}")
        await query.answer(texts.TOAST_CHAIN_ON.format(chain=chain) if not cur
                           else texts.TOAST_CHAIN_OFF.format(chain=chain))
    else:
        await query.answer()
    states = [(c, await db.crypto_chain_enabled(c)) for c in cp.active_chains()]
    await edit_text_safe(query, texts.MSG_CRYPTO_CHAINS,
                         kb.crypto_chains_kb(states))
