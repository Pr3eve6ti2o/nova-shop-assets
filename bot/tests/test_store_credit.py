"""Store credit (Medusa borrow, plan 2026-10-14) — Phase 1 gates:
ledger provenance, admin credit/debit, gift cards, manual orders.

Invariants enforced: no deposit bonus on admin/gift credits; debits
fail closed above the balance; gift cards redeem exactly once per cent;
balance == unexpired lot total == last ledger balance_after.

Run: BOT_TOKEN=<dummy> python -m unittest tests.test_store_credit
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
    cat = await db.add_category("Gear")
    p1 = await db.add_product(category_id=cat, name="Widget",
                              price_cents=2500, stock=-1)
    p2 = await db.add_product(category_id=cat, name="Gadget",
                              price_cents=1000, stock=-1)
    u = await db.create_user(777, "Credit Tester")
    return db, path, u["id"], p1, p2


class StoreCredit(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_migration_m014_shape(self):
        async def go():
            db, path, uid, *_ = await _fixture()
            try:
                async with db._db() as c:
                    async with c.execute(
                            "PRAGMA table_info(balance_transactions)") as cur:
                        cols = {r["name"] for r in await cur.fetchall()}
                    async with c.execute(
                            "SELECT name FROM sqlite_master"
                            " WHERE type='table' AND name='gift_cards'") as cur:
                        self.assertIsNotNone(await cur.fetchone())
                for col in ("actor_type", "actor_id", "note", "reference",
                            "reference_id"):
                    self.assertIn(col, cols)
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_admin_credit_no_bonus_and_ledger_provenance(self):
        async def go():
            db, path, uid, *_ = await _fixture()
            try:
                bal = await db.adjust_balance(
                    uid, 10000, tx_type="admin_credit", actor_type="admin",
                    actor_id=42, note="goodwill", reference="admin")
                # Exactly 10000 — the 5% top-up bonus must NOT apply.
                self.assertEqual(bal, 10000)
                self.assertEqual(await db.get_balance(uid), 10000)
                self.assertEqual(await db.credit_lots_total(uid), 10000)
                rows = await db.list_balance_transactions(uid)
                self.assertEqual(len(rows), 1)
                r = rows[0]
                self.assertEqual(r["type"], "admin_credit")
                self.assertEqual(r["amount_cents"], 10000)
                self.assertEqual(r["balance_after_cents"], 10000)
                self.assertEqual(r["actor_type"], "admin")
                self.assertEqual(r["actor_id"], "42")
                self.assertEqual(r["note"], "goodwill")
                stats = await db.account_stats(uid)
                self.assertEqual(stats["total_credits_cents"], 10000)
                self.assertEqual(stats["total_debits_cents"], 0)
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_admin_debit_fails_closed_and_consumes_lots(self):
        async def go():
            db, path, uid, *_ = await _fixture()
            try:
                await db.adjust_balance(
                    uid, 5000, tx_type="admin_credit", actor_type="admin",
                    actor_id=1, note="seed")
                out = await db.adjust_balance(
                    uid, -7000, tx_type="admin_debit", actor_type="admin",
                    actor_id=1, note="too much")
                self.assertIsNone(out)  # exceeds balance: refused
                self.assertEqual(await db.get_balance(uid), 5000)
                out = await db.adjust_balance(
                    uid, -2000, tx_type="admin_debit", actor_type="admin",
                    actor_id=1, note="correction")
                self.assertEqual(out, 3000)
                self.assertEqual(await db.credit_lots_total(uid), 3000)
                stats = await db.account_stats(uid)
                self.assertEqual(stats["total_debits_cents"], 2000)
                self.assertEqual(stats["transactions"], 2)
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_giftcard_full_partial_expired_revoked(self):
        async def go():
            db, path, uid, *_ = await _fixture()
            try:
                card = await db.giftcard_create(
                    4000, created_by="admin:1", note="promo prize")
                self.assertEqual(card["remaining_cents"], 4000)
                ok, info = await db.giftcard_redeem(card["code"], uid,
                                                    amount_cents=1500)
                self.assertTrue(ok)
                self.assertEqual(info["remaining_cents"], 2500)
                self.assertEqual(await db.get_balance(uid), 1500)
                # Second redemption of the remainder, then it's spent.
                ok, info = await db.giftcard_redeem(card["code"], uid)
                self.assertTrue(ok)
                self.assertEqual(info["remaining_cents"], 0)
                self.assertEqual(await db.get_balance(uid), 4000)
                ok, reason = await db.giftcard_redeem(card["code"], uid)
                self.assertFalse(ok)
                self.assertEqual(reason, "redeemed")
                # Unknown code / revoked card / expired card.
                ok, reason = await db.giftcard_redeem("NOVA-XXXX-XXXX-XXXX",
                                                      uid)
                self.assertEqual((ok, reason), (False, "not_found"))
                card2 = await db.giftcard_create(1000, created_by="admin:1")
                self.assertTrue(await db.giftcard_revoke(card2["id"]))
                ok, reason = await db.giftcard_redeem(card2["code"], uid)
                self.assertEqual((ok, reason), (False, "revoked"))
                async with db._db() as c:
                    await c.execute(
                        "INSERT INTO gift_cards(code, value_cents,"
                        " remaining_cents, status, expires_at, created_at)"
                        " VALUES ('NOVA-OLD0-OLD0-OLD0', 500, 500,"
                        " 'active', '2000-01-01T00:00:00+00:00',"
                        " '2000-01-01T00:00:00+00:00')")
                    await c.commit()
                ok, reason = await db.giftcard_redeem(
                    "NOVA-OLD0-OLD0-OLD0", uid)
                self.assertEqual((ok, reason), (False, "expired"))
                # Invariant still holds after everything.
                self.assertEqual(await db.get_balance(uid),
                                 await db.credit_lots_total(uid))
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_manual_orders_comp_and_balance(self):
        async def go():
            db, path, uid, p1, p2 = await _fixture()
            try:
                await db.adjust_balance(
                    uid, 3000, tx_type="admin_credit", actor_type="admin",
                    actor_id=1, note="seed")
                # Comp: no money moves, order is confirmed, manual payment 0.
                oid, reason = await db.create_manual_order(
                    uid, [(p1, 1), (p2, 2)], kind="comp", actor_tg_id=99,
                    note="review unit")
                self.assertIsNone(reason)
                order = await db.get_order(oid)
                self.assertEqual(order["status"], "confirmed")
                self.assertEqual(order["total_cents"], 4500)
                self.assertEqual(order["payment_method"], "comp")
                self.assertEqual(order["origin"], "admin")
                self.assertEqual(await db.get_balance(uid), 3000)
                pays = await db.get_payments_by_order(oid)
                self.assertEqual(len(pays), 1)
                self.assertEqual(pays[0]["provider"], "manual")
                self.assertEqual(pays[0]["amount_cents"], 0)
                # Balance-charged: 3000 available, order of 2500 succeeds.
                oid2, reason = await db.create_manual_order(
                    uid, [(p1, 1)], kind="balance", actor_tg_id=99)
                self.assertIsNone(reason)
                self.assertEqual(await db.get_balance(uid), 500)
                self.assertEqual(await db.credit_lots_total(uid), 500)
                # Insufficient: refused, order cancelled, balance untouched.
                oid3, reason = await db.create_manual_order(
                    uid, [(p1, 1)], kind="balance", actor_tg_id=99)
                self.assertIsNone(oid3)
                self.assertEqual(reason, "insufficient_balance")
                self.assertEqual(await db.get_balance(uid), 500)
                # Bad product id.
                oid4, reason = await db.create_manual_order(
                    uid, [(999999, 1)], kind="comp", actor_tg_id=99)
                self.assertEqual((oid4, reason), (None, "bad_product"))
            finally:
                os.unlink(path)
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
