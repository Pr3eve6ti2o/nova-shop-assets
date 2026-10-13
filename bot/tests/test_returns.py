"""Returns workflow tests (port plan 1.1) + fulfilment stamps (1.2).

Exercises the database layer against an in-memory DB: creation guards,
the atomic decide claim, exactly-once balance refunds, mandatory denial
notes, the manual-refund path, and shipped/delivered timestamps.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_returns.py
"""
import asyncio
import os
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402


async def _fixture():
    # NB: a temp file, not ":memory:" — the in-memory keepalive connection
    # holds a non-daemon aiosqlite thread open and the test process would
    # never exit.
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    await db.create_tables()
    user = await db.create_user(424242, "Return Tester")
    uid = user["id"] if isinstance(user, dict) else user
    if uid is None:
        uid = (await db.get_user_by_tg(424242))["id"]
    oid = await db.create_order(
        user_id=uid, subtotal_cents=5000, discount_cents=0,
        total_cents=5000, payment_method="balance",
        delivery_kind="digital", address=None, phone=None)
    await db.set_order_status(oid, "delivered")
    return db, uid, oid


class ReturnsFlow(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_create_and_balance_refund_exactly_once(self):
        async def go():
            db, uid, oid = await _fixture()
            rid = await db.create_return(uid, oid, "Key never arrived")
            self.assertEqual((await db.get_return(rid))["status"],
                             "requested")
            before = await db.get_balance(uid)
            outcome = await db.decide_return(rid, 1, approve=True,
                                             refund_target="balance")
            self.assertEqual(outcome, "refunded")
            self.assertEqual(await db.get_balance(uid), before + 5000)
            ret = await db.get_return(rid)
            self.assertEqual(ret["status"], "refunded")
            self.assertEqual(ret["refund_cents"], 5000)
            self.assertEqual((await db.get_order(oid))["status"], "refunded")
            # Second decision attempt must fail and must NOT re-credit.
            with self.assertRaises(ValueError):
                await db.decide_return(rid, 1, approve=True,
                                       refund_target="balance")
            self.assertEqual(await db.get_balance(uid), before + 5000)
        self.run_async(go())

    def test_create_guards(self):
        async def go():
            db, uid, oid = await _fixture()
            # Someone else's order
            with self.assertRaises(ValueError):
                await db.create_return(uid + 999, oid, "not mine")
            # Empty reason
            with self.assertRaises(ValueError):
                await db.create_return(uid, oid, "   ")
            # Pending (unpaid) order is not returnable
            oid2 = await db.create_order(
                user_id=uid, subtotal_cents=100, discount_cents=0,
                total_cents=100, payment_method="balance",
                delivery_kind="digital", address=None, phone=None)
            with self.assertRaises(ValueError):
                await db.create_return(uid, oid2, "changed my mind")
            # Duplicate open return
            await db.create_return(uid, oid, "first")
            with self.assertRaises(ValueError):
                await db.create_return(uid, oid, "second")
        self.run_async(go())

    def test_deny_requires_note_and_notifies_fields(self):
        async def go():
            db, uid, oid = await _fixture()
            rid = await db.create_return(uid, oid, "Just testing")
            with self.assertRaises(ValueError):
                await db.decide_return(rid, 1, approve=False, note="")
            outcome = await db.decide_return(
                rid, 1, approve=False, note="Item was delivered as described.")
            self.assertEqual(outcome, "denied")
            ret = await db.get_return(rid)
            self.assertEqual(ret["status"], "denied")
            self.assertEqual(ret["admin_note"],
                             "Item was delivered as described.")
            self.assertEqual(await db.get_balance(uid), 0)
            self.assertEqual((await db.get_order(oid))["status"], "delivered")
        self.run_async(go())

    def test_manual_path(self):
        async def go():
            db, uid, oid = await _fixture()
            rid = await db.create_return(uid, oid, "Paid by card, want refund")
            outcome = await db.decide_return(rid, 1, approve=True,
                                             refund_target="manual")
            self.assertEqual(outcome, "approved")
            self.assertEqual(await db.get_balance(uid), 0)
            # A negative refund amount is invalid input
            with self.assertRaises(ValueError):
                await db.mark_return_refunded(rid, -1)
            self.assertTrue(await db.mark_return_refunded(rid, 5000))
            self.assertEqual((await db.get_return(rid))["status"], "refunded")
            self.assertEqual((await db.get_order(oid))["status"], "refunded")
            # And it can't be closed twice
            self.assertFalse(await db.mark_return_refunded(rid, 5000))
        self.run_async(go())

    def test_fulfilment_stamps(self):
        async def go():
            db, uid, oid = await _fixture()  # fixture ends 'delivered'
            order = await db.get_order(oid)
            self.assertIsNotNone(order["delivered_at"])
            oid2 = await db.create_order(
                user_id=uid, subtotal_cents=100, discount_cents=0,
                total_cents=100, payment_method="balance",
                delivery_kind="physical", address="x", phone="y")
            await db.set_order_status(oid2, "shipped")
            o2 = await db.get_order(oid2)
            self.assertIsNotNone(o2["shipped_at"])
            self.assertIsNone(o2["delivered_at"])
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
