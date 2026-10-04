#!/usr/bin/env python3
"""Send stock-restocker DM notifications to users waiting for alerts.

Usage: .venv/bin/python tools/notify_restock.py [--dry-run]

Finds products that were restocked (stock went 0 -> >0) with pending
stock_alerts, sends a Telegram DM to each waiting user, and clears the alerts.
"""
import argparse
import asyncio
import os
import sqlite3
import html
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "nova_shop.db")


async def send_dm(bot_token, tg_id, text):
    import aiohttp
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json={
            "chat_id": tg_id, "text": text, "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "🛍️ Open Nova Shop", "web_app": {"url": os.environ.get("MINIAPP_URL", "")}}
            ]]} if os.environ.get("MINIAPP_URL") else None,
        }) as resp:
            return resp.status == 200


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not BOT_TOKEN and not args.dry_run:
        print("BOT_TOKEN not set")
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # Products with pending alerts that are now in stock
    rows = con.execute("""
        SELECT DISTINCT sa.product_id, p.name, p.stock
        FROM stock_alerts sa
        JOIN products p ON p.id = sa.product_id
        WHERE p.stock != 0 AND p.is_active = 1
    """).fetchall()

    if not rows:
        print("No restocked products with pending alerts.")
        return

    for r in rows:
        pid = r["product_id"]
        users = con.execute(
            """SELECT sa.user_id, u.tg_id FROM stock_alerts sa
               JOIN users u ON u.id = sa.user_id
               WHERE sa.product_id = ?""", (pid,)).fetchall()
        print(f"Product {pid} ({r['name']}): {len(users)} alert(s)")
        if args.dry_run:
            continue
        for u in users:
            text = (f"🔔 <b>Back in stock!</b>\n\n{html.escape(r['name'])} is available again. "
                    f"Tap below to grab it before it sells out.")
            ok = await send_dm(BOT_TOKEN, u["tg_id"], text)
            print(f"  {'✓' if ok else '✗'} user {u['user_id']} (tg {u['tg_id']})")
            if ok:
                con.execute("DELETE FROM stock_alerts WHERE user_id=? AND product_id=?",
                            (u["user_id"], pid))
        con.commit()
    con.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
