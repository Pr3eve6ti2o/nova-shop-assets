"""Pricing parity: the JavaScript pricing engine (pricing-engine/,
Dinero.js + Decimal.js) and this bot must price every shared vector
identically, cent for cent.

The vectors live in pricing-engine/test-vectors.json and are executed
against the JS engine by pricing-engine/test/vectors.test.js. Here they
run against the bot's REAL totals() (handlers/common.py) backed by a
temp database — promo validation included — so a silent drift in either
implementation fails the suite.

Run: BOT_TOKEN=<dummy> python -m unittest tests.test_pricing_parity
"""
import asyncio
import json
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

import config  # noqa: E402
from database import Database  # noqa: E402
from loader import dp  # noqa: E402
from filters import IsAdmin  # noqa: E402

dp.filters_factory.bind(IsAdmin)  # as app.py does; handlers use is_admin=
import handlers.common as common  # noqa: E402

VECTORS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "pricing-engine", "test-vectors.json")


class _State:
    """Minimal FSMContext stand-in: totals() only reads promo/delivery."""

    def __init__(self, data):
        self._data = data

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)


async def _run_vector(vec):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    await db.create_tables()
    try:
        cat_ids = {}
        for cid in sorted({i["categoryId"] for i in vec["items"]} |
                          ({vec["promo"]["categoryId"]}
                           if vec.get("promo") and
                           vec["promo"].get("categoryId") else set())):
            cat_ids[cid] = await db.add_category(f"Cat{cid}")
        user = await db.create_user(424242, "Parity Tester")
        uid = user["id"]
        for line in vec["items"]:
            pid = await db.add_product(
                category_id=cat_ids[line["categoryId"]],
                name=f"P{line['priceCents']}",
                price_cents=line["priceCents"], stock=-1)
            await db.cart_add(uid, pid, line["qty"])
        state_data = {"delivery_kind": "delivery"}
        promo = vec.get("promo")
        if promo:
            async with db._db() as c:
                await c.execute(
                    "INSERT INTO promos(code, kind, value, category_id,"
                    " bound_user_id) VALUES (?, ?, ?, ?, ?)",
                    ("PARITY", promo["kind"], promo["value"],
                     cat_ids.get(promo.get("categoryId")), None))
                await c.commit()
            state_data["promo_code"] = "PARITY"

        old_db, old_fee = common.db, config.DELIVERY_FEE_CENTS
        common.db = db
        config.DELIVERY_FEE_CENTS = vec["deliveryFeeCents"]
        try:
            t = await common.totals(uid, _State(state_data),
                                    with_delivery=True)
        finally:
            common.db = old_db
            config.DELIVERY_FEE_CENTS = old_fee
        return t
    finally:
        os.unlink(path)


class PricingParity(unittest.TestCase):
    def run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_vectors_match_bot_totals(self):
        with open(VECTORS_PATH, encoding="utf-8") as f:
            vectors = json.load(f)["vectors"]
        self.assertGreaterEqual(len(vectors), 10)
        for vec in vectors:
            with self.subTest(vector=vec["name"]):
                t = self.run_async(_run_vector(vec))
                exp = vec["expected"]
                self.assertEqual(t["subtotal"], exp["subtotal"])
                self.assertEqual(t["discount"], exp["discount"])
                self.assertEqual(t["delivery_fee"], exp["deliveryFee"])
                self.assertEqual(t["total"], exp["total"])


if __name__ == "__main__":
    unittest.main()
