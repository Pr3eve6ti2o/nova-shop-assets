"""Store credit, Medusa-style (plan 2026-10-14): ledger provenance,
gift cards, order origin.

Medusa's store-credit model keeps an append-only transaction ledger in
which every movement carries who caused it (actor), why (note) and what
it belongs to (reference + reference id). Nova's balance_transactions
predates that discipline: it knows the type, the signed amount and the
resulting balance, but not the actor, the reason or the reference.

This migration:
- adds actor_type / actor_id / note / reference / reference_id to
  balance_transactions (all nullable; historical rows stay valid);
- creates gift_cards: stored-value codes (value/remaining in cents,
  status lifecycle active -> redeemed | revoked | expired) that redeem
  into balance as credit lots;
- adds orders.origin ('bot' | 'miniapp' | 'admin' | 'payload') so
  admin-created (manual/comp) orders are filterable.
"""

VERSION = 14
DESCRIPTION = "Store credit: ledger actor/note/reference, gift_cards, orders.origin"


async def up(db):
    async with db._db() as conn:
        for col in ("actor_type TEXT", "actor_id TEXT", "note TEXT",
                    "reference TEXT", "reference_id TEXT"):
            try:
                await conn.execute(
                    f"ALTER TABLE balance_transactions ADD COLUMN {col}")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS gift_cards("
            " id INTEGER PRIMARY KEY,"
            " code TEXT NOT NULL UNIQUE,"
            " value_cents INTEGER NOT NULL CHECK (value_cents > 0),"
            " remaining_cents INTEGER NOT NULL CHECK (remaining_cents >= 0),"
            " status TEXT NOT NULL DEFAULT 'active'"
            "   CHECK (status IN ('active','redeemed','revoked','expired')),"
            " expires_at TEXT,"
            " created_by TEXT,"
            " note TEXT,"
            " redeemed_by_user_id INTEGER REFERENCES users(id),"
            " redeemed_at TEXT,"
            " created_at TEXT NOT NULL)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gift_cards_status"
            " ON gift_cards(status)")
        try:
            await conn.execute(
                "ALTER TABLE orders ADD COLUMN origin TEXT DEFAULT 'bot'")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                raise
        await conn.commit()


async def down(db):
    pass  # Additive only; columns/tables stay (SQLite DROP is unsafe here).
