#!/usr/bin/env python3
"""Usability smoke (port plan 7.4) — PORTED from
JumpCodeFrog/telegram-shop-bot `cmd/usability-smoke/main.go`.

The original wires the real bot to a FAKE Telegram Bot API that
records every outgoing call, seeds a small catalogue, then walks a
scripted user journey — /start → catalogue → product → add → cart →
checkout → confirm → payment — printing each message the bot sends
with its buttons, so a human can eyeball the actual UX. No
assertions; the printout IS the check.

Adaptations (minor, host-fit): Go/httptest → a stdlib HTTP server in
a thread; aiogram's bot is re-pointed at it via bot.server (read per
request); the journey uses our callback data (shop/cat:/p:/a:/cart/
cq:/co/cop:/cok) and ends with a real balance payment + order
history instead of a Stars invoice (no provider token in test
config). Seed fixtures keep the source's shape (2 categories,
2 products at $12.99 / $9.99), in English.

Usage: python3 tools/usability_smoke.py
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Environment BEFORE importing the bot: temp DB, dummy token, the
# journey user is also the admin so admin notifications get recorded.
_TMP = tempfile.mkdtemp(prefix="nova_usability_")
os.environ.setdefault("BOT_TOKEN",
                      "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "shop.db")
os.environ["ADMINS"] = "30001"
# loader.py wires the bot to the env proxy; an egress proxy refuses
# localhost destinations, so the fake API would be unreachable.
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(_v, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

CHAT_ID = 20001
USER_ID = 30001

# ------------------------------------------------------------------
# Fake Telegram API (the recorder)
# ------------------------------------------------------------------

CALLS = []
_LOCK = threading.Lock()
_next_mid = [100]


def _record(method, params):
    with _LOCK:
        CALLS.append({"method": method, "params": params})


def _count():
    with _LOCK:
        return len(CALLS)


def _snapshot(frm):
    with _LOCK:
        return list(CALLS[frm:])


def _next_id(existing=None):
    with _LOCK:
        if existing:
            try:
                return int(existing)
            except (TypeError, ValueError):
                pass
        _next_mid[0] += 1
        return _next_mid[0]


class FakeTelegram(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # aiohttp reuses connections

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        method = self.path.rstrip("/").split("/")[-1]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type") or ""
        params = {}
        if "application/json" in ctype and body:
            try:
                params = json.loads(body)
            except ValueError:
                params = {}
        elif body:
            # aiogram 2.x posts form-encoded data; reply_markup
            # arrives as a JSON string inside it.
            from urllib.parse import parse_qs
            parsed = parse_qs(body.decode("utf-8", "replace"))
            params = {k: v[0] if len(v) == 1 else v
                      for k, v in parsed.items()}
            if isinstance(params.get("reply_markup"), str):
                try:
                    params["reply_markup"] = json.loads(
                        params["reply_markup"])
                except ValueError:
                    pass
        _record(method, params)
        result = self._result(method, params)
        payload = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _result(method, params):
        if method == "getMe":
            return {"id": 999001, "is_bot": True,
                    "first_name": "UX Smoke Bot",
                    "username": "ux_smoke_bot"}
        if method in ("answerCallbackQuery", "deleteMessage",
                      "editMessageReplyMarkup"):
            return True
        # Everything message-shaped gets a plausible Message back.
        mid = _next_id(params.get("message_id"))
        chat_id = params.get("chat_id") or CHAT_ID
        msg = {"message_id": mid, "date": int(time.time()),
               "chat": {"id": chat_id, "type": "private"}}
        if params.get("text"):
            msg["text"] = params["text"]
        if params.get("caption"):
            msg["caption"] = params["caption"]
        return msg


# ------------------------------------------------------------------
# Printout (ported from the source's printCalls/printKeyboard)
# ------------------------------------------------------------------

def _print_keyboard(markup):
    if not markup:
        return
    if isinstance(markup, str):
        try:
            markup = json.loads(markup)
        except ValueError:
            print(f"reply_markup(raw): {markup}")
            return
    rows = markup.get("inline_keyboard") or []
    if not rows:
        return
    print("buttons:")
    for row in rows:
        labels = [b.get("text", "?") for b in row]
        print("  [" + "] [".join(labels) + "]")


def print_calls(title, calls):
    print(f"\n=== {title} ===")
    if not calls:
        print("No outgoing actions.")
        return
    for call in calls:
        method, params = call["method"], call["params"]
        print(f"method: {method}")
        if method in ("sendMessage", "editMessageText"):
            print("text:")
            print(params.get("text") or params.get("caption") or "")
            _print_keyboard(params.get("reply_markup"))
        elif method in ("sendPhoto", "editMessageCaption"):
            print("caption:")
            print(params.get("caption") or "")
            _print_keyboard(params.get("reply_markup"))
        elif method == "answerCallbackQuery":
            print(f"callback feedback: {params.get('text')!r}")
            if params.get("show_alert"):
                print(f"show_alert: {params['show_alert']}")
        elif method == "sendInvoice":
            print(f"invoice title: {params.get('title')}")
            print(f"invoice description: {params.get('description')}")
            print(f"invoice payload: {params.get('payload')}")
            print(f"invoice prices: {params.get('prices')}")
        else:
            print(f"params: {params}")
        print()


# ------------------------------------------------------------------
# Journey
# ------------------------------------------------------------------

def _user():
    return {"id": USER_ID, "is_bot": False, "first_name": "TestUser",
            "username": "testuser", "language_code": "en"}


def _chat():
    return {"id": CHAT_ID, "type": "private"}


def command_update(uid, text):
    return {"update_id": uid,
            "message": {"message_id": uid, "date": int(time.time()),
                        "chat": _chat(), "from": _user(), "text": text,
                        "entities": [{"offset": 0,
                                      "length": len(text.split()[0]),
                                      "type": "bot_command"}]}}


def callback_update(uid, msg_id, data):
    return {"update_id": uid,
            "callback_query": {
                "id": f"cb-{uid}", "from": _user(), "chat_instance": "ux",
                "message": {"message_id": msg_id, "date": int(time.time()),
                            "chat": _chat(),
                            "from": {"id": 999001, "is_bot": True,
                                     "first_name": "UX Smoke Bot",
                                     "username": "ux_smoke_bot"},
                            "text": "…"},
                "data": data}}


async def seed_data(db):
    """Same fixture shape as the source's seedUsabilityData."""
    clothing = await db.add_category("Clothing", "👕")
    accessories = await db.add_category("Accessories", "🎒")
    await db.add_product(category_id=clothing, name="Basic T-Shirt",
                         description="100% cotton, sizes S-XXL",
                         price_cents=1299, stock=50)
    await db.add_product(category_id=accessories,
                         name="Embroidered Cap",
                         description="One size, adjustable strap",
                         price_cents=999, stock=25)
    return clothing


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    from aiogram import types
    from aiogram.bot.api import TelegramAPIServer
    from aiogram import Bot as _Bot, Dispatcher as _Dp
    from loader import bot, db, dp
    from filters import IsAdmin
    _Bot.set_current(bot)
    _Dp.set_current(dp)
    dp.filters_factory.bind(IsAdmin)
    bot.server = TelegramAPIServer.from_base(base)  # the re-point
    import handlers  # noqa: F401  (registers everything on dp)

    await db.create_tables()
    cat_id = await seed_data(db)

    print("Nova Shop usability smoke")
    print("Scenario: /start -> catalogue -> category -> product -> add "
          "-> cart -> +1 -> checkout -> balance -> confirm -> orders")

    async def step(title, raw_update):
        before = _count()
        # One task per update, like the real polling loop: aiogram's
        # StateFilter caches FSM state in a ContextVar, and running
        # every update in this task would freeze that cache at the
        # first check — state-gated handlers would never match.
        await asyncio.create_task(
            dp.process_update(types.Update(**raw_update)))
        await asyncio.sleep(0.6)  # the source's settle delay
        calls = _snapshot(before)
        print_calls(title, calls)
        return calls

    def last_mid(calls):
        for c in reversed(calls):
            p = c["params"]
            if c["method"].startswith(("send", "edit")):
                return _next_id(p.get("message_id")) \
                    if p.get("message_id") else _next_mid[0]
        return 100

    start_calls = await step("/start", command_update(1, "/start"))
    mid = last_mid(start_calls)

    # Fund the journey user so the balance checkout can complete.
    user = await db.get_user_by_tg(USER_ID)
    await db.add_balance(user["id"], 10000, "smoke funding")

    await step("Catalogue from the main menu",
               callback_update(2, mid, "shop"))
    await step("Category product list",
               callback_update(3, mid, f"cat:{cat_id}:0"))
    prod_calls = await step("Product card",
                            callback_update(4, mid, "p:1"))
    mid = last_mid(prod_calls) or mid
    await step("Add to cart from the card",
               callback_update(5, mid, "a:1"))
    cart_calls = await step("Cart", callback_update(6, mid, "cart"))
    mid = last_mid(cart_calls) or mid
    await step("Quantity +1 in the cart",
               callback_update(7, mid, "cq:1:+1"))
    await step("Checkout", callback_update(8, mid, "co"))
    await step("Choose balance", callback_update(9, mid, "cop:balance"))
    await step("Confirm / place order", callback_update(10, mid, "cok"))
    await step("Order history", callback_update(11, mid, "orders"))

    server.shutdown()
    print("\nDone: scenario ran locally against the fake Telegram API "
          "with no real client.")


if __name__ == "__main__":
    asyncio.run(main())
