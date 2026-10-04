#!/usr/bin/env python3
"""Sync the Payload CMS catalog DOWN into the Telegram bot's SQLite DB.

Payload is the source of truth for catalog content. This script:
  - for each Payload product WITH botId: UPDATE the bot's products row
    (name, description, price_cents, old_price_cents, kind, stock, category,
    is_active=1 when status=published else is_active=0)
  - for each Payload product WITHOUT botId: INSERT a new bot row
    (is_active=1 when published; drafts are skipped), then PATCH the
    Payload product with the new bot id (write-back)
  - never DELETEs bot rows; safe and idempotent — re-running changes nothing
    when both sides already agree.

Usage:
    python3 tools/sync_payload_to_bot.py [--dry-run] [--db data/nova_shop.db]

Config (env or ~/workspace/nova-shop/admin/.env):
    PAYLOAD_URL      e.g. http://localhost:3001
    PAYLOAD_API_KEY  API key of the sync user (users collection)

Suggested cron: run a minute or two after catalog edits in the panel, e.g.
    */5 * * * * cd ~/workspace/nova-shop && python3 tools/sync_payload_to_bot.py >> /var/log/nova-payload-sync.log 2>&1
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_ENV = os.path.join(ROOT, "admin", ".env")


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


def api_get(base, key, path, params=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"users API-Key {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def api_patch(base, key, path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        base + path, data=body, method="PATCH",
        headers={"Content-Type": "application/json",
                 "Authorization": f"users API-Key {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_all_products(base, key):
    """All products (published AND draft — drafts with botId must deactivate)."""
    docs, page = [], 1
    while True:
        res = api_get(base, key, "/api/products",
                      {"limit": "100", "page": str(page), "depth": "1"})
        docs.extend(res.get("docs", []))
        if page >= res.get("totalPages", 1):
            break
        page += 1
    return docs


def ensure_bot_category(con, name, emoji, dry_run):
    if not name:
        return None
    row = con.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    if dry_run:
        return -1  # placeholder: would create
    mx = con.execute("SELECT COALESCE(MAX(sort), -1) FROM categories").fetchone()[0]
    cur = con.execute(
        "INSERT INTO categories(name, emoji, sort) VALUES (?, ?, ?)",
        (name, emoji or "📦", mx + 1))
    return cur.lastrowid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would change, write nothing")
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

    try:
        products = fetch_all_products(base, key)
    except Exception as e:  # noqa: BLE001 - report and exit, don't crash cron
        print(f"Payload fetch failed: {e}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    stats = {"updated": 0, "inserted": 0, "deactivated": 0,
             "skipped": 0, "writeback": 0}
    try:
        for p in products:
            pid = p.get("id")
            bot_id = p.get("botId")
            status = p.get("status") or "draft"
            published = status == "published"
            cat = p.get("category") or {}
            cat_name = cat.get("name") if isinstance(cat, dict) else None
            cat_emoji = cat.get("emoji") if isinstance(cat, dict) else None

            if bot_id:
                row = con.execute(
                    "SELECT id, is_active, stock FROM products WHERE id=?",
                    (bot_id,)).fetchone()
                if row is None:
                    # Bot row was deleted manually: re-insert and keep botId link
                    bot_id = None  # fall through to insert path
                else:
                    new_active = 1 if published else 0
                    cat_id = ensure_bot_category(con, cat_name, cat_emoji,
                                                 args.dry_run)
                    if not args.dry_run:
                        con.execute(
                            "UPDATE products SET name=?, description=?,"
                            " price_cents=?, old_price_cents=?, kind=?,"
                            " stock=?, category_id=COALESCE(?, category_id),"
                            " rating_sum=COALESCE(?, rating_sum),"
                            " rating_count=COALESCE(?, rating_count),"
                            " is_active=? WHERE id=?",
                            (p.get("name"), p.get("description") or "",
                             p.get("priceCents"), p.get("oldPriceCents"),
                             p.get("kind") or "physical",
                             p.get("stock") if p.get("stock") is not None else -1,
                             cat_id if cat_id != -1 else None,
                             p.get("ratingSum"), p.get("ratingCount"),
                             new_active, bot_id))
                    # Restock detection: was 0, now >0 → queue stock alert notifications
                    old_stock = row["stock"] if "stock" in row.keys() else 0
                    new_stock = p.get("stock") if p.get("stock") is not None else -1
                    if old_stock == 0 and new_stock != 0 and new_stock != -1:
                        alert_users = con.execute(
                            "SELECT user_id FROM stock_alerts WHERE product_id=?",
                            (bot_id,)).fetchall()
                        if alert_users:
                            print(f"  🔔 RESTOCK: product {bot_id} ({p.get('name')}) — "
                                  f"{len(alert_users)} user(s) waiting for stock alert")
                            # The bot picks these up via the stock_alerts table;
                            # run tools/notify_restock.py to send the DMs.
                    if row["is_active"] != new_active:
                        stats["deactivated" if not published else "updated"] += 1
                    else:
                        stats["updated"] += 1
                    continue

            # --- no botId (or orphaned): insert new bot row ---
            if not published:
                stats["skipped"] += 1  # draft never synced: nothing to do
                continue
            cat_id = ensure_bot_category(con, cat_name, cat_emoji, args.dry_run)
            if args.dry_run:
                stats["inserted"] += 1
                continue
            cur = con.execute(
                "INSERT INTO products(category_id, name, description,"
                " price_cents, old_price_cents, kind, stock,"
                " rating_sum, rating_count, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (cat_id if cat_id != -1 else None,
                 p.get("name"), p.get("description") or "",
                 p.get("priceCents"), p.get("oldPriceCents"),
                 p.get("kind") or "physical",
                 p.get("stock") if p.get("stock") is not None else -1,
                 p.get("ratingSum") or 0, p.get("ratingCount") or 0))
            new_bot_id = cur.lastrowid
            try:
                api_patch(base, key, f"/api/products/{pid}",
                          {"botId": new_bot_id})
                stats["writeback"] += 1
            except Exception as e:  # noqa: BLE001
                con.rollback()
                print(f"write-back failed for Payload product {pid}: {e}",
                      file=sys.stderr)
                return 1
            stats["inserted"] += 1

        if not args.dry_run:
            con.commit()
    finally:
        con.close()

    mode = "DRY-RUN " if args.dry_run else ""
    print(f"{mode}sync complete: {stats['updated']} updated, "
          f"{stats['inserted']} inserted, {stats['deactivated']} deactivated, "
          f"{stats['skipped']} skipped, {stats['writeback']} write-backs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
