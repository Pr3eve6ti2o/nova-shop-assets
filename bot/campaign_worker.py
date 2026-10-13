"""Campaign engine (port plan Part 2, DoktorShift pattern).

Customer-lifecycle messages, one pass every CAMPAIGN_INTERVAL_SECONDS:

- abandoned_cart — a cart idle for >= ABANDONED_CART_DELAY_MINUTES gets
  one reminder per cart version (dedup key = the cart's last activity
  stamp; touch the cart and the clock restarts).
- back_in_stock — stock-alert subscribers are notified when their
  product is available again, then unsubscribed (the alert table is
  the queue; the campaign claim guards against double-sends).
- post_purchase — a thank-you lands POST_PURCHASE_DELAY_HOURS after
  delivery, once per order.
- onboarding — a single nudge ONBOARDING_NUDGE_HOURS after registering
  for users who have never ordered.

Every send is claimed in campaign_sends BEFORE sending (UNIQUE
constraint): a crash may lose one message but can never duplicate one.
Sends are throttled to ~25/second (Telegram's ceiling is ~30).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils import fmt_money

logger = logging.getLogger(__name__)

_SEND_GAP = 1 / 25  # ~25 messages/sec


def _iso_before(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(
        timespec="seconds")


async def _send(bot, tg_id: int, text: str, reply_markup=None) -> bool:
    try:
        await bot.send_message(tg_id, text, reply_markup=reply_markup,
                               disable_web_page_preview=True)
        return True
    except Exception as e:
        logger.info("campaign send to %s failed: %s", tg_id, e)
        return False


async def _tg_of(db, user_id: int):
    user = await db.get_user(user_id)
    return user["tg_id"] if user else None


async def _pass_abandoned_cart(db, bot) -> int:
    sent = 0
    rows = await db.carts_idle(config.ABANDONED_CART_DELAY_MINUTES)
    for row in rows:
        uid, dedup = row["user_id"], f"cart:{row['last_at']}"
        if not await db.campaign_claim_send("abandoned_cart", uid, dedup):
            continue
        tg_id = await _tg_of(db, uid)
        ok = False
        if tg_id:
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
                "🛒 View cart", callback_data="cart"))
            ok = await _send(
                bot, tg_id,
                "🛒 <b>Your cart is waiting</b>\n\n"
                f"You left {row['items']} item(s) worth "
                f"{fmt_money(row['total_cents'] or 0, config.CURRENCY)} "
                "in your cart. They're saved for you — pick up where "
                "you left off whenever you're ready.",
                reply_markup=kb)
        if ok:
            sent += 1
        else:
            await db.campaign_release_send("abandoned_cart", uid, dedup)
        await asyncio.sleep(_SEND_GAP)
    return sent


async def _pass_back_in_stock(db, bot) -> int:
    sent = 0
    for product in await db.alert_products_in_stock():
        pid, name = product["id"], product["name"]
        for uid in await db.stock_alerts_for_product(pid):
            # The alert row IS the claim: remove it first (so nothing can
            # double-send), restore it only if delivery fails. This also
            # keeps future restocks working — a fresh subscription is a
            # fresh row, never blocked by an old campaign claim.
            await db.stock_alert_remove(uid, pid)
            tg_id = await _tg_of(db, uid)
            ok = False
            if tg_id:
                kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
                    "🛍 View product", callback_data=f"p:{pid}"))
                ok = await _send(
                    bot, tg_id,
                    f"🔔 <b>Back in stock</b>\n\n<b>{name}</b> is available "
                    "again. Stock can go quickly — grab it while it lasts.",
                    reply_markup=kb)
            if ok:
                sent += 1
            else:
                await db.stock_alert_add(uid, pid)
            await asyncio.sleep(_SEND_GAP)
    return sent


async def _pass_post_purchase(db, bot) -> int:
    sent = 0
    cutoff = _iso_before(hours=config.POST_PURCHASE_DELAY_HOURS)
    # Window: only orders delivered within the last 7 days are thanked —
    # a first pass must not flood every historical customer.
    since = _iso_before(hours=config.POST_PURCHASE_DELAY_HOURS + 168)
    for order in await db.orders_delivered_before(cutoff, since_iso=since):
        uid, dedup = order["user_id"], f"order:{order['id']}"
        if not await db.campaign_claim_send("post_purchase", uid, dedup):
            continue
        tg_id = await _tg_of(db, uid)
        ok = False
        if tg_id:
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton(
                "📦 View order", callback_data=f"o:{order['id']}"))
            ok = await _send(
                bot, tg_id,
                f"🙏 <b>Thank you for order #{order['id']}</b>\n\n"
                "We hope everything arrived exactly as expected. If "
                "anything isn't right, our support team is one tap away "
                "from the order page.",
                reply_markup=kb)
        if ok:
            sent += 1
        else:
            await db.campaign_release_send("post_purchase", uid, dedup)
        await asyncio.sleep(_SEND_GAP)
    return sent


async def _pass_onboarding(db, bot) -> int:
    sent = 0
    cutoff = _iso_before(hours=config.ONBOARDING_NUDGE_HOURS)
    for user in await db.users_registered_before_no_orders(cutoff):
        uid = user["id"]
        if not await db.campaign_claim_send("onboarding", uid, "welcome"):
            continue
        ok = await _send(
            bot, user["tg_id"],
            "👋 <b>Still browsing?</b>\n\n"
            "Your account is ready and your first order only takes a "
            "minute. If you have any questions before buying, just ask "
            "us here — a human replies.")
        if ok:
            sent += 1
        else:
            await db.campaign_release_send("onboarding", uid, "welcome")
        await asyncio.sleep(_SEND_GAP)
    return sent


async def process_campaigns_once(db, bot) -> dict:
    """Run one pass of every campaign type. Returns per-type counts."""
    counts = {}
    counts["abandoned_cart"] = await _pass_abandoned_cart(db, bot)
    counts["back_in_stock"] = await _pass_back_in_stock(db, bot)
    counts["post_purchase"] = await _pass_post_purchase(db, bot)
    counts["onboarding"] = await _pass_onboarding(db, bot)
    return counts


async def campaign_worker_loop(db, bot):
    interval = config.CAMPAIGN_INTERVAL_SECONDS
    logger.info("campaign worker started (interval=%ss)", interval)
    while True:
        try:
            if config.CAMPAIGNS_ENABLED:
                counts = await process_campaigns_once(db, bot)
                total = sum(counts.values())
                if total:
                    logger.info("campaigns: sent %s", counts)
        except Exception as e:
            logger.exception("campaign worker error: %s", e)
        await asyncio.sleep(interval)
