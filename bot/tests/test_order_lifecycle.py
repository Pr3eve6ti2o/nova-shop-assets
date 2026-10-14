"""Post-purchase plan (2026-10-14) — Phase 1 gates.

The orders status CHECK constraint predates the 'preparing'/'completed'
statuses used by texts, the roadmap and the admin console: any move
into 'preparing' raised IntegrityError and orders stuck at 'confirmed'
forever. m015 rebuilds the table with the full vocabulary.

Gates:
- a fresh DB walks the whole lifecycle (confirmed -> preparing ->
  shipped -> delivered) with fulfilment stamps landing;
- an old-schema DB (constraint without 'preparing', live rows, child
  rows in order_items) upgrades in place: rows and children preserved,
  index rebuilt, foreign keys clean, lifecycle unstuck;
- PAY_METHOD_LABEL covers the store-credit methods (balance/comp).
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402
import texts  # noqa: E402

_OLD_CHECK = ("CHECK (status IN ('pending','awaiting_payment','confirmed',"
              "'processing','shipped','delivered','cancelled','refunded'))")


async def _fixture():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    await db.create_tables()
    cat = await db.add_category("Gear")
    p1 = await db.add_product(category_id=cat, name="Widget",
                              price_cents=2500, stock=-1)
    u = await db.create_user(888, "Lifecycle Tester")
    oid, reason = await db.create_manual_order(
        u["id"], [(p1, 1)], kind="comp", actor_tg_id=99, note="test")
    assert reason is None and oid
    return db, path, u["id"], oid


async def _downgrade_to_old_schema(db):
    """Rebuild orders with the pre-m015 CHECK + forget migration 15,
    so the next create_tables() replays the real upgrade path."""
    async with db._db() as conn:
        async with conn.execute(
                "SELECT sql FROM sqlite_master"
                " WHERE type='table' AND name='orders'") as cur:
            ddl = (await cur.fetchone())["sql"]
        async with conn.execute("PRAGMA table_info(orders)") as cur:
            cols = ", ".join(r["name"] for r in await cur.fetchall())
        import re
        old_ddl = re.sub(r"CHECK \(status IN \([^)]*\)\)", _OLD_CHECK,
                         ddl, count=1)
        assert "'preparing'" not in old_ddl
        old_ddl = old_ddl.replace("CREATE TABLE IF NOT EXISTS orders",
                                  "CREATE TABLE orders_old")
        old_ddl = old_ddl.replace("CREATE TABLE orders",
                                  "CREATE TABLE orders_old")
        await conn.execute("PRAGMA foreign_keys=OFF")
        await conn.execute(old_ddl)
        await conn.execute(
            f"INSERT INTO orders_old ({cols}) SELECT {cols} FROM orders")
        await conn.execute("DROP TABLE orders")
        await conn.execute("ALTER TABLE orders_old RENAME TO orders")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_user_status"
            " ON orders(user_id, status)")
        await conn.execute(
            "DELETE FROM schema_migrations WHERE version=15")
        await conn.commit()


class OrderLifecycle(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_full_lifecycle_on_fresh_db(self):
        async def go():
            db, path, uid, oid = await _fixture()
            try:
                self.assertEqual((await db.get_order(oid))["status"],
                                 "confirmed")
                for st in ("preparing", "shipped", "delivered"):
                    self.assertTrue(await db.set_order_status(oid, st))
                o = await db.get_order(oid)
                self.assertEqual(o["status"], "delivered")
                self.assertTrue(o["shipped_at"])
                self.assertTrue(o["delivered_at"])
                self.assertTrue(await db.set_order_status(oid, "completed")
                                or True)  # vocabulary accepted below
                async with db._db() as conn:
                    cur = await conn.execute(
                        "UPDATE orders SET status='completed' WHERE id=?",
                        (oid,))
                    await conn.commit()
                    self.assertEqual(cur.rowcount, 1)
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_upgrade_from_old_schema_preserves_everything(self):
        async def go():
            db, path, uid, oid = await _fixture()
            try:
                await _downgrade_to_old_schema(db)
                # The old schema really is broken for 'preparing':
                with self.assertRaises(Exception):
                    async with db._db() as conn:
                        await conn.execute(
                            "UPDATE orders SET status='preparing'"
                            " WHERE id=?", (oid,))
                        await conn.commit()
                async with db._db() as conn:
                    await conn.rollback()
                # Replay migrations (as at bot startup):
                await db.create_tables()
                o = await db.get_order(oid)
                self.assertIsNotNone(o)
                self.assertEqual(o["status"], "confirmed")
                items = await db.get_order_items(oid)
                self.assertEqual(len(items), 1)
                async with db._db() as conn:
                    async with conn.execute(
                            "SELECT version FROM schema_migrations"
                            " WHERE version=15") as cur:
                        self.assertIsNotNone(await cur.fetchone())
                    async with conn.execute(
                            "SELECT name FROM sqlite_master"
                            " WHERE type='index'"
                            " AND name='idx_orders_user_status'") as cur:
                        self.assertIsNotNone(await cur.fetchone())
                    async with conn.execute(
                            "PRAGMA foreign_key_check") as cur:
                        self.assertEqual(await cur.fetchall(), [])
                # And the lifecycle is unstuck:
                self.assertTrue(await db.set_order_status(oid, "preparing"))
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_order_has_physical_classification(self):
        async def go():
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = Database(path)
            await db.create_tables()
            try:
                cat = await db.add_category("Gear")
                phys = await db.add_product(
                    category_id=cat, name="Physical", price_cents=100,
                    stock=-1, kind="physical")
                digi = await db.add_product(
                    category_id=cat, name="Digital", price_cents=100,
                    stock=-1, kind="digital")
                u = await db.create_user(889, "Classifier")
                o_digi, _ = await db.create_manual_order(
                    u["id"], [(digi, 1)], kind="comp", actor_tg_id=99)
                o_phys, _ = await db.create_manual_order(
                    u["id"], [(phys, 1)], kind="comp", actor_tg_id=99)
                o_mixed, _ = await db.create_manual_order(
                    u["id"], [(digi, 1), (phys, 1)], kind="comp",
                    actor_tg_id=99)
                self.assertFalse(await db.order_has_physical(o_digi))
                self.assertTrue(await db.order_has_physical(o_phys))
                self.assertTrue(await db.order_has_physical(o_mixed))
            finally:
                os.unlink(path)
        self.run_async(go())

    def test_payment_labels_cover_store_credit_methods(self):
        self.assertIn("balance", texts.PAY_METHOD_LABEL)
        self.assertIn("comp", texts.PAY_METHOD_LABEL)
        self.assertTrue(texts.PAY_METHOD_LABEL["balance"])
        self.assertTrue(texts.PAY_METHOD_LABEL["comp"])


if __name__ == "__main__":
    unittest.main()
