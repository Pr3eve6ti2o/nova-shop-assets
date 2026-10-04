"""FSM states for Nova Shop Bot (aiogram 2.x StatesGroups)."""
from aiogram.dispatcher.filters.state import State, StatesGroup


class Checkout(StatesGroup):
    """Sleek 2-screen checkout: payment -> confirm. (Details removed for digital-only.)"""
    payment = State()   # payment method (chains listed directly)
    confirm = State()   # merged review & confirm; promo via reply


class SearchFlow(StatesGroup):
    waiting_query = State()
    results = State()


class ReviewFlow(StatesGroup):
    waiting_text = State()


class SupportFlow(StatesGroup):
    waiting_message = State()


class AdminReplyFlow(StatesGroup):
    waiting_text = State()


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
