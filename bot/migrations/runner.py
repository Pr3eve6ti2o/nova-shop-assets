"""Migration runner (re-audit P3.22)."""

import importlib
import logging
import os

logger = logging.getLogger(__name__)


async def _ensure_migrations_table(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            " version INTEGER PRIMARY KEY,"
            " description TEXT NOT NULL,"
            " applied_at TEXT NOT NULL)")
        await conn.commit()


async def _applied_versions(db) -> set:
    await _ensure_migrations_table(db)
    async with db._db() as conn:
        async with conn.execute(
            "SELECT version FROM schema_migrations") as cur:
            rows = await cur.fetchall()
    return {r["version"] for r in rows}


def _discover_migrations() -> list:
    """Find all migration modules in version order."""
    mig_dir = os.path.dirname(os.path.abspath(__file__))
    migrations = []
    for fname in sorted(os.listdir(mig_dir)):
        if fname.startswith("m") and fname.endswith(".py"):
            mod_name = f"migrations.{fname[:-3]}"
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "VERSION") and hasattr(mod, "up"):
                migrations.append(mod)
    return sorted(migrations, key=lambda m: m.VERSION)


async def run_migrations(db):
    """Apply all pending migrations in version order."""
    applied = await _applied_versions(db)
    pending = [m for m in _discover_migrations()
               if m.VERSION not in applied]
    if not pending:
        logger.info("migrations: up to date")
        return 0
    from database import utcnow_iso
    for mod in pending:
        logger.info("migrations: applying m%03d %s",
                    mod.VERSION, getattr(mod, "DESCRIPTION", ""))
        await mod.up(db)
        async with db._db() as conn:
            await conn.execute(
                "INSERT INTO schema_migrations(version, description, applied_at)"
                " VALUES (?, ?, ?)",
                (mod.VERSION, getattr(mod, "DESCRIPTION", ""),
                 utcnow_iso()))
            await conn.commit()
        logger.info("migrations: m%03d applied", mod.VERSION)
    return len(pending)
