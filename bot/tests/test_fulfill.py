"""Fulfilment regression tests (usability-smoke find, 2026-10-13).

fulfill_order_atomic wrote status='fulfilled', which the orders
CHECK constraint rejects — every real payment fulfilment crashed
with IntegrityError while 59 unit tests stayed green (none of them
fulfilled a valid order end-to-end). These tests do exactly that.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_fulfill.py
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402


class FulfillAtomic(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_fulfil_valid_order_end_to_end(self):
        async def go():
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = Database(path)
            await db.create_tables()
            cat = await db.add_category("Test")
            dig = await db.add_product(
                category_id=cat, name="Key", price_cents=500,
                kind="digital", is_unlimited=False)
            await db.add_product_values(dig, ["KEY-1", "KEY-2", "KEY-3"])
            phys = await db.add_product(
                category_id=cat, name="Box", price_cents=700, stock=5)
            u = await db.create_user(70707, "Fulfiller")
            oid = await db.create_order(
                user_id=u["id"], subtotal_cents=1700, discount_cents=0,
                total_cents=1700, payment_method="balance",
                delivery_kind="pickup", address=None, phone=None)
            await db.add_order_item(oid, dig, "Key", 2, 500)
            await db.add_order_item(oid, phys, "Box", 1, 700)
            await db.set_order_status(oid, "confirmed")

            ok, reason = await db.fulfill_order_atomic(oid)
            self.assertTrue(ok, reason)
            order = await db.get_order(oid)
            # Status stays in the CHECK vocabulary; marker is set.
            self.assertEqual(order["status"], "confirmed")
            self.assertTrue(order["fulfilled_at"])
            items = await db.get_order_items(oid)
            dig_item = [i for i in items if i["product_id"] == dig][0]
            self.assertIn("KEY-", dig_item["delivered_value"])
            self.assertEqual(len(dig_item["delivered_value"].splitlines()), 2)
            self.assertEqual((await db.get_product(phys))["stock"], 4)

            # Second fulfilment: refused, nothing double-claimed.
            ok2, reason2 = await db.fulfill_order_atomic(oid)
            self.assertFalse(ok2)
            self.assertEqual(reason2, "already_fulfilled")
            self.assertEqual((await db.get_product(phys))["stock"], 4)
            async with db._db() as conn:
                async with conn.execute(
                        "SELECT COUNT(*) c FROM product_values"
                        " WHERE product_id=? AND is_used=0", (dig,)) as cur:
                    remaining = (await cur.fetchone())["c"]
            self.assertEqual(remaining, 1)
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
