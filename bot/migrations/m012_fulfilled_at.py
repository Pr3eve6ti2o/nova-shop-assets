"""Order fulfilment marker (usability-smoke find, 2026-10-13).

fulfill_order_atomic guarded and marked fulfilment by writing
status='fulfilled' — a value the orders CHECK constraint has never
allowed, so every real payment fulfilment raised IntegrityError.
The lifecycle vocabulary is canonical (confirmed → shipped →
delivered); fulfilment (values claimed / stock decremented) gets
its own timestamp marker instead, mirroring shipped_at/delivered_at.
"""

VERSION = 12
DESCRIPTION = "Add orders.fulfilled_at fulfilment marker"


async def up(db):
    async with db._db() as conn:
        try:
            await conn.execute(
                "ALTER TABLE orders ADD COLUMN fulfilled_at TEXT")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise
        await conn.commit()


async def down(db):
    pass  # SQLite cannot drop columns pre-3.35 everywhere; marker stays.
