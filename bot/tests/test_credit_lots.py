"""Credit lot tests (port plan Part 4): FIFO spend, LIFO restore,
expiry forfeiture, and the balance == lots invariant.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_credit_lots.py
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
    u = await db.create_user(4242, "Lot Tester")
    return db, u["id"]


async def _order(db, uid, total=100):
    return await db.create_order(
        user_id=uid, subtotal_cents=total, discount_cents=0,
        total_cents=total, payment_method="balance",
        delivery_kind="digital", address=None, phone=None)


async def _invariant(db, uid):
    return (await db.get_balance(uid)) == (await db.credit_lots_total(uid))


class CreditLots(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_fifo_spend_across_lots(self):
        async def go():
            db, uid = await _fixture()
            # Two grants -> two lots (refund type avoids the topup bonus)
            await db.add_balance(uid, 1000, tx_type="refund")
            await db.add_balance(uid, 2000, tx_type="refund")
            self.assertTrue(await _invariant(db, uid))
            # Spend 1500: lot1 fully, lot2 partially (FIFO)
            oid = await _order(db, uid)
            new_bal = await db.deduct_balance(uid, 1500, order_id=oid)
            self.assertEqual(new_bal, 1500)
            lots = await db.credit_lots_list(uid)
            self.assertEqual([l["remaining_cents"] for l in lots],
                             [0, 1500])
            self.assertTrue(await _invariant(db, uid))
        self.run_async(go())

    def test_lifo_restore_and_shortfall(self):
        async def go():
            db, uid = await _fixture()
            await db.add_balance(uid, 1000, tx_type="refund")
            await db.add_balance(uid, 2000, tx_type="refund")
            oid = await _order(db, uid)
            await db.deduct_balance(uid, 1500, order_id=oid)
            # Restore the full spend: lot2 gets its 500 back first (LIFO
            # spends newest first), then lot1 its 1000. Shortfall 0.
            shortfall = await db.credit_restore_for_order(uid, oid, 1500)
            self.assertEqual(shortfall, 0)
            await db.add_balance(uid, 1500, tx_type="refund",
                                 order_id=oid, lot_cents=shortfall)
            lots = await db.credit_lots_list(uid)
            self.assertEqual([l["remaining_cents"] for l in lots],
                             [1000, 2000])
            self.assertEqual(len(lots), 2)  # no phantom lot was minted
            self.assertTrue(await _invariant(db, uid))
            # A second restore finds nothing left to restore
            shortfall = await db.credit_restore_for_order(uid, oid, 1500)
            self.assertEqual(shortfall, 1500)
        self.run_async(go())

    def test_expiry_forfeits_and_keeps_invariant(self):
        async def go():
            db, uid = await _fixture()
            await db.add_balance(uid, 1000, tx_type="refund")
            # A grant that is already expired (expires_days negative path
            # simulated by direct stamp)
            await db.add_balance(uid, 500, tx_type="refund",
                                 expires_days=365)
            async with db._db() as c:
                await c.execute(
                    "UPDATE credit_lots SET expires_at='2000-01-01T00:00:00'"
                    " WHERE amount_cents=500")
                await c.commit()
            # Expired lot no longer counts as spendable
            self.assertEqual(await db.credit_lots_total(uid), 1000)
            forfeited = await db.credit_sweep_expired()
            self.assertEqual(forfeited, 500)
            self.assertEqual(await db.get_balance(uid), 1000)
            self.assertTrue(await _invariant(db, uid))
            # Spending skips the dead lot entirely
            await db.deduct_balance(uid, 400, order_id=await _order(db, uid))
            self.assertTrue(await _invariant(db, uid))
            self.assertEqual(await db.get_balance(uid), 600)
        self.run_async(go())

    def test_expired_lot_unspendable_before_sweep(self):
        async def go():
            db, uid = await _fixture()
            await db.add_balance(uid, 1000, tx_type="refund")
            await db.add_balance(uid, 500, tx_type="refund",
                                 expires_days=365)
            async with db._db() as c:
                await c.execute(
                    "UPDATE credit_lots SET expires_at='2000-01-01T00:00:00'"
                    " WHERE amount_cents=500")
                await c.commit()
            # No sweep has run: the plain balance still reads 1500, but
            # the expired 500 must not be spendable.
            self.assertEqual(await db.get_balance(uid), 1500)
            out = await db.deduct_balance(
                uid, 1001, order_id=await _order(db, uid))
            self.assertIsNone(out)
            self.assertEqual(await db.get_balance(uid), 1500)
            # The unexpired 1000 is fully spendable.
            new_bal = await db.deduct_balance(
                uid, 1000, order_id=await _order(db, uid))
            self.assertEqual(new_bal, 500)
            # Admin debits (adjust_balance -> deduct_balance) are
            # capped the same way and fail closed.
            out = await db.adjust_balance(
                uid, -1, tx_type="admin_debit", actor_type="admin")
            self.assertIsNone(out)
            # After the sweep forfeits the dead lot, the books agree.
            self.assertEqual(await db.credit_sweep_expired(), 500)
            self.assertEqual(await db.get_balance(uid), 0)
            self.assertTrue(await _invariant(db, uid))
        self.run_async(go())

    def test_topup_bonus_lands_in_the_lot(self):
        async def go():
            db, uid = await _fixture()
            import config
            # DEPOSIT_BONUS_PERCENT is config-driven; the lot must carry
            # the same total the balance was credited with.
            before = await db.get_balance(uid)
            await db.add_balance(uid, 10000, tx_type="topup")
            credited = (await db.get_balance(uid)) - before
            lots = await db.credit_lots_list(uid)
            self.assertEqual(sum(l["amount_cents"] for l in lots), credited)
            self.assertGreaterEqual(credited, 10000)
            self.assertTrue(await _invariant(db, uid))
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
