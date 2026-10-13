"""Money-math matrix tests for utils.py (port plan 7.5, stage 1).

Run: PYTHONPATH=. python -m pytest tests/test_money_matrix.py
     or PYTHONPATH=. python tests/test_money_matrix.py
"""
import unittest

from utils import fmt_money, paginate, stars_for_cents


class FmtMoneyMatrix(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            (0, "$0.00"), (1, "$0.01"), (9, "$0.09"), (10, "$0.10"),
            (99, "$0.99"), (100, "$1.00"), (101, "$1.01"), (110, "$1.10"),
            (999, "$9.99"), (1299, "$12.99"), (100000, "$1000.00"),
            (100000000, "$1000000.00"),
        ]
        for cents, expected in cases:
            with self.subTest(cents=cents):
                self.assertEqual(fmt_money(cents, "USD"), expected)

    def test_negatives(self):
        self.assertEqual(fmt_money(-1, "USD"), "-$0.01")
        self.assertEqual(fmt_money(-100, "USD"), "-$1.00")
        self.assertEqual(fmt_money(-1299, "USD"), "-$12.99")

    def test_currency_symbols(self):
        self.assertEqual(fmt_money(1299, "EUR"), "€12.99")
        self.assertEqual(fmt_money(1299, "GBP"), "£12.99")
        self.assertEqual(fmt_money(1299, "RUB"), "₽12.99")
        self.assertEqual(fmt_money(1299, "UAH"), "₴12.99")
        self.assertEqual(fmt_money(1299, "KZT"), "₸12.99")
        self.assertEqual(fmt_money(1299, "BYN"), "Br12.99")
        self.assertEqual(fmt_money(1299, "PLN"), "zł12.99")

    def test_unknown_currency_falls_back_to_code(self):
        self.assertEqual(fmt_money(1299, "XYZ"), "12.99 XYZ")

    def test_currency_normalisation(self):
        self.assertEqual(fmt_money(100, "usd"), "$1.00")
        self.assertEqual(fmt_money(100, None), "$1.00")
        self.assertEqual(fmt_money(100), "$1.00")


class StarsForCentsMatrix(unittest.TestCase):
    def test_exact_and_ceiling(self):
        cases = [
            (100, 60, 60), (101, 60, 61), (199, 100, 199), (200, 100, 200),
            (250, 40, 100), (1, 50, 1), (1, 1, 1), (10000, 55, 5500),
            (899, 60, 540),  # the $8.99 rental price at 60 stars/USD
            (8999, 60, 5400),  # the $89.99 rental price
        ]
        for cents, rate, expected in cases:
            with self.subTest(cents=cents, rate=rate):
                self.assertEqual(stars_for_cents(cents, rate), expected)

    def test_never_undercharges_and_is_minimal(self):
        # Display/charge drift guard: the stars charged must always cover
        # the cents owed, and one star less must not cover it.
        for cents in (1, 7, 33, 100, 101, 899, 1000, 12345, 999999):
            for rate in (1, 13, 40, 50, 60, 100):
                stars = stars_for_cents(cents, rate)
                self.assertGreaterEqual(stars * 100, cents * rate)
                self.assertLess((stars - 1) * 100, cents * rate)

    def test_rejects_bad_inputs(self):
        for bad_cents in (0, -1, -100, True, False, 10.5, "100", None):
            with self.subTest(cents=bad_cents):
                with self.assertRaises(ValueError):
                    stars_for_cents(bad_cents, 60)
        for bad_rate in (0, -1, True, 1.5, "60", None):
            with self.subTest(rate=bad_rate):
                with self.assertRaises(ValueError):
                    stars_for_cents(100, bad_rate)

    def test_rejects_non_usd(self):
        with self.assertRaises(ValueError):
            stars_for_cents(100, 60, "EUR")


class PaginateMatrix(unittest.TestCase):
    def test_pages(self):
        self.assertEqual(paginate(0, 0, 10), (0, 1))
        self.assertEqual(paginate(1, 0, 10), (0, 1))
        self.assertEqual(paginate(10, 0, 10), (0, 1))
        self.assertEqual(paginate(11, 0, 10), (0, 2))
        self.assertEqual(paginate(25, 2, 10), (2, 3))
        self.assertEqual(paginate(100, 9, 10), (9, 10))

    def test_clamping(self):
        self.assertEqual(paginate(25, 99, 10), (2, 3))
        self.assertEqual(paginate(25, -1, 10), (0, 3))
        self.assertEqual(paginate(-5, 0, 10), (0, 1))

    def test_bad_per_page(self):
        with self.assertRaises(ValueError):
            paginate(10, 0, 0)


if __name__ == "__main__":
    unittest.main()
