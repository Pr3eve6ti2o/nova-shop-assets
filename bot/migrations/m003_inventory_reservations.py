"""Add inventory reservations (re-audit P3.23).

Physical stock is reserved at checkout (payment confirmed) and released
on cancel/expiry. Prevents overselling when multiple customers check out
simultaneously.
"""

VERSION = 3
DESCRIPTION = "Add inventory_reservations table for physical stock"


async def up(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS inventory_reservations("
            " id INTEGER PRIMARY KEY,"
            " order_id INTEGER NOT NULL,"
            " product_id INTEGER NOT NULL,"
            " qty INTEGER NOT NULL,"
            " reserved_at TEXT NOT NULL,"
            " expires_at TEXT NOT NULL,"
            " released_at TEXT,"
            " FOREIGN KEY (order_id) REFERENCES orders(id))")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reservations_order"
            " ON inventory_reservations(order_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reservations_product"
            " ON inventory_reservations(product_id, released_at)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS inventory_reservations")
        await conn.commit()
