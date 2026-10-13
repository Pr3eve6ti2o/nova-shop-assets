#!/usr/bin/env python3
"""Smoke checks (port plan 7.4).

Two halves, mirroring the reference repo's tooling:
- OFFLINE (always runs) — the plan's scripted checks on a throwaway
  database: migrations apply, catalogue loads, a cart totals/checkout
  computation renders, admin stats queries open, a return round-trips.
- ONLINE (only with --online and a real BOT_TOKEN) — a line-for-line
  port of JumpCodeFrog's `cmd/telegram-smoke`: getMe, webhook state
  vs the configured URL, pending updates, last delivery error.

Exit code 1 on any [FAIL]. Usage: python3 tools/smoke.py [--online]
"""
import asyncio
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))
os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

lines = []
failed = False


def add(status, label, detail=""):
    global failed
    if status == "FAIL":
        failed = True
    line = f"[{status}] {label}"
    if detail:
        line += f": {detail}"
    lines.append(line)


async def offline_checks():
    from database import Database
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    try:
        await db.create_tables()
        add("OK", "Migrations", "schema created on a fresh database")

        cat = await db.add_category("Smoke")
        pid = await db.add_product(category_id=cat, name="Smoke Widget",
                                   price_cents=2500, stock=10)
        products = await db.list_all_products_in_category(cat, 10, 0)
        if products and products[0]["name"] == "Smoke Widget":
            add("OK", "Catalogue loads", "seeded product listed")
        else:
            add("FAIL", "Catalogue loads", "seeded product missing")

        user = await db.create_user(31337, "Smoke Tester")
        uid = user["id"]
        await db.cart_add(uid, pid, 2)
        items = await db.cart_items(uid)
        subtotal = sum(i["price_cents"] * i["qty"] for i in items)
        if subtotal == 5000:
            add("OK", "Checkout renders", "cart totals compute to $50.00")
        else:
            add("FAIL", "Checkout renders", f"subtotal was {subtotal}")

        oid = await db.create_order(
            user_id=uid, subtotal_cents=5000, discount_cents=0,
            total_cents=5000, payment_method="balance",
            delivery_kind="digital", address=None, phone=None)
        await db.set_order_status(oid, "delivered")
        rev, _n = await db.revenue(days=7)
        if rev == 5000 and (await db.revenue_by_day(7)):
            add("OK", "Admin opens", "stats + daily revenue queries run")
        else:
            add("FAIL", "Admin opens", "revenue queries disagree")

        rid = await db.create_return(oid, uid, "smoke test return")
        await db.decide_return(rid, 1, "approved", refund_target="balance")
        if (await db.get_balance(uid)) == 5000:
            add("OK", "Return round-trips", "refund landed on the balance")
        else:
            add("FAIL", "Return round-trips", "balance after refund wrong")
    except Exception as e:
        add("FAIL", "Offline smoke", f"{type(e).__name__}: {e}")
    finally:
        os.unlink(path)


def online_checks():
    """Port of cmd/telegram-smoke/main.go's buildSmokeReport."""
    token = ""
    env_path = os.path.join(os.path.dirname(__file__), "..", "bot", ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
    token = os.environ.get("BOT_TOKEN_REAL", token)
    host = ""
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("WEBHOOK_HOST="):
                host = line.split("=", 1)[1].strip()
    if not token or token.startswith("123456789"):
        add("WARN", "Telegram smoke", "skipped — no real BOT_TOKEN found")
        return

    def call(method):
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)["result"]

    try:
        me = call("getMe")
        info = call("getWebhookInfo")
    except Exception:
        add("FAIL", "Telegram getMe", "could not reach the Telegram API")
        return
    label = "@" + me["username"] if me.get("username") else me.get(
        "first_name", "?")
    add("OK", "Telegram getMe", f"{label} (id={me['id']})")
    url = info.get("url") or ""
    if not url:
        add("OK", "Telegram webhook", "not set; polling mode")
    else:
        add("OK", "Telegram webhook", url)
    expected = host.rstrip("/") if host else ""
    if not expected and url:
        add("WARN", "WEBHOOK_URL env mismatch",
            "env is empty but Telegram still has a webhook configured")
    elif expected and not url:
        add("WARN", "WEBHOOK_URL env mismatch",
            "env suggests webhook mode, but Telegram has none configured")
    elif expected and url != expected and not url.startswith(expected):
        add("WARN", "WEBHOOK_URL env mismatch",
            f"expected {expected}…, got {url}")
    elif expected:
        add("OK", "WEBHOOK_URL env", expected)
    pending = info.get("pending_update_count") or 0
    if pending > 0:
        add("WARN", "Pending updates", f"{pending} update(s) queued")
        if not url:
            add("WARN", "Polling consumer",
                "updates are queued while no webhook is set; the bot "
                "process is likely not polling right now")
    else:
        add("OK", "Pending updates", "0")
    if info.get("last_error_message"):
        detail = info["last_error_message"]
        if info.get("last_error_date"):
            at = datetime.fromtimestamp(
                info["last_error_date"], timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
            detail = f"{detail} (at {at})"
        add("WARN", "Webhook delivery error", detail)


async def main():
    await offline_checks()
    if "--online" in sys.argv:
        online_checks()
    print("Nova Shop Smoke")
    print()
    for line in lines:
        print(line)
    print()
    print("Smoke FAILED." if failed else "Smoke completed successfully.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
