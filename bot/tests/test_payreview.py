"""Payreview + refunds ledger tests (port plan Part 6): fingerprint
idempotency, resolve claims, note requirements, and the fail-closed
refund ceiling.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_payreview.py
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
    u = await db.create_user(888, "Pay Tester")
    oid = await db.create_order(
        user_id=u["id"], subtotal_cents=5000, discount_cents=0,
        total_cents=5000, payment_method="ton", delivery_kind="digital",
        address=None, phone=None)
    return db, u["id"], oid


class Payreview(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_anomaly_idempotent_and_resolvable_once(self):
        async def go():
            db, uid, oid = await _fixture()
            fp = db.anomaly_fingerprint("tonconnect", "pending", 7)
            a1 = await db.anomaly_record(
                "tonconnect", fp, "unmatched", external_id="TC-1",
                user_id=uid, amount_text="100 nanoTON")
            a2 = await db.anomaly_record(
                "tonconnect", fp, "unmatched again",
                external_id="TC-1", user_id=uid)
            self.assertEqual(a1, a2)  # same row, recorded once
            self.assertEqual(len(await db.anomalies_open()), 1)
            # Notes are mandatory — they are the audit trail
            with self.assertRaises(ValueError):
                await db.anomaly_resolve(a1, 1, "settled", note="  ")
            self.assertTrue(await db.anomaly_resolve(
                a1, 1, "settled", note="credited manually",
                amount_cents=500))
            # A second resolution is refused
            self.assertFalse(await db.anomaly_resolve(
                a1, 1, "dismissed", note="too late"))
            res = await db.anomaly_resolutions(a1)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["action"], "settled")
            self.assertEqual(await db.anomalies_open(), [])
        self.run_async(go())

    def test_refund_ceiling_fail_closed(self):
        async def go():
            db, uid, oid = await _fixture()
            await db.record_refund(oid, uid, 3000, "balance")
            await db.record_refund(oid, uid, 2000, "manual")
            # 3000 + 2000 = the full 5000 total; one cent more is refused
            with self.assertRaises(ValueError):
                await db.record_refund(oid, uid, 1, "balance")
            rows = await db.refunds_for_order(oid)
            self.assertEqual(sum(r["amount_cents"] for r in rows), 5000)
            # Unknown order also fails closed
            with self.assertRaises(ValueError):
                await db.record_refund(999999, uid, 1, "balance")
        self.run_async(go())

    def test_revenue_by_day(self):
        async def go():
            db, uid, oid = await _fixture()
            await db.set_order_status(oid, "delivered")
            days = await db.revenue_by_day(7)
            self.assertEqual(len(days), 1)
            self.assertEqual(days[0]["cents"], 5000)
            self.assertEqual(days[0]["n"], 1)
            # Pending orders don't count as revenue
            await db.create_order(
                user_id=uid, subtotal_cents=700, discount_cents=0,
                total_cents=700, payment_method="balance",
                delivery_kind="digital", address=None, phone=None)
            days = await db.revenue_by_day(7)
            self.assertEqual(days[0]["cents"], 5000)
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
