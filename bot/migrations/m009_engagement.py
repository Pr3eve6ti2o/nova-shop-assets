"""Engagement data (port plan Part 5).

- wishlist gains price_at_add_cents + price_notified_at, the two
  columns the price-drop alert pass needs (JumpCodeFrog pattern,
  including its re-arm on price recovery).
- users gains loyalty_points (lifetime, status-only per the source
  design); loyalty_txs is the per-order accrual ledger (UNIQUE
  order_id makes accrual idempotent).
- promos gains category_id (discount applies to that category only)
  and bound_user_id (a personal code, invisible to everyone else).
"""

VERSION = 9
DESCRIPTION = "Wishlist price tracking, loyalty points, promo scope columns"

_ALTERS = (
    ("wishlist", "price_at_add_cents",
     "ALTER TABLE wishlist ADD COLUMN price_at_add_cents INTEGER"),
    ("wishlist", "price_notified_at",
     "ALTER TABLE wishlist ADD COLUMN price_notified_at TEXT"),
    ("users", "loyalty_points",
     "ALTER TABLE users ADD COLUMN loyalty_points INTEGER NOT NULL DEFAULT 0"),
    ("promos", "category_id",
     "ALTER TABLE promos ADD COLUMN category_id INTEGER"),
    ("promos", "bound_user_id",
     "ALTER TABLE promos ADD COLUMN bound_user_id INTEGER"),
)


async def up(db):
    async with db._db() as conn:
        for _table, _col, ddl in _ALTERS:
            try:
                await conn.execute(ddl)
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS loyalty_txs("
            " id INTEGER PRIMARY KEY,"
            " user_id INTEGER NOT NULL,"
            " order_id INTEGER NOT NULL UNIQUE,"
            " points INTEGER NOT NULL,"
            " created_at TEXT NOT NULL)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS loyalty_txs")
        await conn.commit()
