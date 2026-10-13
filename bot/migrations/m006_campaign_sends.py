"""Add campaign_sends log (port plan Part 2).

The campaign engine (abandoned cart, back-in-stock, post-purchase,
onboarding nudge) records every send here. The UNIQUE(campaign,
user_id, dedup_key) constraint is the dedup mechanism: a send is
claimed by inserting its row, and a duplicate claim inserts nothing.
"""

VERSION = 6
DESCRIPTION = "Add campaign_sends table for the campaign engine"


async def up(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS campaign_sends("
            " id INTEGER PRIMARY KEY,"
            " campaign TEXT NOT NULL,"
            " user_id INTEGER NOT NULL,"
            " dedup_key TEXT NOT NULL,"
            " sent_at TEXT NOT NULL,"
            " UNIQUE(campaign, user_id, dedup_key))")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_campaign_sends_user"
            " ON campaign_sends(user_id, campaign)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS campaign_sends")
        await conn.commit()
