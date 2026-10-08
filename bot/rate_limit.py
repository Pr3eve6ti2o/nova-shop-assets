"""Distributed rate limiter (re-audit P3.21).

Replaces the in-memory per-process rate limiter with a database-backed
sliding window that works across multiple bot replicas.

How it works:
- Each action records a timestamp in the `rate_limit_hits` table
- `is_allowed()` counts hits in the window; if under limit, records and allows
- Old hits are pruned lazily

For PostgreSQL multi-replica, the INSERT + COUNT is wrapped in a transaction
with the count check. For true atomicity under high concurrency, use
`SELECT ... FOR UPDATE` on a per-user bucket row (PostgreSQL) or rely on
the coarse transaction (SQLite single-writer).

Table (created in migration):
    CREATE TABLE rate_limit_hits (
        bucket TEXT NOT NULL,      -- e.g. "global", "payment"
        user_id INTEGER NOT NULL,
        hit_at TEXT NOT NULL,      -- ISO timestamp
        PRIMARY KEY (bucket, user_id, hit_at)
    );
    CREATE INDEX idx_rate_limit_lookup ON rate_limit_hits(bucket, user_id, hit_at);
"""

import time


async def is_allowed(db, bucket: str, user_id: int, limit: int,
                     window_sec: int = 60) -> bool:
    """Sliding-window rate limit check. Returns True if allowed (and records)."""
    now = time.time()
    cutoff = now - window_sec
    # Use ISO format for SQLite TEXT comparison; PostgreSQL uses TIMESTAMPTZ
    from datetime import datetime, timezone
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    now_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

    async with db._db() as conn:
        # Prune old hits (lazy cleanup)
        await conn.execute(
            "DELETE FROM rate_limit_hits WHERE hit_at < ?", (cutoff_iso,))
        # Count recent hits for this bucket+user
        async with conn.execute(
            "SELECT COUNT(*) AS c FROM rate_limit_hits"
            " WHERE bucket=? AND user_id=? AND hit_at >= ?",
            (bucket, user_id, cutoff_iso)) as cur:
            row = await cur.fetchone()
        count = row["c"] if row else 0
        if count >= limit:
            await conn.commit()
            return False
        # Record this hit
        await conn.execute(
            "INSERT INTO rate_limit_hits(bucket, user_id, hit_at)"
            " VALUES (?, ?, ?)",
            (bucket, user_id, now_iso))
        await conn.commit()
        return True
