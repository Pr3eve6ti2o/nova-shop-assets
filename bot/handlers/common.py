"""Shared helpers for handlers: user registration, admin checks, totals, rendering."""
import html
import logging

from aiogram import types
from aiogram.dispatcher import FSMContext

import config
import keyboards as kb
import texts
from loader import bot, db, dp
from utils import fmt_money, stars_for_cents

logger = logging.getLogger(__name__)

NAV_BUTTONS = {
    texts.BTN_SHOP, texts.BTN_PROFILE,
    texts.BTN_INFO, texts.BTN_RENT, texts.BTN_ADMIN,
}


async def get_or_register(tg_id: int, name: str, referred_by=None):
    """Return (user_row, is_new). Config ADMINS get full mask on first sight."""
    user = await db.get_user_by_tg(tg_id)
    if user is None:
        try:
            user = await db.create_user(tg_id, name, referred_by=referred_by)
            is_new = True
        except Exception:
            # Concurrent registration race: another coroutine created the user.
            user = await db.get_user_by_tg(tg_id)
            if user is None:
                raise
            is_new = False
    else:
        is_new = False
    if tg_id in config.ADMINS and not user["role_mask"]:
        await db.update_user_admin(user["id"], role_mask=config.PERM_ALL)
        user = await db.get_user_by_tg(tg_id)
    return user, is_new


async def is_admin_tg(tg_id: int) -> bool:
    if tg_id in config.ADMINS:
        return True
    user = await db.get_user_by_tg(tg_id)
    return bool(user and user["role_mask"])


async def mask_of_tg(tg_id: int) -> int:
    # Fail-closed like admin.mask_of: reject negative/non-int, strip unknown bits.
    if tg_id in config.ADMINS:
        return config.PERM_ALL
    user = await db.get_user_by_tg(tg_id)
    if not user or user.get("is_banned"):
        return 0
    mask = user.get("role_mask") or 0
    if not isinstance(mask, int) or mask < 0:
        return 0
    return mask & config.PERM_ALL


async def main_reply_kb(tg_id: int):
    user = await db.get_user_by_tg(tg_id)
    try:
        show_rental = bool(user["has_rental_history"]) if user else False
    except (IndexError, KeyError, TypeError):
        show_rental = False
    return kb.reply_main_menu(is_admin=await is_admin_tg(tg_id),
                              show_rental=show_rental)


async def refresh_reply_kb(chat_id: int, tg_id: int):
    """Best-effort live cart badge: re-send reply keyboard on next message.

    Reply keyboards can't be edited in place, so every newly SENT message
    carries a fresh keyboard (see send() helpers below).
    """


async def totals(user_id: int, state: FSMContext, with_delivery: bool = False):
    """Recompute cart totals from the DB. Never trust client-side amounts."""
    items = await db.cart_items(user_id)
    subtotal = sum(i["price_cents"] * i["qty"] for i in items)
    promo_code = None
    discount = 0
    data = await state.get_data()
    code = data.get("promo_code")
    if code:
        ok, _, disc, _ = await db.validate_promo(code, user_id, subtotal)
        if ok:
            promo_code, discount = code, disc
        else:
            await state.update_data(promo_code=None)
    delivery_fee = 0
    if with_delivery and data.get("delivery_kind", "delivery") == "delivery":
        delivery_fee = config.DELIVERY_FEE_CENTS
    total = max(0, subtotal - discount + delivery_fee)
    return {
        "items": items, "subtotal": subtotal, "discount": discount,
        "promo_code": promo_code, "delivery_fee": delivery_fee, "total": total,
    }


def render_lines(items) -> str:
    return "\n".join(
        texts.MSG_CART_LINE.format(
            name=html.escape(str(i["name"])), qty=i["qty"],
            line_total=fmt_money(i["price_cents"] * i["qty"], config.CURRENCY))
        for i in items
    )


def totals_text(t: dict) -> str:
    discount_line = ""
    if t["discount"]:
        discount_line = texts.MSG_CO_DISCOUNT_LINE.format(
            code=t["promo_code"],
            discount=fmt_money(t["discount"], config.CURRENCY))
    delivery_line = ""
    if t["delivery_fee"]:
        delivery_line = texts.MSG_CO_DELIVERY_LINE.format(
            fee=fmt_money(t["delivery_fee"], config.CURRENCY))
    return texts.MSG_CO_TOTALS.format(
        subtotal=fmt_money(t["subtotal"], config.CURRENCY),
        discount_line=discount_line, delivery_line=delivery_line,
        total=fmt_money(t["total"], config.CURRENCY))


def render_roadmap(status: str) -> str:
    if status == "cancelled":
        return texts.MSG_ROADMAP_CANCELLED
    flow = ["pending", "confirmed", "preparing", "shipped", "delivered"]
    idx = flow.index(status) if status in flow else 0
    lines = []
    for i, st in enumerate(flow):
        label = texts.STATUS_LABEL[st]
        lines.append(texts.MSG_ROADMAP_DONE.format(label=label) if i <= idx
                     else texts.MSG_ROADMAP_TODO.format(label=label))
    return "\n".join(lines)


async def notify_admins(text: str, min_bit: int = 0, reply_markup=None):
    """Send a message to config admins + users holding min_bit. Returns sent count."""
    targets = set(config.ADMINS)
    for tg_id, mask in await db.admin_tg_ids():
        if min_bit == 0 or (mask & min_bit):
            targets.add(tg_id)
    sent = 0
    for tg_id in targets:
        try:
            await bot.send_message(tg_id, text, reply_markup=reply_markup,
                                   disable_web_page_preview=True)
            sent += 1
        except Exception as e:
            logger.warning("notify_admins -> %s failed: %s", tg_id, e)
    return sent


async def fulfill_order(order_id: int):
    """Claim digital values / decrement stock. Returns (ok, note).

    Audit 3.2: the whole fulfillment runs in ONE database transaction
    (db.fulfill_order_atomic). Any failure rolls back atomically — no
    compensation rollback needed, so inventory can never be stranded by
    a failed rollback.
    """
    return await db.fulfill_order_atomic(order_id)


async def maybe_credit_referral(order) -> int:
    """Credit referrer on the referee's FIRST paid order. Returns credited cents."""
    user = await db.get_user(order["user_id"])
    if not user or not user["referred_by"]:
        return 0
    percent = await db.referral_percent()
    amount = order["total_cents"] * percent // 100
    if amount <= 0:
        return 0
    if not await db.claim_and_record_referral_credit(
            user["id"], user["referred_by"], order["id"], amount):
        return 0
    referrer = await db.get_user(user["referred_by"])
    if referrer:
        try:
            await bot.send_message(
                referrer["tg_id"],
                texts.MSG_REFERRAL_CREDIT.format(
                    amount=fmt_money(amount, config.CURRENCY),
                    name=user["name"] or "a friend"))
        except Exception as e:
            logger.warning("referral notify failed: %s", e)
    await db.audit(0, "referral_credit",
                   f"order={order['id']} referrer={user['referred_by']} amount={amount}")
    return amount


async def edit_text_safe(query: types.CallbackQuery, text: str, reply_markup=None):
    """Edit in place; fall back to delete+send when the message kind differs."""
    try:
        await query.message.edit_text(text, reply_markup=reply_markup,
                                      disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.delete()
        except Exception:
            pass
        await bot.send_message(query.message.chat.id, text, reply_markup=reply_markup,
                               disable_web_page_preview=True)


async def check_stock_line(p) -> str:
    if p["kind"] == "digital":
        return texts.MSG_STOCK_DIGITAL
    if p["stock"] == -1:
        return texts.MSG_STOCK_PHYSICAL.format(n="\u221e")
    return texts.MSG_STOCK_PHYSICAL.format(n=p["stock"])


async def product_available(p, qty: int = 1) -> bool:
    if not p or not p["is_active"]:
        return False
    if p["kind"] == "physical" and p["stock"] != -1 and p["stock"] < qty:
        return False
    if p["kind"] == "digital" and not p["is_unlimited"]:
        if await db.unused_values_count(p["id"]) < qty:
            return False
    return True


async def handle_escape(message: types.Message, state: FSMContext) -> bool:
    """If the user taps nav while in a text-input state, bail out cleanly."""
    text = message.text or ""
    # The cart reply-button carries a live count badge ("🛒 Cart (3)").
    if text in NAV_BUTTONS or text.startswith(texts.BTN_CART) or text.startswith("/"):
        await state.finish()
        await message.answer(texts.MSG_WIZARD_CANCELLED,
                             reply_markup=await main_reply_kb(message.from_user.id))
        return True
    return False


def stars_label(total_cents: int) -> int:
    return stars_for_cents(total_cents, config.STARS_PER_USD)
