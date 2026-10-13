"""Add cart_items.updated_at (port plan 8.1).

The bot cart is server-side, but rows carried no timestamp, so nothing
could tell an abandoned cart from an active one. updated_at is stamped
by every cart mutation and indexed for the campaign engine's idle scan
(port plan Part 2). Existing rows are backfilled with the migration
time (they age into eligibility naturally).
"""

VERSION = 5
DESCRIPTION = "Add cart_items.updated_at for abandoned-cart detection"


async def up(db):
    async with db._db() as conn:
        try:
            await conn.execute(
                "ALTER TABLE cart_items ADD COLUMN updated_at TEXT")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise
        from database import utcnow_iso
        await conn.execute(
            "UPDATE cart_items SET updated_at=? WHERE updated_at IS NULL",
            (utcnow_iso(),))
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cart_items_updated"
            " ON cart_items(updated_at)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP INDEX IF EXISTS idx_cart_items_updated")
        await conn.commit()
