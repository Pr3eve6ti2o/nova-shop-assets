# P3.20: PostgreSQL Migration Path

## Current state

The bot uses SQLite (`data/nova_shop.db`, WAL mode) via `aiosqlite`. This is
correct for the current single-replica deployment: one bot process, one
watcher process, both on the same machine.

## Why PostgreSQL matters

SQLite cannot serve multiple replicas. The production architecture
(re-audit §"RECOMMENDED FINAL ARCHITECTURE") has:

- Multiple bot replicas (Telegram allows one poller per token, but webhooks
  allow horizontal scaling)
- Separate watcher service
- Separate outbox worker

All of these need a shared database. PostgreSQL is the target.

## Migration strategy

### Phase 1: Abstraction (this commit)

- `bot/db/__init__.py` — backend factory: `get_db()` returns SQLite or
  PostgreSQL based on `DATABASE_URL`
- `bot/db/postgres.py` — asyncpg-based implementation skeleton
- `bot/db/sqlite.py` — current aiosqlite implementation (moved, unchanged)

### Phase 2: SQL dialect translation

Key differences to handle:

| SQLite | PostgreSQL |
|---|---|
| `?` placeholders | `$1`, `$2`, ... |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `INSERT OR REPLACE` | `INSERT ... ON CONFLICT DO UPDATE` |
| `datetime('now', ...)` | `NOW() + INTERVAL` |
| `AUTOINCREMENT` | `SERIAL` / `GENERATED ALWAYS AS IDENTITY` |
| `BEGIN IMMEDIATE` | `BEGIN` (PostgreSQL uses MVCC, no lock upgrade) |

### Phase 3: Data migration

1. `pgloader` or custom script: SQLite → PostgreSQL
2. Verify row counts per table
3. Cutover: stop bot, migrate, update `DATABASE_URL`, start bot

### Phase 4: Multi-replica

- Replace `BEGIN IMMEDIATE` coarse locks with row-level `SELECT ... FOR UPDATE`
- Outbox claim: `SELECT ... FOR UPDATE SKIP LOCKED` (true multi-worker)
- Distributed rate limits via PostgreSQL advisory locks or Redis

## What is NOT changing

- The control plane (`identity/`) already uses PostgreSQL via Drizzle.
- SQLite remains the default for development and single-replica production.
- Set `DATABASE_URL=postgresql://...` to use PostgreSQL when ready.
