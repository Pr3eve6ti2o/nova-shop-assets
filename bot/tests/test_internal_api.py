"""Store credit Phase 3 — internal API contract gates.

Auth (401 without the key), idempotency (a replayed key returns the
stored response and never moves money twice), credit/debit through
the real DB layer, gift cards, manual orders, refund-to-credit with
the fail-closed ceiling.

Run: BOT_TOKEN=<dummy> python -m unittest tests.test_internal_api
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from database import Database  # noqa: E402
from internal_api import create_app  # noqa: E402

SECRET = "s" * 40
H = {"X-Nova-Internal-Key": SECRET}


def idem(key):
    return {**H, "Idempotency-Key": key}


class InternalApi(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_contract(self):
        async def go():
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = Database(path)
            await db.create_tables()
            cat = await db.add_category("Gear")
            p1 = await db.add_product(category_id=cat, name="Widget",
                                      price_cents=2500, stock=-1)
            user = await db.create_user(777, "Api Tester")
            uid = user["id"]
            client = TestClient(TestServer(create_app(db, SECRET)))
            await client.start_server()
            try:
                # Auth: no key and wrong key are both refused.
                r = await client.get("/internal/customers/777")
                self.assertEqual(r.status, 401)
                r = await client.get(
                    "/internal/customers/777",
                    headers={"X-Nova-Internal-Key": "wrong"})
                self.assertEqual(r.status, 401)
                # Unknown customer.
                r = await client.get("/internal/customers/424242",
                                     headers=H)
                self.assertEqual(r.status, 404)
                # Credit requires an idempotency key.
                r = await client.post("/internal/customers/777/credit",
                                      headers=H, json={
                                          "amount_cents": 5000,
                                          "note": "goodwill"})
                self.assertEqual(r.status, 400)
                # Credit applies exactly once across a replay.
                r = await client.post("/internal/customers/777/credit",
                                      headers=idem("k-credit-1"), json={
                                          "amount_cents": 5000,
                                          "note": "goodwill",
                                          "actor": "admin@panel"})
                self.assertEqual(r.status, 200)
                body = await r.json()
                self.assertEqual(body["balance_cents"], 5000)
                r = await client.post("/internal/customers/777/credit",
                                      headers=idem("k-credit-1"), json={
                                          "amount_cents": 5000,
                                          "note": "goodwill"})
                self.assertEqual(r.status, 200)
                self.assertEqual(await db.get_balance(uid), 5000)
                # Note is mandatory; overdraft debit conflicts.
                r = await client.post("/internal/customers/777/debit",
                                      headers=idem("k-debit-0"),
                                      json={"amount_cents": 100})
                self.assertEqual(r.status, 400)
                r = await client.post("/internal/customers/777/debit",
                                      headers=idem("k-debit-1"), json={
                                          "amount_cents": 7000,
                                          "note": "too much"})
                self.assertEqual(r.status, 409)
                r = await client.post("/internal/customers/777/debit",
                                      headers=idem("k-debit-2"), json={
                                          "amount_cents": 2000,
                                          "note": "correction"})
                self.assertEqual(r.status, 200)
                self.assertEqual(await db.get_balance(uid), 3000)
                # Ledger read shows provenance.
                r = await client.get(
                    "/internal/customers/777/transactions", headers=H)
                txs = (await r.json())["transactions"]
                self.assertEqual(len(txs), 2)
                self.assertEqual(txs[0]["actor_type"], "payload")
                # Gift card create + revoke; second revoke conflicts.
                r = await client.post("/internal/gift-cards",
                                      headers=idem("k-gc-1"), json={
                                          "value_cents": 1500,
                                          "note": "prize"})
                self.assertEqual(r.status, 201)
                card = await r.json()
                self.assertTrue(card["code"].startswith("NOVA-"))
                url = f"/internal/gift-cards/{card['id']}/revoke"
                r = await client.post(url, headers=idem("k-gc-r1"),
                                      json={})
                self.assertEqual(r.status, 200)
                r = await client.post(url, headers=idem("k-gc-r2"),
                                      json={})
                self.assertEqual(r.status, 409)
                # Manual comp order (no money moves), then a charged one.
                r = await client.post("/internal/orders/manual",
                                      headers=idem("k-mo-1"), json={
                                          "tg_id": 777, "kind": "comp",
                                          "items": [{"product_id": p1,
                                                     "qty": 1}]})
                self.assertEqual(r.status, 201)
                self.assertEqual(await db.get_balance(uid), 3000)
                r = await client.post("/internal/orders/manual",
                                      headers=idem("k-mo-2"), json={
                                          "tg_id": 777, "kind": "balance",
                                          "items": [{"product_id": p1,
                                                     "qty": 1}]})
                self.assertEqual(r.status, 201)
                charged_oid = (await r.json())["order_id"]
                self.assertEqual(await db.get_balance(uid), 500)
                # Refund-to-credit: partial keeps status, full flips it.
                url = f"/internal/orders/{charged_oid}/refund-to-credit"
                r = await client.post(url, headers=idem("k-rf-1"),
                                      json={"amount_cents": 1000,
                                            "note": "damaged"})
                self.assertEqual(r.status, 200)
                self.assertEqual((await r.json())["status"], "confirmed")
                self.assertEqual(await db.get_balance(uid), 1500)
                r = await client.post(url, headers=idem("k-rf-2"),
                                      json={"note": "the rest"})
                self.assertEqual(r.status, 200)
                self.assertEqual((await r.json())["status"], "refunded")
                self.assertEqual(await db.get_balance(uid), 3000)
                r = await client.post(url, headers=idem("k-rf-3"),
                                      json={"note": "again"})
                self.assertEqual(r.status, 409)  # fail-closed ceiling
                # Order read-back.
                r = await client.get(f"/internal/orders/{charged_oid}",
                                     headers=H)
                self.assertEqual(r.status, 200)
                self.assertEqual(len((await r.json())["items"]), 1)
                # Sync lists for the Payload mirror.
                r = await client.get("/internal/customers", headers=H)
                custs = (await r.json())["customers"]
                self.assertEqual(len(custs), 1)
                self.assertEqual(custs[0]["tg_id"], 777)
                r = await client.get("/internal/gift-cards", headers=H)
                self.assertEqual(len((await r.json())["gift_cards"]), 1)
                # Buyer edit: comp order is 'confirmed' (eligible);
                # the refunded one is not.
                comp = await db.create_manual_order(
                    uid, [(p1, 1)], kind="comp", actor_tg_id=1)
                r = await client.post(
                    f"/internal/orders/{comp[0]}/buyer", headers=H,
                    json={"phone": "+1 555 0100", "address": "1 Main St"})
                self.assertEqual(r.status, 200)
                o = await db.get_order(comp[0])
                self.assertEqual(o["phone"], "+1 555 0100")
                r = await client.post(
                    f"/internal/orders/{charged_oid}/buyer", headers=H,
                    json={"phone": "x"})
                self.assertEqual(r.status, 409)
            finally:
                await client.close()
                os.unlink(path)
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
