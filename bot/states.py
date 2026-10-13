"""FSM states for Nova Shop Bot (aiogram 2.x StatesGroups)."""
from aiogram.dispatcher.filters.state import State, StatesGroup


class Checkout(StatesGroup):
    """Sleek 2-screen checkout: payment -> confirm. (Details removed for digital-only.)"""
    payment = State()   # payment method (chains listed directly)
    confirm = State()   # merged review & confirm; promo via reply
    buyer_email = State()  # port 1.3: BUYER_INFO_MODE=email|address prompt
    buyer_name = State()   # port 1.3: BUYER_INFO_MODE=address prompt


class SearchFlow(StatesGroup):
    waiting_query = State()
    results = State()


class ReviewFlow(StatesGroup):
    waiting_text = State()


class SupportFlow(StatesGroup):
    waiting_message = State()
    followup = State()  # port 3.1: adding a message to an open ticket thread


class AdminReplyFlow(StatesGroup):
    waiting_text = State()


class SwapFlow(StatesGroup):
    """Tenant token-swap application: reason -> owner approval -> new token -> challenge."""
    waiting_reason = State()
    waiting_token = State()


class CategoryWizard(StatesGroup):
    name = State()
    rename = State()


class ProductWizard(StatesGroup):
    name = State()
    description = State()
    photo = State()
    price = State()
    kind = State()
    stock = State()
    values = State()
    unlimited = State()
    category = State()
    confirm = State()


class ProductPriceEdit(StatesGroup):
    value = State()


class ProductStockEdit(StatesGroup):
    value = State()


class ProductValuesAdd(StatesGroup):
    values = State()


class PromoWizard(StatesGroup):
    code = State()
    kind = State()
    value = State()
    max_uses = State()
    expiry = State()
    confirm = State()


class BroadcastFlow(StatesGroup):
    content = State()
    confirm = State()


class UserSearch(StatesGroup):
    query = State()


class CartPromo(StatesGroup):
    waiting_code = State()


class BalanceFlow(StatesGroup):
    topup_custom = State()  # waiting for the user to type a custom top-up amount


class ReturnFlow(StatesGroup):
    reason = State()  # waiting for the customer to type the return reason


class AdminReturnFlow(StatesGroup):
    deny_note = State()  # waiting for the admin to type the (required) denial note


class AdminPayreviewFlow(StatesGroup):
    settle_amount = State()  # USD amount to credit for a settled anomaly
    settle_note = State()    # required audit note for the settlement
    dismiss_note = State()   # required audit note for a dismissal


class AdminRefundFlow(StatesGroup):
    order_id = State()  # waiting for the admin to type the order id


class AdminCreditFlow(StatesGroup):
    """Store credit (Medusa borrow): admin credit/debit with a reason."""
    amount = State()   # USD amount typed by the admin
    note = State()     # mandatory ledger note
    confirm = State()  # awaiting the confirm tap


class AdminGiftCardFlow(StatesGroup):
    """Admin gift-card creation: amount -> expiry days -> note."""
    amount = State()
    expiry = State()
    note = State()


class GiftCardFlow(StatesGroup):
    """Customer gift-card redemption from the Balance screen."""
    code = State()


class AdminOrderFlow(StatesGroup):
    """Admin manual (comp / balance-charged) order for a customer."""
    pick = State()     # tapping products to build the order
    confirm = State()  # awaiting the confirm tap
