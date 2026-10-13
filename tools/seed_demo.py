#!/usr/bin/env python3
"""Seed demo data (port plan 7.4) — PORTED from
JumpCodeFrog/telegram-shop-bot `cmd/seed/main.go`, adapted to Nova
Shop's schema with minor changes (English demo catalogue per house
rule, prices in USD cents, our Database helpers instead of raw SQL;
the source's idempotent INSERT OR IGNORE discipline is kept — running
it twice creates no duplicates).

Seeds into DATABASE_PATH if set, else bot/data/demo.db — never the
live database unless you point DATABASE_PATH at it yourself.

Usage:  BOT_TOKEN=<any> python3 tools/seed_demo.py [db_path]
(The seed talks to no Telegram API; BOT_TOKEN only satisfies config
import, exactly as in the test-suite fixtures.)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))
os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402

CATEGORIES = [
    ("Clothing", "👕"),
    ("Shoes", "👟"),
    ("Accessories", "🎒"),
]

# (category, name, description, price_cents, stock)
PRODUCTS = [
    ("Clothing", "Basic T-Shirt", "100% cotton, sizes S–XXL", 1299, 50),
    ("Clothing", "Oversized Hoodie", "Fleece, unisex, black/grey", 2999, 30),
    ("Shoes", "Running Trainers", "Lightweight sole, breathable upper", 4999, 20),
    ("Shoes", "Slip-Ons", "Elastic fit, summer style", 1999, 40),
    ("Accessories", "City Backpack", 'Fits a 15.6" laptop', 3499, 25),
    ("Accessories", "Embroidered Cap", "One size, adjustable strap", 999, 100),
]

PROMOS = [  # (code, percent, max_uses)
    ("WELCOME10", 10, 100),
    ("SALE20", 20, 50),
]


async def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "DATABASE_PATH") or os.path.join(
            os.path.dirname(__file__), "..", "bot", "data", "demo.db")
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = Database(db_path)
    await db.create_tables()

    cat_ids = {}
    for name, emoji in CATEGORIES:
        async with db._db() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO categories(name, emoji) VALUES (?, ?)",
                (name, emoji))
            await conn.commit()
            async with conn.execute(
                    "SELECT id FROM categories WHERE name=?", (name,)) as cur:
                cat_ids[name] = (await cur.fetchone())["id"]
    print("categories seeded")

    for cat, name, desc, cents, stock in PRODUCTS:
        async with db._db() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO products"
                "(category_id, name, description, price_cents, kind, stock,"
                " is_active, created_at)"
                " SELECT ?, ?, ?, ?, 'physical', ?, 1, ?"
                " WHERE NOT EXISTS (SELECT 1 FROM products WHERE name=?)",
                (cat_ids[cat], name, desc, cents, stock,
                 "2026-01-01T00:00:00+00:00", name))
            await conn.commit()
    print("products seeded")

    for code, pct, max_uses in PROMOS:
        async with db._db() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO promos"
                "(code, kind, value, max_uses, used_count, is_active)"
                " VALUES (?, 'percent', ?, ?, 0, 1)",
                (code, pct, max_uses))
            await conn.commit()
    print("promo codes seeded")
    print(f"seed complete — demo database ready at {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
