"""PostgreSQL backend (re-audit P3.20) — multi-replica production.

This is the structural skeleton. Each method mirrors the SQLite
implementation in database.py but uses asyncpg with $n placeholders
and PostgreSQL-specific SQL.

Status: SCAFFOLD. The SQLite backend remains the default until each
method is ported and tested. See docs/P3-POSTGRESQL-MIGRATION.md.

Key translation rules (applied per-method during porting):
- `?` -> `$1, $2, ...`
- `INSERT OR IGNORE` -> `ON CONFLICT DO NOTHING`
- `BEGIN IMMEDIATE` -> plain transaction (MVCC, no lock upgrade needed)
- `datetime('now', '+X')` -> `NOW() + INTERVAL 'X'`
- Outbox claim: `SELECT ... FOR UPDATE SKIP LOCKED` for multi-worker
"""

import logging

logger = logging.getLogger(__name__)


class PostgresDB:
    """asyncpg-backed database. Mirrors the Database class API."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool = None

    async def connect(self):
        import asyncpg
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        logger.info("PostgreSQL pool connected")

    async def close(self):
        if self._pool:
            await self._pool.close()

    # --- Ported methods go here, one per commit, each with a test. ---
    # Example pattern:
    #
    # async def get_user(self, user_id: int):
    #     async with self._pool.acquire() as conn:
    #         row = await conn.fetchrow(
    #             "SELECT * FROM users WHERE id=$1", user_id)
    #         return dict(row) if row else None

    def __getattr__(self, name):
        raise NotImplementedError(
            f"PostgresDB.{name} not yet ported from SQLite. "
            f"See docs/P3-POSTGRESQL-MIGRATION.md.")
