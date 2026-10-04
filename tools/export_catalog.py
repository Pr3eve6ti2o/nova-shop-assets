#!/usr/bin/env python3
"""Export the live catalog to miniapp/catalog.json for the Mini App.

Usage:
    python3 tools/export_catalog.py [--db data/nova_shop.db]

Run after every catalog change, then redeploy the static Mini App files.
Only ACTIVE products are exported. Photo file_ids are included for reference
but are NOT usable outside Telegram (see miniapp/README.md).
"""
import argparse
import json
import os
import sqlite3
import sys

# Ensure the project root is on sys.path for `import config`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/nova_shop.db")
    ap.add_argument("--out", default="miniapp/catalog.json")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(root, args.db)
    out_path = os.path.join(root, args.out)
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    cats = [dict(r) for r in con.execute(
        "SELECT id, name, emoji FROM categories ORDER BY sort, id")]
    prods = []
    for r in con.execute(
            "SELECT id, category_id, name, description, photo_file_id,"
            " price_cents, old_price_cents, kind, stock, rating_sum, rating_count"
            " FROM products WHERE is_active=1 ORDER BY category_id, id"):
        prods.append({
            "id": r["id"],
            "category_id": r["category_id"],
            "name": r["name"],
            "description": r["description"] or "",
            "photo_file_id": r["photo_file_id"],  # Telegram-only; see README
            "price_cents": r["price_cents"],
            "old_price_cents": r["old_price_cents"],
            "kind": r["kind"],
            "stock": r["stock"],
            "rating_sum": r["rating_sum"] or 0,
            "reviews": r["rating_count"] or 0,
        })
    con.close()

    # Merchant TON address for TON Connect payments (from .env or config).
    # Reuses the existing TON_DEPOSIT_ADDRESS (the memo-scheme wallet).
    merchant_ton = os.environ.get("TON_DEPOSIT_ADDRESS", "")
    if not merchant_ton:
        try:
            import config as _cfg
            merchant_ton = getattr(_cfg, "TON_DEPOSIT_ADDRESS", "") or ""
        except Exception:
            merchant_ton = ""

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"categories": cats, "products": prods,
                   "merchant_ton_address": merchant_ton}, f,
                  ensure_ascii=False, indent=1)
    print(f"exported {len(cats)} categories, {len(prods)} products -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
