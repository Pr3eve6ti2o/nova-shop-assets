#!/usr/bin/env python3
"""Seed Payload CMS (Categories + Products) from the live bot catalog.

Reads ~/workspace/nova-shop/data/nova_shop.db and creates matching
Payload documents via the REST API:
  - Categories: matched by name (no duplicates on re-run)
  - Products: matched by botId (= bot product id); status = published
    iff the bot row has is_active=1

Usage:
    python3 admin/scripts/seed_from_bot.py [--dry-run] [--db data/nova_shop.db]

Config: PAYLOAD_URL / PAYLOAD_API_KEY (env or admin/.env).
Idempotent — safe to re-run; existing rows are updated in place.
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

ADMIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(ADMIN_DIR)
ADMIN_ENV = os.path.join(ADMIN_DIR, ".env")


def load_config():
    url = os.environ.get("PAYLOAD_URL", "").strip().rstrip("/")
    key = os.environ.get("PAYLOAD_API_KEY", "").strip()
    if (not url or not key) and os.path.exists(ADMIN_ENV):
        try:
            with open(ADMIN_ENV, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("PAYLOAD_URL=") and not url:
                        url = line.split("=", 1)[1].strip().rstrip("/")
                    elif line.startswith("PAYLOAD_API_KEY=") and not key:
                        key = line.split("=", 1)[1].strip()
        except OSError:
            pass
    return url, key


def req(base, key, method, path, params=None, data=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"users API-Key {key}"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)


def find_one(base, key, collection, field, value):
    res = req(base, key, "GET", f"/api/{collection}",
              {"where[%s][equals]" % field: value, "limit": "1"})
    docs = res.get("docs", [])
    return docs[0] if docs else None


def slugify(name):
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "item"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default="data/nova_shop.db")
    args = ap.parse_args()

    base, key = load_config()
    if not base or not key:
        print("PAYLOAD_URL / PAYLOAD_API_KEY not set (env or admin/.env)",
              file=sys.stderr)
        return 2

    db_path = os.path.join(ROOT, args.db)
    if not os.path.exists(db_path):
        print(f"bot DB not found: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cats = [dict(r) for r in con.execute(
        "SELECT id, name, emoji FROM categories ORDER BY sort, id")]
    prods = [dict(r) for r in con.execute(
        "SELECT id, category_id, name, description, price_cents,"
        " old_price_cents, kind, stock, rating_sum, rating_count, is_active"
        " FROM products ORDER BY id")]
    con.close()

    stats = {"categories": 0, "products": 0, "updated": 0}
    try:
        cat_map = {}  # bot category id -> Payload category id
        for c in cats:
            existing = find_one(base, key, "categories", "name", c["name"])
            if existing:
                cat_map[c["id"]] = existing["id"]
                continue
            if args.dry_run:
                stats["categories"] += 1
                continue
            doc = req(base, key, "POST", "/api/categories", data={
                "name": c["name"],
                "slug": slugify(c["name"]),
                "emoji": c["emoji"] or "📦",
            })["doc"]
            cat_map[c["id"]] = doc["id"]
            stats["categories"] += 1

        for p in prods:
            data = {
                "name": p["name"],
                "slug": slugify(p["name"]) + f"-{p['id']}",
                "description": p["description"] or "",
                "priceCents": p["price_cents"],
                "oldPriceCents": p["old_price_cents"],
                "kind": p["kind"] if p["kind"] in ("physical", "digital") else "physical",
                "stock": p["stock"] if p["stock"] is not None else -1,
                "category": cat_map.get(p["category_id"]),
                "status": "published" if p["is_active"] else "draft",
                "ratingSum": p["rating_sum"] or 0,
                "ratingCount": p["rating_count"] or 0,
                "botId": p["id"],
            }
            existing = find_one(base, key, "products", "botId", p["id"])
            if args.dry_run:
                stats["products" if not existing else "updated"] += 1
                continue
            if existing:
                req(base, key, "PATCH",
                    f"/api/products/{existing['id']}", data=data)
                stats["updated"] += 1
            else:
                req(base, key, "POST", "/api/products", data=data)
                stats["products"] += 1
    except Exception as e:  # noqa: BLE001
        print(f"seed failed: {e}", file=sys.stderr)
        return 1

    mode = "DRY-RUN " if args.dry_run else ""
    print(f"{mode}seed complete: {stats['categories']} categories created, "
          f"{stats['products']} products created, {stats['updated']} products updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
