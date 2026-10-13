"""Server-cart tests (port plan 8.1): updated_at stamps, Mini App mirror,
idle-cart detection for the campaign engine.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_cart_sync.py
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
    user = await db.create_user(515151, "Cart Tester")
    uid = user["id"]
    cat = await db.add_category("Test")
    p1 = await db.add_product(category_id=cat, name="Widget",
                              price_cents=1500, stock=-1)
    p2 = await db.add_product(category_id=cat, name="Gadget",
                              price_cents=2500, stock=5)
    return db, uid, p1, p2


class CartSync(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_mutations_stamp_updated_at(self):
        async def go():
            db, uid, p1, _ = await _fixture()
            await db.cart_add(uid, p1, 2)
            items = await db.cart_items(uid)
            self.assertEqual(len(items), 1)
            self.assertIsNotNone(items[0]["updated_at"])
            stamp1 = items[0]["updated_at"]
            await db.cart_set_qty(uid, p1, 3)
            items = await db.cart_items(uid)
            self.assertGreaterEqual(items[0]["updated_at"], stamp1)
            self.assertEqual(items[0]["qty"], 3)
        self.run_async(go())

    def test_mirror_replaces_cart(self):
        async def go():
            db, uid, p1, p2 = await _fixture()
            await db.cart_add(uid, p1, 1)
            await db.cart_mirror(uid, [{"product_id": p2, "qty": 4}])
            items = await db.cart_items(uid)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["product_id"], p2)
            self.assertEqual(items[0]["qty"], 4)
            self.assertIsNotNone(items[0]["updated_at"])
        self.run_async(go())

    def test_idle_detection(self):
        async def go():
            db, uid, p1, p2 = await _fixture()
            await db.cart_add(uid, p1, 2)   # 2 x $15 = $30
            await db.cart_add(uid, p2, 1)   # 1 x $25 = $25
            # Fresh cart: not idle
            self.assertEqual(await db.carts_idle(60), [])
            # Age the cart by 2 hours (same ISO format the code writes)
            from datetime import datetime, timedelta, timezone
            aged = (datetime.now(timezone.utc)
                    - timedelta(hours=2)).isoformat(timespec="seconds")
            async with db._db() as conn:
                await conn.execute(
                    "UPDATE cart_items SET updated_at=?"
                    " WHERE user_id=?", (aged, uid))
                await conn.commit()
            idle = await db.carts_idle(60)
            self.assertEqual(len(idle), 1)
            self.assertEqual(idle[0]["user_id"], uid)
            self.assertEqual(idle[0]["items"], 2)
            self.assertEqual(idle[0]["total_cents"], 5500)
            # A short idle window still excludes it at 3h threshold
            self.assertEqual(await db.carts_idle(180), [])
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
