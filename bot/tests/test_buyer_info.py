"""Buyer-info tests (port plan 1.3): checkout stores the collected
fields; orders created any other way keep them NULL.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_buyer_info.py
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402


class BuyerInfo(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_checkout_atomic_stores_buyer_fields(self):
        async def go():
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = Database(path)
            await db.create_tables()
            cat = await db.add_category("Test")
            pid = await db.add_product(category_id=cat, name="Widget",
                                       price_cents=1000, stock=-1)
            u = await db.create_user(60606, "Buyer")
            await db.cart_add(u["id"], pid, 1)
            oid, reason = await db.create_checkout_atomic(
                user_id=u["id"], subtotal_cents=1000, discount_cents=0,
                total_cents=1000, payment_method="balance",
                delivery_kind="digital", address=None, phone=None,
                items=[(pid, "Widget", 1, 1000)],
                buyer_email="buyer@example.com", buyer_name="Test Buyer")
            self.assertIsNone(reason)
            order = await db.get_order(oid)
            self.assertEqual(order["buyer_email"], "buyer@example.com")
            self.assertEqual(order["buyer_name"], "Test Buyer")
            # Orders from other paths: fields default to NULL
            oid2 = await db.create_order(
                user_id=u["id"], subtotal_cents=100, discount_cents=0,
                total_cents=100, payment_method="balance",
                delivery_kind="digital", address=None, phone=None)
            order2 = await db.get_order(oid2)
            self.assertIsNone(order2["buyer_email"])
            self.assertIsNone(order2["buyer_name"])
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
