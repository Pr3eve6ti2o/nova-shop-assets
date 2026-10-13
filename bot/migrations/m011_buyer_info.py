"""Buyer-info fields on orders (port plan 1.3).

Model ported from DoktorShift/telegramshop: orders carry optional
buyer_email / buyer_name (their orders also have buyer_address; ours
already stores the delivery address in orders.address, so it is
reused rather than duplicated). Whether checkout collects them is a
shop setting — BUYER_INFO_MODE=none|email|address (default none:
checkout behaves exactly as before).
"""

VERSION = 11
DESCRIPTION = "Add orders.buyer_email + orders.buyer_name"


async def up(db):
    async with db._db() as conn:
        for col in ("buyer_email", "buyer_name"):
            try:
                await conn.execute(
                    f"ALTER TABLE orders ADD COLUMN {col} TEXT")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await conn.commit()


async def down(db):
    pass  # SQLite cannot drop columns pre-3.35 everywhere; fields stay.
