"""Add returns workflow + fulfilment timestamps (port plan 1.1/1.2).

Pattern adapted from DoktorShift/telegramshop's returns model:
customer-initiated request -> admin approve/deny (deny requires a note)
-> refund to balance or manual handling. Order rows gain shipped_at /
delivered_at stamps so fulfilment tracking has real timestamps.
"""

VERSION = 4
DESCRIPTION = "Add returns table + orders.shipped_at/delivered_at"


async def up(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS returns("
            " id INTEGER PRIMARY KEY,"
            " order_id INTEGER NOT NULL REFERENCES orders(id),"
            " user_id INTEGER NOT NULL,"
            " reason TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'requested'"
            "   CHECK (status IN ('requested','approved','denied','refunded')),"
            " admin_note TEXT,"
            " refund_cents INTEGER,"
            " refund_target TEXT"
            "   CHECK (refund_target IN ('balance','manual')),"
            " created_at TEXT NOT NULL,"
            " decided_at TEXT,"
            " decided_by INTEGER)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_returns_order"
            " ON returns(order_id, status)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_returns_status"
            " ON returns(status, created_at)")
        for col in ("shipped_at", "delivered_at"):
            try:
                await conn.execute(
                    f"ALTER TABLE orders ADD COLUMN {col} TEXT")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS returns")
        await conn.commit()
