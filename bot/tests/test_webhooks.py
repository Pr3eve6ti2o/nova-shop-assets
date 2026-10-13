"""Outbound webhook tests (port plan 6.4): HMAC signature, delivery
against a local HTTP server, and the unconfigured no-op.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_webhooks.py
"""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

import config  # noqa: E402
import webhooks  # noqa: E402
from database import Database  # noqa: E402


class Webhooks(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_signature_vector(self):
        config.SHOP_WEBHOOK_SECRET = "s3cret"
        body = b'{"event":"order.created","data":{"order_id":1}}'
        expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertEqual(webhooks.sign_body(body), expected)
        config.SHOP_WEBHOOK_SECRET = None

    def test_emit_noop_when_unconfigured(self):
        async def go():
            config.SHOP_WEBHOOK_URL = None
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = Database(path)
            await db.create_tables()
            await webhooks.webhook_emit(db, "order.created",
                                        {"order_id": 1})
            async with db._db() as c:
                async with c.execute(
                        "SELECT COUNT(*) n FROM outbox_events") as cur:
                    self.assertEqual((await cur.fetchone())["n"], 0)
        self.run_async(go())

    def test_delivery_roundtrip_and_signature_header(self):
        async def go():
            from aiohttp import web

            seen = {}

            async def handler(request):
                seen["body"] = await request.read()
                seen["sig"] = request.headers.get("X-Nova-Signature")
                seen["event"] = request.headers.get("X-Nova-Event")
                return web.Response(status=200)

            app = web.Application()
            app.router.add_post("/hook", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 18931)
            await site.start()
            try:
                config.SHOP_WEBHOOK_URL = "http://127.0.0.1:18931/hook"
                config.SHOP_WEBHOOK_SECRET = "s3cret"
                ok = await webhooks.deliver_webhook(
                    {"event": "order.paid", "data": {"order_id": 7}})
                self.assertTrue(ok)
                payload = json.loads(seen["body"])
                self.assertEqual(payload["data"]["order_id"], 7)
                self.assertEqual(seen["event"], "order.paid")
                self.assertEqual(
                    seen["sig"],
                    hmac.new(b"s3cret", seen["body"],
                             hashlib.sha256).hexdigest())
            finally:
                await runner.cleanup()
                config.SHOP_WEBHOOK_URL = None
                config.SHOP_WEBHOOK_SECRET = None
        self.run_async(go())

    def test_delivery_failure_is_false_not_exception(self):
        async def go():
            config.SHOP_WEBHOOK_URL = "http://127.0.0.1:18932/hook"
            ok = await webhooks.deliver_webhook({"event": "x", "data": {}})
            self.assertFalse(ok)
            config.SHOP_WEBHOOK_URL = None
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
