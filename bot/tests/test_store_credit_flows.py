"""Store credit Phase 2 (bot workflows) — keyboard/callback shape gates.

The money logic is covered by test_store_credit.py at the DB layer;
these tests pin the Telegram surface: the admin user card gains
Credit (+ Debit only when there is a balance), Create order and the
Balance screen gains the gift-card redeem entry; the manual-order
picker only offers Comp / Charge once something is picked; callback
strings match what handlers/admin/store_credit.py routes on.

Run: BOT_TOKEN=<dummy> python -m unittest tests.test_store_credit_flows
"""
import os
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from loader import dp  # noqa: E402
from filters import IsAdmin  # noqa: E402

dp.filters_factory.bind(IsAdmin)

import keyboards as kb  # noqa: E402


def _callbacks(markup):
    out = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                out.append(btn.callback_data)
    return out


class StoreCreditKeyboards(unittest.TestCase):
    def test_user_card_money_buttons(self):
        broke = {"tg_id": 555, "is_blocked": 0, "balance_cents": 0}
        cbs = _callbacks(kb.admin_user_kb(broke))
        self.assertIn("ad:ucr:555", cbs)
        self.assertNotIn("ad:udb:555", cbs)  # Medusa: debit off at zero
        self.assertNotIn("ad:uzero:555", cbs)  # nothing to zero either
        self.assertIn("ad:uord:555", cbs)
        funded = {"tg_id": 555, "is_blocked": 0, "balance_cents": 1200}
        cbs = _callbacks(kb.admin_user_kb(funded))
        self.assertIn("ad:udb:555", cbs)
        self.assertIn("ad:uzero:555", cbs)

    def test_balance_kb_has_giftcard_redeem(self):
        self.assertIn("bal:gift", _callbacks(kb.balance_kb()))
        self.assertIn("bal:topup", _callbacks(kb.balance_kb()))

    def test_manual_picker_flow_shape(self):
        products = [{"id": 7, "name": "Widget", "price_cents": 2500}]
        empty = _callbacks(kb.admin_manual_pick_kb(products, {}))
        self.assertIn("ad:mo:add:7", empty)
        self.assertNotIn("ad:mo:comp", empty)  # nothing picked yet
        picked = _callbacks(kb.admin_manual_pick_kb(products, {"7": 2}))
        self.assertIn("ad:mo:comp", picked)
        self.assertIn("ad:mo:bal", picked)
        self.assertIn("ad:mo:clear", picked)

    def test_pick_text_totals(self):
        from handlers.admin.store_credit import _pick_text
        user = {"name": "Pat", "balance_cents": 900}
        products = [{"id": 7, "name": "Widget", "price_cents": 2500},
                    {"id": 8, "name": "Gadget", "price_cents": 1000}]
        text = _pick_text(user, products, {"7": 2, "8": 1})
        self.assertIn("Total: $60.00", text)
        self.assertIn("Widget ×2", text)

    def test_giftcard_keyboards(self):
        cards = [{"id": 3, "code": "NOVA-AAAA-BBBB-CCCC",
                  "remaining_cents": 500, "status": "active"}]
        self.assertIn("ad:gc:3", _callbacks(kb.admin_giftcards_kb(cards)))
        active = {"id": 3, "status": "active"}
        self.assertIn("ad:gcrv:3", _callbacks(kb.admin_giftcard_kb(active)))
        spent = {"id": 3, "status": "redeemed"}
        self.assertNotIn("ad:gcrv:3", _callbacks(kb.admin_giftcard_kb(spent)))


if __name__ == "__main__":
    unittest.main()
