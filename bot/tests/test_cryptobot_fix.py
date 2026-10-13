"""CryptoBot fix tests (2026-10-13, ported from JumpCodeFrog
internal/payment/cryptobot.go + cryptobot_test.go):

- strict provider amount parser: no rounding, no floats, rejects
  signs/whitespace/exponents/precision it would have to round;
- receipt validation: a provider-paid invoice is finalised only when
  its amount, asset and payload match the stored invoice exactly;
- anomaly quarantine: paid-but-invalid invoices are preserved in the
  payreview queue (raw facts kept), alerted exactly once, never
  credited and never dropped;
- top-up recovery: the sweep credits paid top-up invoices (the pre-fix
  sweep sent them down the order path and looped forever);
- provider-history window: bounded paged scan with a continuation
  offset; late payments for expired rows and orphan paid invoices are
  quarantined, never auto-credited.

Run: python -m unittest discover -s tests -p "test_*.py"
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
os.environ.setdefault("CRYPTOBOT_TOKEN", "test-token")

import config  # noqa: E402
import crypto_payments as cp  # noqa: E402
from database import Database  # noqa: E402


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class StrictAmountParser(unittest.TestCase):
    def test_valid_amounts(self):
        cases = {
            "10.31": 1031, "10.3": 1030, "10": 1000, "0.01": 1,
            "2.67": 267, "0.10": 10, "007.50": 750, "1000.00": 100000,
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(cp.parse_strict_provider_amount(raw), want)

    def test_invalid_amounts_rejected(self):
        for raw in ("", None, "0", "0.00", "-1.00", "+1", " 1.00", "1.00 ",
                    "1e3", "1.234", ".5", "5.", "1.2.3", "abc", "1,00",
                    True, "1.005"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    cp.parse_strict_provider_amount(raw)


class ReceiptValidation(unittest.TestCase):
    def _item(self, **kw):
        item = {"invoice_id": 42, "status": "paid", "asset": "USDT",
                "amount": "10.31", "payload": "7", "paid_at": "2026-01-01T00:00:00Z"}
        item.update(kw)
        return item

    def test_valid_receipt_returns_gross_cents(self):
        got = cp.validate_cryptobot_receipt(
            self._item(), expected_amount="10.31", expected_payload="7")
        self.assertEqual(got, 1031)

    def test_mismatches_raise(self):
        for kw in ({"amount": "9.99"}, {"amount": "10.999"},
                   {"amount": "abc"}, {"asset": "TON"},
                   {"payload": "8"}, {"status": "active"}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    cp.validate_cryptobot_receipt(
                        self._item(**kw), expected_amount="10.31",
                        expected_payload="7")


class InvoicesWindow(unittest.TestCase):
    def _patch_provider(self, total_items):
        dataset = [{"invoice_id": i + 1, "status": "paid", "asset": "USDT",
                    "amount": "1.00", "payload": str(i + 1)}
                   for i in range(total_items)]
        orig = cp._cryptobot_call

        async def fake_call(method, params):
            offset = int(params.get("offset", 0))
            count = int(params.get("count", len(dataset)))
            return {"items": dataset[offset:offset + count]}

        cp._cryptobot_call = fake_call
        return orig

    def test_window_complete(self):
        orig = self._patch_provider(250)
        try:
            items, nxt = run_async(cp.cryptobot_get_invoices_window(
                status="paid", start_offset=0))
            self.assertEqual(len(items), 250)
            self.assertIsNone(nxt)
        finally:
            cp._cryptobot_call = orig

    def test_window_bounded_with_continuation(self):
        orig = self._patch_provider(250)
        try:
            items, nxt = run_async(cp.cryptobot_get_invoices_window(
                status="paid", start_offset=0, max_invoices=200))
            self.assertEqual(len(items), 200)
            self.assertEqual(nxt, 200)
            items2, nxt2 = run_async(cp.cryptobot_get_invoices_window(
                status="paid", start_offset=nxt, max_invoices=200))
            self.assertEqual(len(items2), 50)
            self.assertIsNone(nxt2)
        finally:
            cp._cryptobot_call = orig

    def test_window_exact_fit_is_complete(self):
        orig = self._patch_provider(200)
        try:
            items, nxt = run_async(cp.cryptobot_get_invoices_window(
                status="paid", start_offset=0, max_invoices=200))
            self.assertEqual(len(items), 200)
            self.assertIsNone(nxt)
        finally:
            cp._cryptobot_call = orig


class SweepCryptobot(unittest.TestCase):
    """Sweep tests: real temp-file Database, fake provider + finalize."""

    def _run(self, scenario):
        run_async(self._scenario(scenario))

    async def _scenario(self, scenario):
        import crypto_watcher as cw

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = Database(path)
        await db.create_tables()

        self.alerts = []
        self.finalize_calls = []
        self.provider_paid = {}   # invoice_id -> provider item
        self.history_items = []

        orig_db = cw.db
        orig_alert = cw._alert_payment_anomaly
        orig_finalize = cw.finalize_crypto_order
        orig_get = cp.cryptobot_get_invoices
        orig_window = cp.cryptobot_get_invoices_window
        orig_token = config.CRYPTOBOT_TOKEN

        async def fake_alert(aid, invoice_id):
            self.alerts.append((aid, invoice_id))

        async def fake_finalize(order_id, *, provider, external_id,
                                amount_cents, currency):
            self.finalize_calls.append(
                {"order_id": order_id, "amount_cents": amount_cents})
            if getattr(self, "finalize_should_fail", False):
                return False
            await db.set_order_status(order_id, "confirmed")
            return True

        async def fake_get(invoice_ids=None, status=None, offset=None,
                           count=None):
            return [self.provider_paid[int(i)] for i in (invoice_ids or [])
                    if int(i) in self.provider_paid]

        async def fake_window(status="paid", start_offset=0, **kw):
            return list(self.history_items), None

        cw.db = db
        cw._alert_payment_anomaly = fake_alert
        cw.finalize_crypto_order = fake_finalize
        cp.cryptobot_get_invoices = fake_get
        cp.cryptobot_get_invoices_window = fake_window
        config.CRYPTOBOT_TOKEN = "test-token"
        cw._CB_HISTORY_OFFSET = 0
        try:
            await scenario(self, db, cw)
        finally:
            cw.db = orig_db
            cw._alert_payment_anomaly = orig_alert
            cw.finalize_crypto_order = orig_finalize
            cp.cryptobot_get_invoices = orig_get
            cp.cryptobot_get_invoices_window = orig_window
            config.CRYPTOBOT_TOKEN = orig_token

    async def _make_order_invoice(self, db, *, total=1000, gross="10.31",
                                  fee_pct=3):
        cat = await db.add_category("Test")
        await db.add_product(category_id=cat, name="Key",
                             price_cents=total, kind="digital",
                             is_unlimited=True)
        user = await db.create_user(818181, "Payer")
        oid = await db.create_order(
            user_id=user["id"], subtotal_cents=total, discount_cents=0,
            total_cents=total, payment_method="cryptobot",
            delivery_kind="pickup", address=None, phone=None)
        await db.create_cryptobot_invoice(
            order_id=oid, invoice_id=555001, asset="USDT", amount=gross,
            fee_pct=fee_pct)
        return user, oid

    def _paid_item(self, invoice_id, *, amount="10.31", payload="1",
                   asset="USDT"):
        return {"invoice_id": invoice_id, "status": "paid", "asset": asset,
                "amount": amount, "payload": payload,
                "paid_at": "2026-10-13T00:00:00Z"}

    def test_sweep_finalizes_valid_order_invoice(self):
        async def scenario(s, db, cw):
            _user, oid = await s._make_order_invoice(db)
            s.provider_paid[555001] = s._paid_item(555001, payload=str(oid))
            await cw._sweep_cryptobot()
            inv = await db.get_cryptobot_invoice(555001)
            s.assertEqual(inv["status"], "paid")
            s.assertEqual(len(s.finalize_calls), 1)
            s.assertEqual(s.finalize_calls[0]["amount_cents"], 1000)
        self._run(scenario)

    def test_sweep_quarantines_amount_mismatch_once(self):
        async def scenario(s, db, cw):
            _user, oid = await s._make_order_invoice(db)
            s.provider_paid[555001] = s._paid_item(
                555001, amount="9.99", payload=str(oid))
            await cw._sweep_cryptobot()
            inv = await db.get_cryptobot_invoice(555001)
            s.assertEqual(inv["status"], "quarantined")
            s.assertEqual(s.finalize_calls, [])
            rows = await db.anomalies_open()
            s.assertEqual(len(rows), 1)
            s.assertEqual(rows[0]["provider"], "cryptobot")
            s.assertIn("amount mismatch", rows[0]["reason"])
            s.assertIn(f"invoice_payload:{oid}", rows[0]["raw"])
            s.assertEqual(len(s.alerts), 1)
            # Second sweep: still exactly one anomaly, one alert.
            await cw._sweep_cryptobot()
            s.assertEqual(len(await db.anomalies_open()), 1)
            s.assertEqual(len(s.alerts), 1)
        self._run(scenario)

    def test_sweep_recovers_paid_topup(self):
        async def scenario(s, db, cw):
            user = await db.create_user(828282, "Topper")
            await db.create_cryptobot_invoice(
                order_id=None, invoice_id=555002, asset="USDT",
                amount="10.31", purpose="topup",
                topup_user_id=user["id"], fee_pct=3)
            s.provider_paid[555002] = s._paid_item(555002, payload="topup")
            await cw._sweep_cryptobot()
            inv = await db.get_cryptobot_invoice(555002)
            s.assertEqual(inv["status"], "paid")
            bonus = 1000 * config.DEPOSIT_BONUS_PERCENT // 100
            s.assertEqual(await db.get_balance(user["id"]), 1000 + bonus)
            # Idempotent: a second sweep credits nothing more.
            await cw._sweep_cryptobot()
            s.assertEqual(await db.get_balance(user["id"]), 1000 + bonus)
        self._run(scenario)

    def test_sweep_finalize_failure_marks_paid_unfinalized(self):
        async def scenario(s, db, cw):
            s.finalize_should_fail = True
            _user, oid = await s._make_order_invoice(db)
            s.provider_paid[555001] = s._paid_item(555001, payload=str(oid))
            await cw._sweep_cryptobot()
            inv = await db.get_cryptobot_invoice(555001)
            s.assertEqual(inv["status"], "paid_unfinalized")
        self._run(scenario)

    def test_history_quarantines_orphan_paid_invoice(self):
        async def scenario(s, db, cw):
            s.history_items = [s._paid_item(999999, amount="5.00",
                                            payload="12345")]
            await cw._sweep_cryptobot()
            rows = await db.anomalies_open()
            s.assertEqual(len(rows), 1)
            s.assertEqual(rows[0]["external_id"], "999999")
            s.assertEqual(rows[0]["amount_cents"], 500)
            s.assertEqual(len(s.alerts), 1)
        self._run(scenario)

    def test_history_quarantines_late_payment_for_expired_invoice(self):
        async def scenario(s, db, cw):
            _user, oid = await s._make_order_invoice(db)
            await db.set_cryptobot_status(555001, "expired")
            s.history_items = [s._paid_item(555001, payload=str(oid))]
            await cw._sweep_cryptobot()
            inv = await db.get_cryptobot_invoice(555001)
            s.assertEqual(inv["status"], "quarantined")
            s.assertEqual(s.finalize_calls, [])
            rows = await db.anomalies_open()
            s.assertEqual(len(rows), 1)
            s.assertIn("late payment", rows[0]["reason"])
        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
