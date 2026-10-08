"""Add rate_limit_hits table (re-audit P3.21)."""

VERSION = 2
DESCRIPTION = "Add rate_limit_hits table for distributed rate limiting"


async def up(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_limit_hits("
            " bucket TEXT NOT NULL,"
            " user_id INTEGER NOT NULL,"
            " hit_at TEXT NOT NULL,"
            " PRIMARY KEY (bucket, user_id, hit_at))")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_lookup"
            " ON rate_limit_hits(bucket, user_id, hit_at)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS rate_limit_hits")
        await conn.commit()
