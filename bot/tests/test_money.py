import unittest

from utils import fmt_money, stars_for_cents


class MoneyTests(unittest.TestCase):
    def test_integer_formatting(self):
        self.assertEqual(fmt_money(1299, "USD"), "$12.99")
        self.assertEqual(fmt_money(0, "USD"), "$0.00")
        self.assertEqual(fmt_money(-1, "USD"), "-$0.01")

    def test_stars_round_up(self):
        self.assertEqual(stars_for_cents(100, 60), 60)
        self.assertEqual(stars_for_cents(101, 60), 61)
