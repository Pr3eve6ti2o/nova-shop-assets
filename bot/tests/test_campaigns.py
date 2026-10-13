"""Campaign engine tests (port plan Part 2): all four passes against a
recording fake bot — dedup, claim/release, restock alerts, windows.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_campaigns.py
"""
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402
import campaign_worker  # noqa: E402


class FakeBot:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    async def send_message(self, tg_id, text, reply_markup=None,
                           disable_web_page_preview=False):
        if tg_id in self.fail_for:
            raise RuntimeError("user blocked the bot")
        self.sent.append((tg_id, text))
        return True


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(
        timespec="seconds")


async def _fixture():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    await db.create_tables()
    cat = await db.add_category("Test")
    p1 = await db.add_product(category_id=cat, name="Widget",
                              price_cents=1500, stock=0)
    return db, cat, p1


async def _user(db, tg):
    u = await db.create_user(tg, f"U{tg}")
    return u["id"]


class Campaigns(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_abandoned_cart_once_per_cart_version(self):
        async def go():
            db, cat, p1 = await _fixture()
            uid = await _user(db, 111)
            await db.cart_add(uid, p1, 2)
            bot = FakeBot()
            # Fresh cart: nothing
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["abandoned_cart"], 0)
            # Age it past the 60-minute delay
            async with db._db() as c:
                await c.execute("UPDATE cart_items SET updated_at=?",
                                (_ago(hours=2),))
                await c.commit()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["abandoned_cart"], 1)
            self.assertIn("cart is waiting", bot.sent[0][1])
            # Same cart version: never again
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["abandoned_cart"], 0)
            # Customer touches the cart, abandons again -> new reminder
            await db.cart_add(uid, p1, 1)
            async with db._db() as c:
                await c.execute("UPDATE cart_items SET updated_at=?",
                                (_ago(hours=3),))
                await c.commit()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["abandoned_cart"], 1)
        self.run_async(go())

    def test_back_in_stock_and_failure_restores_alert(self):
        async def go():
            db, cat, p1 = await _fixture()
            uid = await _user(db, 222)
            await db.stock_alert_add(uid, p1)
            bot = FakeBot()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["back_in_stock"], 0)  # still stock 0
            await db.update_product(p1, stock=3)
            # Delivery fails -> alert restored for a later pass
            bot.fail_for = {222}
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["back_in_stock"], 0)
            self.assertEqual(await db.stock_alerts_for_product(p1), [uid])
            # Delivery works -> notified once, alert consumed
            bot.fail_for = set()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["back_in_stock"], 1)
            self.assertEqual(await db.stock_alerts_for_product(p1), [])
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["back_in_stock"], 0)
        self.run_async(go())

    def test_post_purchase_once_and_window(self):
        async def go():
            db, cat, p1 = await _fixture()
            uid = await _user(db, 333)
            oid = await db.create_order(
                user_id=uid, subtotal_cents=1500, discount_cents=0,
                total_cents=1500, payment_method="balance",
                delivery_kind="digital", address=None, phone=None)
            await db.set_order_status(oid, "delivered")
            bot = FakeBot()
            # Just delivered: inside the 24h delay, nothing
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["post_purchase"], 0)
            # Delivered 48h ago: thanked once
            async with db._db() as c:
                await c.execute("UPDATE orders SET delivered_at=? WHERE id=?",
                                (_ago(hours=48), oid))
                await c.commit()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["post_purchase"], 1)
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["post_purchase"], 0)
            # Ancient order (30 days): outside the 7-day window, no flood
            oid2 = await db.create_order(
                user_id=uid, subtotal_cents=1500, discount_cents=0,
                total_cents=1500, payment_method="balance",
                delivery_kind="digital", address=None, phone=None)
            await db.set_order_status(oid2, "delivered")
            async with db._db() as c:
                await c.execute("UPDATE orders SET delivered_at=? WHERE id=?",
                                (_ago(days=30), oid2))
                await c.commit()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["post_purchase"], 0)
        self.run_async(go())

    def test_onboarding_only_new_orderless_users(self):
        async def go():
            db, cat, p1 = await _fixture()
            uid_new = await _user(db, 444)
            uid_buyer = await _user(db, 555)
            await db.create_order(
                user_id=uid_buyer, subtotal_cents=100, discount_cents=0,
                total_cents=100, payment_method="balance",
                delivery_kind="digital", address=None, phone=None)
            bot = FakeBot()
            # Fresh registrations: inside the 24h delay
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["onboarding"], 0)
            # Age both registrations by 48h
            async with db._db() as c:
                await c.execute("UPDATE users SET created_at=?",
                                (_ago(hours=48),))
                await c.commit()
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["onboarding"], 1)  # only the orderless
            self.assertEqual(bot.sent[-1][0], 444)
            counts = await campaign_worker.process_campaigns_once(db, bot)
            self.assertEqual(counts["onboarding"], 0)
        self.run_async(go())

    def test_claim_release_primitives(self):
        async def go():
            db, cat, p1 = await _fixture()
            self.assertTrue(await db.campaign_claim_send("x", 1, "k"))
            self.assertFalse(await db.campaign_claim_send("x", 1, "k"))
            await db.campaign_release_send("x", 1, "k")
            self.assertTrue(await db.campaign_claim_send("x", 1, "k"))
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
