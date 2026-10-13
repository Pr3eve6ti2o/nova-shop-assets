"""Campaign dead-recipient pruning (stress-audit Part G, item M6).

The campaign worker claimed a send slot per (campaign, user, dedup)
and released the claim on ANY delivery failure, so a permanently
unreachable chat (deleted account, bot blocked, seeded fake user)
was retried on every new campaign event forever — a steady stream
of "Chat not found" log noise and wasted API calls.

users gains a consecutive-permanent-failure counter and a mute
flag: after 3 permanent failures (chat not found / bot blocked /
user deactivated) the user is campaign-muted and claim_send
refuses new slots. A successful send resets the counter.
"""

VERSION = 13
DESCRIPTION = "Add users.campaign_fails / campaign_muted for dead-recipient pruning"


async def up(db):
    async with db._db() as conn:
        for col in ("campaign_fails INTEGER NOT NULL DEFAULT 0",
                    "campaign_muted INTEGER NOT NULL DEFAULT 0"):
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await conn.commit()


async def down(db):
    pass  # SQLite cannot drop columns pre-3.35 everywhere; flags stay.
