"""Database backend factory (re-audit P3.20).

Selects SQLite (default) or PostgreSQL based on DATABASE_URL.

    DATABASE_URL not set  -> SQLite (aiosqlite, single-replica)
    DATABASE_URL=postgresql://... -> PostgreSQL (asyncpg, multi-replica)

Usage:
    from db import get_db
    db = get_db()
"""

import os


def get_db():
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        from db.postgres import PostgresDB
        return PostgresDB(url)
    # Default: existing SQLite implementation
    from database import db
    return db
