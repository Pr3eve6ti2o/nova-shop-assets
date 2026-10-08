"""Versioned database migrations (re-audit P3.22).

Each migration is a Python module named `mNNN_description.py` with:
- `VERSION: int` — the migration number
- `DESCRIPTION: str` — human-readable description
- `async def up(db)` — apply the migration
- `async def down(db)` — (optional) revert the migration

Migrations run in version order. Applied versions are tracked in the
`schema_migrations` table.

Usage:
    from migrations import run_migrations
    await run_migrations(db)
"""
