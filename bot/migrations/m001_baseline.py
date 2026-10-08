"""Baseline migration (re-audit P3.22).

The pre-migration schema was created via inline CREATE TABLE IF NOT EXISTS
statements in database.py. This migration is a no-op marker: it records
that the baseline schema exists, so future migrations have a version to
build on.

All schema changes after this point MUST be new migration files, not
inline CREATE TABLE statements.
"""

VERSION = 1
DESCRIPTION = "Baseline: existing inline schema (no-op marker)"


async def up(db):
    # No-op: the baseline schema already exists via inline CREATE TABLE.
    # This just records version 1 as applied.
    pass


async def down(db):
    # Cannot revert the baseline.
    raise NotImplementedError("Cannot revert baseline migration")
