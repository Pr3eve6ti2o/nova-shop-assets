"""Engagement tests (port plan Part 5): reviews, wishlist price drops,
loyalty tiers, scoped promos.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_engagement.py
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402


async def _fixture():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    await db.create_tables()
    cat_a = await db.add_category("A")
    cat_b = await db.add_category("B")
    pa = await db.add_product(category_id=cat_a, name="Alpha",
                              price_cents=10000, stock=-1)
    pb = await db.add_product(category_id=cat_b, name="Beta",
                              price_cents=10000, stock=-1)
    u = await db.create_user(999, "Engage Tester")
    return db, u["id"], cat_a, cat_b, pa, pb


async def _promo(db, code, kind, value, **kw):
    async with db._db() as c:
        await c.execute(
            "INSERT INTO promos(code, kind, value, category_id,"
            " bound_user_id) VALUES (?, ?, ?, ?, ?)",
            (code, kind, value, kw.get("category_id"),
             kw.get("bound_user_id")))
        await c.commit()


class Engagement(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_review_upsert_updates_aggregates(self):
        async def go():
            db, uid, *_rest, pa, _pb = await _fixture()
            await db.add_review(uid, pa, 5, "Great")
            p = await db.get_product(pa)
            self.assertEqual((p["rating_sum"], p["rating_count"]), (5, 1))
            # Re-review replaces — count stays 1, sum takes the new value
            await db.add_review(uid, pa, 3, "Actually meh")
            p = await db.get_product(pa)
            self.assertEqual((p["rating_sum"], p["rating_count"]), (3, 1))
            rows = await db.list_reviews(pa)
            self.assertEqual(rows[0]["user_name"], "Engage Tester")
            self.assertEqual(rows[0]["text"], "Actually meh")
        self.run_async(go())

    def test_wishlist_drop_lifecycle(self):
        async def go():
            db, uid, _ca, _cb, pa, _pb = await _fixture()
            await db.wishlist_toggle(uid, pa)  # added at $100
            self.assertEqual(await db.wishlist_price_drops(), [])
            await db.update_product(pa, price_cents=9000)  # exactly -10%
            drops = await db.wishlist_price_drops()
            self.assertEqual(len(drops), 1)
            await db.wishlist_drop_mark_notified(uid, pa)
            self.assertEqual(await db.wishlist_price_drops(), [])
            # Recovery re-arms; a new drop notifies again
            await db.update_product(pa, price_cents=10000)
            await db.wishlist_drop_rearm()
            await db.update_product(pa, price_cents=8000)
            self.assertEqual(len(await db.wishlist_price_drops()), 1)
        self.run_async(go())

    def test_loyalty_accrual_and_tiers(self):
        async def go():
            db, uid, *_ = await _fixture()
            # Bronze 1%: a $50 order earns 50 points
            self.assertEqual(await db.loyalty_accrue(uid, 1001, 5000), 50)
            # Idempotent per order
            self.assertEqual(await db.loyalty_accrue(uid, 1001, 5000), 0)
            self.assertEqual(await db.loyalty_points_of(uid), 50)
            # Tier boundaries
            self.assertEqual(db.loyalty_tier(999), ("Bronze", 1))
            self.assertEqual(db.loyalty_tier(1000), ("Silver", 2))
            self.assertEqual(db.loyalty_tier(5000), ("Gold", 5))
            self.assertEqual(db.loyalty_tier(10000), ("VIP", 10))
            self.assertEqual(db.loyalty_next_tier(50), ("Silver", 950))
            self.assertIsNone(db.loyalty_next_tier(10000))
            # At Silver the same $50 earns 100
            async with db._db() as c:
                await c.execute(
                    "UPDATE users SET loyalty_points=1000 WHERE id=?", (uid,))
                await c.commit()
            self.assertEqual(await db.loyalty_accrue(uid, 1002, 5000), 100)
        self.run_async(go())

    def test_scoped_promos(self):
        async def go():
            db, uid, cat_a, _cb, pa, pb = await _fixture()
            items = [{"product_id": pa, "price_cents": 10000, "qty": 1},
                     {"product_id": pb, "price_cents": 10000, "qty": 1}]
            # Category promo: 10% applies to category A only ($100 -> $10)
            await _promo(db, "CAT10", "percent", 10, category_id=cat_a)
            ok, _m, disc, _p = await db.validate_promo(
                "CAT10", uid, 20000, items=items)
            self.assertTrue(ok)
            self.assertEqual(disc, 1000)
            # No items in the category -> invalid
            ok, _m, _d, _p = await db.validate_promo(
                "CAT10", uid, 10000,
                items=[{"product_id": pb, "price_cents": 10000, "qty": 1}])
            self.assertFalse(ok)
            # Personal code: invisible to everyone else
            await _promo(db, "MINE20", "percent", 20, bound_user_id=uid)
            ok, _m, disc, _p = await db.validate_promo(
                "MINE20", uid, 20000, items=items)
            self.assertTrue(ok)
            self.assertEqual(disc, 4000)
            ok, _m, _d, _p = await db.validate_promo(
                "MINE20", uid + 55, 20000, items=items)
            self.assertFalse(ok)
            # Plain promos are untouched by the extension
            await _promo(db, "ALL5", "percent", 5)
            ok, _m, disc, _p = await db.validate_promo(
                "ALL5", uid, 20000)
            self.assertTrue(ok)
            self.assertEqual(disc, 1000)
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
