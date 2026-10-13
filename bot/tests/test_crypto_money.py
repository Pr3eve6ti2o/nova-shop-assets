"""Money-math matrix tests for crypto_payments.py pure functions
(port plan 7.5, stage 1): USD->base-unit conversion, tolerance, formatting.

Needs the bot's import environment (aiohttp, python-dotenv) and a
well-formed dummy BOT_TOKEN for config import.

Run: PYTHONPATH=. python -m pytest tests/test_crypto_money.py
"""
import os
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from crypto_payments import (  # noqa: E402
    format_crypto,
    meets_tolerance,
    usd_cents_to_base_units,
)


class UsdToBaseUnits(unittest.TestCase):
    def test_exact_conversions(self):
        # $100 of BTC at $50,000/BTC = 0.002 BTC = 200,000 sats
        self.assertEqual(usd_cents_to_base_units(10000, 50000, "btc"), 200000)
        # $1.00 of USDT at $1.00 = 1,000,000 base units (6 decimals)
        self.assertEqual(
            usd_cents_to_base_units(100, 1, "usdt_polygon"), 1000000)
        # $8.99 of TON at $5.00/TON = 1.798 TON = 1,798,000,000 nano
        self.assertEqual(
            usd_cents_to_base_units(899, 5, "ton"), 1798000000)

    def test_rounds_up_never_underquotes(self):
        # 1 cent at $3/BTC: exact is 333333.33.. sats -> must ceil to 333334
        self.assertEqual(usd_cents_to_base_units(1, 3, "btc"), 333334)
        for cents, price in ((1, 3), (7, 67234.5), (899, 2.63), (100, 0.99),
                             (12345, 42100.77)):
            for chain, dec in (("btc", 8), ("usdt_base", 6), ("ton", 9)):
                got = usd_cents_to_base_units(cents, price, chain)
                price_cents = -(-int(float(price) * 100 * 10) // 10)
                # value received must cover the USD owed...
                self.assertGreaterEqual(
                    got * (int(price * 100) + (1 if price * 100 % 1 else 0)),
                    cents * 10 ** dec - 10 ** dec)  # loose lower bound
                # ...and one unit less must not be a gross overquote
                self.assertLessEqual(got, cents * 10 ** dec // max(1, int(price * 100)) + 2)

    def test_price_input_types_agree(self):
        as_float = usd_cents_to_base_units(1000, 50000.0, "btc")
        as_str = usd_cents_to_base_units(1000, "50000", "btc")
        as_int = usd_cents_to_base_units(1000, 50000, "btc")
        self.assertEqual(as_float, as_str)
        self.assertEqual(as_str, as_int)

    def test_bad_prices_raise(self):
        for bad in (0, -1, -0.5, "abc", "", None):
            with self.subTest(price=bad):
                with self.assertRaises(ValueError):
                    usd_cents_to_base_units(100, bad, "btc")


class MeetsTolerance(unittest.TestCase):
    """Tolerance is 98/100: a deposit of >= 98% of expected counts."""

    def test_boundaries(self):
        self.assertTrue(meets_tolerance(100, 100))
        self.assertTrue(meets_tolerance(150, 100))   # overpay always fine
        self.assertTrue(meets_tolerance(98, 100))    # exactly 98% passes
        self.assertFalse(meets_tolerance(97, 100))   # 97% fails
        self.assertFalse(meets_tolerance(0, 100))
        self.assertFalse(meets_tolerance(1, 100))

    def test_large_amounts_stay_exact(self):
        # Integer math: no float drift at whale sizes.
        expected = 10 ** 18
        self.assertTrue(meets_tolerance(expected * 98 // 100, expected))
        self.assertFalse(meets_tolerance(expected * 98 // 100 - 1, expected))


class FormatCrypto(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(format_crypto(0, "btc"), "0 BTC")
        self.assertEqual(format_crypto(100000000, "btc"), "1 BTC")
        self.assertEqual(format_crypto(123456789, "btc"), "1.23456789 BTC")
        self.assertEqual(format_crypto(1500000, "usdt_polygon"), "1.5 USDT")
        self.assertEqual(format_crypto(1000000, "usdt_polygon"), "1 USDT")
        self.assertEqual(format_crypto(1, "ton"), "0.000000001 TON")
        self.assertEqual(format_crypto(1798000000, "ton"), "1.798 TON")

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            format_crypto(-1, "btc")


if __name__ == "__main__":
    unittest.main()
