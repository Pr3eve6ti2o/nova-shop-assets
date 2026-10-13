"""Store credit lots (port plan Part 4 — DoktorShift credit mechanics
on our balance ledger).

Every balance credit becomes a LOT (amount, remaining, source,
optional expiry). Debits consume lots oldest-first (FIFO) with
per-lot conditional decrements; each consumption is recorded in
credit_lot_spends so a failed fulfilment can restore the exact lots
it took, newest first (LIFO). From this migration on, the invariant

    users.balance_cents == SUM(credit_lots.remaining_cents)

holds for every user; existing balances are backfilled as a single
'legacy' lot per user so the invariant starts true.
"""

VERSION = 10
DESCRIPTION = "Add credit_lots + credit_lot_spends with legacy backfill"


async def up(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS credit_lots("
            " id INTEGER PRIMARY KEY,"
            " user_id INTEGER NOT NULL,"
            " source TEXT NOT NULL,"
            " amount_cents INTEGER NOT NULL,"
            " remaining_cents INTEGER NOT NULL,"
            " expires_at TEXT,"
            " created_at TEXT NOT NULL)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_credit_lots_user"
            " ON credit_lots(user_id, remaining_cents)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS credit_lot_spends("
            " id INTEGER PRIMARY KEY,"
            " lot_id INTEGER NOT NULL REFERENCES credit_lots(id),"
            " user_id INTEGER NOT NULL,"
            " order_id INTEGER,"
            " amount_cents INTEGER NOT NULL,"
            " created_at TEXT NOT NULL,"
            " reversed_at TEXT)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_credit_spends_order"
            " ON credit_lot_spends(order_id)")
        # Backfill: one legacy lot per existing positive balance.
        from database import utcnow_iso
        now = utcnow_iso()
        await conn.execute(
            "INSERT INTO credit_lots"
            "(user_id, source, amount_cents, remaining_cents, created_at)"
            " SELECT id, 'legacy', balance_cents, balance_cents, ?"
            " FROM users WHERE balance_cents > 0"
            " AND NOT EXISTS (SELECT 1 FROM credit_lots c"
            "                 WHERE c.user_id = users.id)",
            (now,))
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS credit_lot_spends")
        await conn.execute("DROP TABLE IF EXISTS credit_lots")
        await conn.commit()
