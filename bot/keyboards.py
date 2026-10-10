"""All keyboard builders for Nova Shop Bot (inline-first).

Callback data scheme (ALL < 64 bytes, integer ids only — never names/prices):
  menu | shop | cart | co | cok | cox | cc | ccy | pm | px
  cat:{cid}:{page} | p:{pid} | pa:{pid}:{delta} | pb:{pid} | w:{pid}
  rv:{pid} | rvl:{pid} | rvr:{pid}:{stars}
  cq:{pid}:{delta} | crm:{pid}
  cod:{kind} | cop:{method} | coe:{step}
  ord | o:{oid} | ob:{oid}
  prof | wl | pur | ref | sup | srep:{tgid}
  adm | ad:st
  ad:cat | ac:cadd | ac:cdel:{cid} | ac:cdely:{cid} | ac:cren:{cid}
  ac:padd | ac:plist:{cid}:{page} | ac:p:{pid} | ac:ptog:{pid}
  ac:pdel:{pid} | ac:pdely:{pid} | ac:ppr:{pid} | ac:pst:{pid} | ac:pv:{pid}
  ad:ord:{status}:{page} | ad:o:{oid} | ad:os:{oid}:{status}
  ad:usr | ad:u:{tgid} | ad:ub:{tgid} | ad:ur:{tgid} | ad:urc:{tgid}:{bit}
  ad:pro | ac:pradd | ac:prt:{pid} | ac:prd:{pid} | ac:prdy:{pid}
  ad:bc | bcy | bcx | bcstop
  ad:mnt | mnt:{0|1}
  noop (dead-end buttons)
"""
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    ForceReply, WebAppInfo,
)

import config
import texts
from utils import cb, fmt_money, paginate

BTN_MENU = InlineKeyboardButton(texts.BTN_MENU, callback_data="menu")
BTN_BACK_SHOP = InlineKeyboardButton(texts.BTN_BACK, callback_data="shop")


def main_menu_inline():
    kb = InlineKeyboardMarkup()
    kb.add(BTN_MENU)
    return kb


def reply_main_menu(is_admin: bool = False, show_rental: bool = False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(texts.BTN_PROFILE), KeyboardButton(texts.BTN_SHOP))
    kb.row(KeyboardButton(texts.BTN_INFO), KeyboardButton(texts.BTN_RENT))
    if show_rental:
        # Persistent once the user has ever subscribed (even one time) —
        # a sort of invoice view for their rental subscription.
        kb.row(KeyboardButton(texts.BTN_RENT_MINE))
    if is_admin:
        kb.row(KeyboardButton(texts.BTN_ADMIN))
    return kb


def _nav_footer(kb, back_cb: str, deep: bool = False):
    row = [InlineKeyboardButton(texts.BTN_BACK, callback_data=back_cb)]
    if deep:
        row.append(BTN_MENU)
    kb.row(*row)
    return kb


# ------------------------------------------------------------- shop ---
def categories_kb(cats):
    kb = InlineKeyboardMarkup(row_width=2)
    for c in cats:
        kb.insert(InlineKeyboardButton(f"{c['emoji']} {c['name']}",
                                       callback_data=cb("cat", c["id"], 0)))
    kb.row(BTN_MENU)
    return kb


def catalog_kb(products):
    """Flat product list for /catalog (no categories)."""
    kb = InlineKeyboardMarkup()
    for p in products:
        label = f"{p['name']} — {fmt_money(p['price_cents'], config.CURRENCY)}"
        kb.add(InlineKeyboardButton(label, callback_data=cb("p", p["id"])))
    kb.row(BTN_MENU)
    return kb


def products_kb(items, cat_id: int, page: int, total: int, per_page: int = 6):
    kb = InlineKeyboardMarkup()
    for p in items:
        label = f"{p['name']} \u2014 {fmt_money(p['price_cents'], config.CURRENCY)}"
        kb.add(InlineKeyboardButton(label, callback_data=cb("p", p["id"])))
    page, total_pages = paginate(total, page, per_page)
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(texts.BTN_PREV,
                                            callback_data=cb("cat", cat_id, page - 1)))
        row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}",
                                        callback_data="noop"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(texts.BTN_NEXT,
                                            callback_data=cb("cat", cat_id, page + 1)))
        kb.row(*row)
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="shop"))
    kb.row(BTN_MENU)
    return kb


def search_results_kb(items, query: str, page: int, total: int, per_page: int = 6):
    """Search results keyboard.

    `query` is intentionally not embedded in callback data; pagination
    relies on the caller keeping the search query in FSM state.
    """
    kb = InlineKeyboardMarkup()
    for p in items:
        label = f"{p['name']} \u2014 {fmt_money(p['price_cents'], config.CURRENCY)}"
        kb.add(InlineKeyboardButton(label, callback_data=cb("p", p["id"])))
    page, total_pages = paginate(total, page, per_page)
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(texts.BTN_PREV,
                                            callback_data=cb("sp", page - 1)))
        row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}",
                                        callback_data="noop"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(texts.BTN_NEXT,
                                            callback_data=cb("sp", page + 1)))
        kb.row(*row)
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="shop"))
    kb.row(BTN_MENU)
    return kb


def product_kb(p, qty: int, in_wishlist: bool, rating_avg: float, rating_count: int):
    kb = InlineKeyboardMarkup()
    # stepper row
    kb.row(
        InlineKeyboardButton("\u2796", callback_data=cb("pa", p["id"], "-1")),
        InlineKeyboardButton(str(qty), callback_data="noop"),
        InlineKeyboardButton("\u2795", callback_data=cb("pa", p["id"], "+1")),
    )
    kb.add(InlineKeyboardButton(
        texts.BTN_BUY_NOW.format(price=fmt_money(p["price_cents"] * qty, config.CURRENCY)),
        callback_data=cb("pb", p["id"])))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("cat", p["category_id"], 0)))
    kb.row(BTN_MENU)
    return kb


def reviews_kb(product_id: int, can_review: bool):
    kb = InlineKeyboardMarkup()
    if can_review:
        kb.add(InlineKeyboardButton(texts.BTN_LEAVE_REVIEW,
                                    callback_data=cb("rvl", product_id)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("p", product_id)))
    kb.row(BTN_MENU)
    return kb


def rating_picker_kb(product_id: int):
    kb = InlineKeyboardMarkup(row_width=5)
    for s in range(1, 6):
        kb.insert(InlineKeyboardButton("\u2b50" * s, callback_data=cb("rvr", product_id, s)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("rv", product_id)))
    return kb


# ------------------------------------------------------------- cart ---
def cart_kb(items, promo_code, promo_desc, total_cents: int):
    kb = InlineKeyboardMarkup()
    for it in items:
        pid = it["product_id"]
        kb.row(
            InlineKeyboardButton("\u2796", callback_data=cb("cq", pid, "-1")),
            InlineKeyboardButton(str(it["qty"]), callback_data="noop"),
            InlineKeyboardButton("\u2795", callback_data=cb("cq", pid, "+1")),
            InlineKeyboardButton("\U0001f5d1\ufe0f", callback_data=cb("crm", pid)),
        )
    # Primary CTA first, full-width; destructive action last.
    kb.add(InlineKeyboardButton(
        texts.BTN_CHECKOUT.format(total=fmt_money(total_cents, config.CURRENCY)),
        callback_data="co"))
    if promo_code:
        kb.row(
            InlineKeyboardButton(f"\u2705 {promo_code} \u2014 {promo_desc}",
                                 callback_data="noop"),
            InlineKeyboardButton(texts.BTN_PROMO_REMOVE, callback_data="px"),
        )
    else:
        kb.add(InlineKeyboardButton(texts.BTN_PROMO, callback_data="pm"))
    kb.row(InlineKeyboardButton(texts.BTN_CONTINUE_SHOPPING, callback_data="shop"))
    kb.row(InlineKeyboardButton(texts.BTN_CLEAR_CART, callback_data="cc"))
    return kb


def cart_empty_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_BROWSE, callback_data="shop"))
    kb.row(BTN_MENU)
    return kb


def clear_confirm_kb(n: int):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(texts.BTN_KEEP_THEM, callback_data="cart"),
        InlineKeyboardButton(f"{texts.BTN_YES_CLEAR} ({n})", callback_data="ccy"),
    )
    return kb


# --------------------------------------------------------- checkout ---
def details_kb(kind: str):
    """Merged delivery-details step: method toggle + Continue."""
    kb = InlineKeyboardMarkup()
    d = "\u2705" if kind == "delivery" else "\u2b1c"
    p = "\u2705" if kind == "pickup" else "\u2b1c"
    kb.row(
        InlineKeyboardButton(f"{texts.BTN_DELIVERY} {d}", callback_data=cb("cod", "delivery")),
        InlineKeyboardButton(f"{texts.BTN_PICKUP} {p}", callback_data=cb("cod", "pickup")),
    )
    kb.add(InlineKeyboardButton(texts.BTN_CONTINUE, callback_data="co3"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="cart"))
    return kb


def details_reply_kb(kind: str):
    """Share buttons for the details step (no 'type manually' decoy — typing just works)."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    kb.add(KeyboardButton(texts.BTN_SHARE_PHONE, request_contact=True))
    if kind == "delivery":
        kb.add(KeyboardButton(texts.BTN_SHARE_LOCATION, request_location=True))
    kb.row(KeyboardButton(texts.BTN_BACK))
    return kb


def payment_kb(rails, cod: bool, prefix: str = "cop", back_cbd: str = "co4"):
    """Payment rail buttons in SPEC2 §1 order.

    `rails`: list of (method_id, label); direct-crypto chains arrive
    pre-expanded as `direct_<chain>` (no sub-menu hop). The "cod" entry
    carries label None and is rendered as COD/pickup here.
    Crypto chains are hidden behind a single 'Crypto payment' submenu.

    `prefix`/`back_cbd` allow reusing this builder outside the checkout
    flow; the defaults keep every existing call site unchanged.
    """
    kb = InlineKeyboardMarkup()
    for method, label in rails:
        if method == "crypto":
            kb.add(InlineKeyboardButton(
                texts.BTN_CRYPTO_PAYMENT, callback_data=f"{prefix}:crypto_menu"))
        elif method == "cod":
            kb.add(InlineKeyboardButton(
                texts.BTN_COD if cod else texts.BTN_PAY_PICKUP,
                callback_data=f"{prefix}:cod"))
        else:
            kb.add(InlineKeyboardButton(label, callback_data=f"{prefix}:{method}"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=back_cbd))
    return kb


def crypto_menu_kb(prefix: str = "cop"):
    """Submenu for crypto payment options."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("\u20bf BTC", callback_data=f"{prefix}:direct_btc"))
    kb.add(InlineKeyboardButton(texts.BTN_USDT_MENU, callback_data=f"{prefix}:usdt_menu"))
    kb.add(InlineKeyboardButton(texts.BTN_USDC_MENU, callback_data=f"{prefix}:usdc_menu"))
    kb.add(InlineKeyboardButton("Gram(Ton)", callback_data=f"{prefix}:direct_ton"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=f"{prefix}:back_to_payment"))
    return kb


def usdt_menu_kb(prefix: str = "cop"):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Base", callback_data=f"{prefix}:usdt_base"))
    kb.add(InlineKeyboardButton("Optimism", callback_data=f"{prefix}:usdt_op"))
    kb.add(InlineKeyboardButton("Polygon", callback_data=f"{prefix}:usdt_polygon"))
    back = "tup:back" if prefix == "tupc" else "cop:crypto_menu"
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=back))
    return kb


def usdc_menu_kb(prefix: str = "cop"):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Base", callback_data=f"{prefix}:usdc_base"))
    kb.add(InlineKeyboardButton("Optimism", callback_data=f"{prefix}:usdc_op"))
    kb.add(InlineKeyboardButton("Polygon", callback_data=f"{prefix}:usdc_polygon"))
    back = "tup:back" if prefix == "tupc" else "cop:crypto_menu"
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=back))
    return kb


def confirm_kb(total_cents: int):
    """Merged review & confirm: primary CTA first, section edits, back."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"{texts.BTN_PLACE_ORDER} \u00b7 {fmt_money(total_cents, config.CURRENCY)}",
        callback_data="cok"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="cob"))
    return kb


def waiting_kb(order_id: int):
    """Payment-waiting screen: switch method while the order is still pending."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_CHANGE_PAYMENT,
                                callback_data=cb("copc", order_id)))
    return kb


def order_success_kb(order_id: int, bot_username: str = None):
    """Post-payment screen: track the order, or jump to the main menu."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_TRACK_ORDER,
                                callback_data=cb("o", order_id)))
    if bot_username:
        # Deep link for instant order access
        kb.add(InlineKeyboardButton(
            texts.BTN_ORDER_LINK,
            url=f"https://t.me/{bot_username}?start=o_{order_id}"))
    kb.row(BTN_MENU)
    return kb


# ---------------------------------------------------------- orders ---
def orders_kb(orders, page: int, total: int, per_page: int = 6):
    kb = InlineKeyboardMarkup()
    for o in orders:
        kb.add(InlineKeyboardButton(
            texts.MSG_ORDER_LINE.format(
                oid=o["id"],
                total=fmt_money(o["total_cents"], config.CURRENCY),
                status=texts.STATUS_LABEL.get(o["status"], o["status"])),
            callback_data=cb("o", o["id"])))
    page, total_pages = paginate(total, page, per_page)
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(texts.BTN_PREV, callback_data=cb("ord", page - 1)))
        row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(texts.BTN_NEXT, callback_data=cb("ord", page + 1)))
        kb.row(*row)
    kb.row(BTN_MENU)
    return kb


def order_detail_kb(order_id: int):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(texts.BTN_BUY_AGAIN, callback_data=cb("ob", order_id)),
        InlineKeyboardButton(texts.BTN_RATE_ITEMS, callback_data=cb("or", order_id)),
    )
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("ord", 0)))
    kb.row(BTN_MENU)
    return kb


# ---------------------------------------------------------- profile ---
def profile_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(texts.BTN_PURCHASES, callback_data="pur"),
        InlineKeyboardButton(texts.BTN_WISHLIST, callback_data="wl"),
    )
    kb.row(
        InlineKeyboardButton(texts.BTN_REFERRAL, callback_data="ref"),
        InlineKeyboardButton(texts.BTN_REDEEM, callback_data="pm3"),
    )
    kb.add(InlineKeyboardButton(texts.BTN_BALANCE, callback_data="bal:topup"))
    kb.row(BTN_MENU)
    return kb


def balance_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_TOPUP, callback_data="bal:topup"))
    kb.row(BTN_MENU)
    return kb


def info_kb():
    kb = InlineKeyboardMarkup()
    kb.row(BTN_MENU)
    return kb


def rent_kb():
    kb = InlineKeyboardMarkup()
    kb.row(BTN_MENU)
    return kb


def balance_topup_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    for cents in [500, 1000, 2500, 5000]:
        label = fmt_money(cents, config.CURRENCY)
        kb.insert(InlineKeyboardButton(label, callback_data=f"bal:amt:{cents}"))
    kb.add(InlineKeyboardButton(texts.BTN_CUSTOM_AMOUNT, callback_data="bal:custom"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="bal:back"))
    return kb


def wishlist_kb(items):
    kb = InlineKeyboardMarkup()
    for p in items:
        kb.add(InlineKeyboardButton(
            f"{p['name']} \u2014 {fmt_money(p['price_cents'], config.CURRENCY)}",
            callback_data=cb("p", p["id"])))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="prof"))
    kb.row(BTN_MENU)
    return kb


def support_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_SUPPORT_CTA, callback_data="sup"))
    kb.row(BTN_MENU)
    return kb


def admin_reply_kb(tg_id: int):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_REPLY, callback_data=cb("srep", tg_id)))
    return kb


def force_reply(placeholder: str = ""):
    if placeholder:
        return ForceReply(selective=True, input_field_placeholder=placeholder)
    return ForceReply(selective=True)


# ------------------------------------------------------------ admin ---
def admin_console_kb(mask: int, maintenance_on: bool):
    kb = InlineKeyboardMarkup(row_width=2)
    if mask & config.PERM_STATS:
        kb.insert(InlineKeyboardButton(texts.BTN_ADM_STATS, callback_data="ad:st"))
    if mask & config.PERM_CATALOG:
        kb.insert(InlineKeyboardButton(texts.BTN_ADM_CATALOG, callback_data="ad:cat"))
    if mask & config.PERM_ORDERS:
        kb.insert(InlineKeyboardButton(texts.BTN_ADM_ORDERS,
                                       callback_data=cb("ad:ord", "pending", 0)))
        kb.insert(InlineKeyboardButton(texts.BTN_CRYPTO_PANEL,
                                       callback_data="cry:panel"))
    if mask & config.PERM_USERS:
        kb.insert(InlineKeyboardButton(texts.BTN_ADM_USERS, callback_data="ad:usr"))
    if mask & config.PERM_PROMOS:
        kb.insert(InlineKeyboardButton(texts.BTN_ADM_PROMOS, callback_data="ad:pro"))
    if mask & config.PERM_BROADCAST:
        kb.insert(InlineKeyboardButton(texts.BTN_ADM_BROADCAST, callback_data="ad:bc"))
    if mask & config.PERM_MAINTENANCE:
        label = texts.BTN_MAINT_OFF if maintenance_on else texts.BTN_MAINT_ON
        kb.insert(InlineKeyboardButton(label, callback_data="ad:mnt"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="menu"))
    return kb


def admin_categories_kb(cats):
    kb = InlineKeyboardMarkup()
    for c in cats:
        kb.add(InlineKeyboardButton(f"{c['emoji']} {c['name']}",
                                    callback_data=cb("ac:cl", c["id"])))
    kb.add(InlineKeyboardButton(texts.BTN_CAT_ADD, callback_data="ac:cadd"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="adm"))
    return kb


def admin_category_kb(cat, n_products: int):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"{texts.BTN_PROD_ADD} ({n_products})",
                                callback_data=cb("ac:padd", cat["id"])))
    kb.row(
        InlineKeyboardButton("\u2712\ufe0f Rename", callback_data=cb("ac:cren", cat["id"])),
        InlineKeyboardButton(texts.BTN_DELETE, callback_data=cb("ac:cdel", cat["id"])),
    )
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="ad:cat"))
    return kb


def admin_products_kb(items, cat_id: int, page: int, total: int, per_page: int = 8):
    kb = InlineKeyboardMarkup()
    for p in items:
        state = texts.MSG_PROD_STATE_ON if p["is_active"] else texts.MSG_PROD_STATE_OFF
        kb.add(InlineKeyboardButton(
            texts.MSG_PROD_LINE_ADMIN.format(id=p["id"], name=p["name"],
                                             price=fmt_money(p["price_cents"], config.CURRENCY),
                                             state=state),
            callback_data=cb("ac:p", p["id"])))
    page, total_pages = paginate(total, page, per_page)
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(texts.BTN_PREV,
                                            callback_data=cb("ac:plist", cat_id, page - 1)))
        row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(texts.BTN_NEXT,
                                            callback_data=cb("ac:plist", cat_id, page + 1)))
        kb.row(*row)
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("ac:cl", cat_id)))
    return kb


def admin_product_kb(p):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.insert(InlineKeyboardButton(texts.BTN_EDIT_PRICE, callback_data=cb("ac:ppr", p["id"])))
    kb.insert(InlineKeyboardButton(texts.BTN_EDIT_STOCK, callback_data=cb("ac:pst", p["id"])))
    if p["kind"] == "digital":
        kb.insert(InlineKeyboardButton(texts.BTN_ADD_VALUES, callback_data=cb("ac:pv", p["id"])))
        kb.insert(InlineKeyboardButton(
            f"{'♾ Unlimited: ON' if p['is_unlimited'] else '♾ Unlimited: OFF'}",
            callback_data=cb("ac:pul", p["id"])))
    kb.insert(InlineKeyboardButton(texts.BTN_TOGGLE, callback_data=cb("ac:ptog", p["id"])))
    kb.insert(InlineKeyboardButton(texts.BTN_DELETE, callback_data=cb("ac:pdel", p["id"])))
    kb.row(InlineKeyboardButton(texts.BTN_BACK,
                                callback_data=cb("ac:plist", p["category_id"], 0)))
    return kb


def admin_orders_filter_kb(counts: dict):
    kb = InlineKeyboardMarkup(row_width=2)
    for st in texts.ORDER_STATUSES:
        label = f"{texts.STATUS_EMOJI[st]} {texts.STATUS_LABEL[st]} ({counts.get(st, 0)})"
        kb.insert(InlineKeyboardButton(label, callback_data=cb("ad:ord", st, 0)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="adm"))
    return kb


def admin_orders_list_kb(orders, status: str, page: int, total: int, per_page: int = 8):
    kb = InlineKeyboardMarkup()
    for o in orders:
        kb.add(InlineKeyboardButton(
            texts.MSG_ORDER_ADMIN_LINE.format(
                oid=o["id"], total=fmt_money(o["total_cents"], config.CURRENCY),
                name=o["user_name"] or o["user_tg_id"]),
            callback_data=cb("ad:o", o["id"])))
    page, total_pages = paginate(total, page, per_page)
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(texts.BTN_PREV,
                                            callback_data=cb("ad:ord", status, page - 1)))
        row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(texts.BTN_NEXT,
                                            callback_data=cb("ad:ord", status, page + 1)))
        kb.row(*row)
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="ad:ordf"))
    return kb


def admin_order_detail_kb(order_id: int, status: str):
    kb = InlineKeyboardMarkup()
    nxt = {"pending": ["confirmed", "cancelled"],
           "confirmed": ["preparing", "cancelled"],
           "preparing": ["shipped", "cancelled"],
           "shipped": ["delivered", "cancelled"],
           "delivered": [], "cancelled": []}.get(status, [])
    for st in nxt:
        kb.add(InlineKeyboardButton(
            f"\u23ed\ufe0f Set: {texts.STATUS_LABEL[st]}",
            callback_data=cb("ad:os", order_id, st)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK,
                                callback_data=cb("ad:ord", status, 0)))
    return kb


def admin_user_kb(user):
    kb = InlineKeyboardMarkup()
    tg_id = user["tg_id"]
    kb.row(
        InlineKeyboardButton(texts.BTN_USER_UNBLOCK if user["is_blocked"] else texts.BTN_USER_BLOCK,
                             callback_data=cb("ad:ub", tg_id)),
        InlineKeyboardButton(texts.BTN_SET_ROLE, callback_data=cb("ad:ur", tg_id)),
    )
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="ad:usr"))
    return kb


def admin_role_kb(tg_id: int, mask: int):
    kb = InlineKeyboardMarkup(row_width=2)
    for bit, name in sorted(config.PERM_NAMES.items()):
        mark = "\u2705" if mask & bit else "\u2b1c"
        kb.insert(InlineKeyboardButton(f"{mark} {name}",
                                       callback_data=cb("ad:urc", tg_id, bit)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("ad:u", tg_id)))
    return kb


def admin_promos_kb(promos):
    kb = InlineKeyboardMarkup()
    for pr in promos:
        desc = (f"{pr['value']}% off" if pr["kind"] == "percent"
                else f"{fmt_money(pr['value'], config.CURRENCY)} off")
        uses = f"{pr['used_count']}/{pr['max_uses'] or '\u221e'}"
        state = "\u2705" if pr["is_active"] else "\u23f8\ufe0f"
        kb.add(InlineKeyboardButton(
            texts.MSG_PROMO_LINE.format(code=pr["code"], desc=desc, uses=uses, state=state),
            callback_data=cb("ac:pr", pr["id"])))
    kb.add(InlineKeyboardButton(texts.BTN_PROMO_ADD, callback_data="ac:pradd"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="adm"))
    return kb


def admin_promo_kb(pr):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("\u2705 Activate" if not pr["is_active"] else "\u23f8\ufe0f Deactivate",
                             callback_data=cb("ac:prt", pr["id"])),
        InlineKeyboardButton(texts.BTN_DELETE, callback_data=cb("ac:prd", pr["id"])),
    )
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="ad:pro"))
    return kb


def broadcast_confirm_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(texts.BTN_CANCEL, callback_data="bcx"),
        InlineKeyboardButton(texts.BTN_SEND, callback_data="bcy"),
    )
    return kb


def broadcast_stop_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_STOP, callback_data="bcstop"))
    return kb


def maintenance_kb(is_on: bool):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_MAINT_OFF if is_on else texts.BTN_MAINT_ON,
                                callback_data=cb("mnt", 0 if is_on else 1)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="adm"))
    return kb


def confirm_generic_kb(yes_cb: str, back_cb: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(texts.BTN_CANCEL, callback_data=back_cb),
        InlineKeyboardButton(texts.BTN_CONFIRM, callback_data=yes_cb),
    )
    return kb


def remove_keyboard():
    return ReplyKeyboardRemove()

# ------------------------------------------------------- crypto keyboards ---
def cryptobot_pay_kb(pay_url: str, invoice_id: int):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"{texts.BTN_CRYPTOBOT_PAY} #{invoice_id}", url=pay_url))
    # No "I've Paid — Check" button: payment is auto-detected.
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="copb"))
    return kb


def topup_cryptobot_kb(pay_url: str, invoice_id: int):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"{texts.BTN_CRYPTOBOT_PAY} #{invoice_id}", url=pay_url))
    kb.row(InlineKeyboardButton("\u2705 I've Paid \u2014 Check", callback_data=f"tupkb:{invoice_id}"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="tup:back"))
    return kb


def deposit_kb(deposit_id: int):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_DEPOSIT_CHECK,
                                callback_data=cb("codc", deposit_id)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="copb"))
    return kb


def crypto_expired_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_NEW_PAYMENT, callback_data="copb"))
    kb.row(BTN_MENU)
    return kb


def crypto_other_methods_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_OTHER_METHODS, callback_data="copb"))
    kb.row(BTN_MENU)
    return kb


def crypto_admin_kb(pending: int, late: int, underpaid: int):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.insert(InlineKeyboardButton(texts.BTN_CRYO_PENDING.format(n=pending),
                                   callback_data="cry:pending"))
    kb.insert(InlineKeyboardButton(texts.BTN_CRYO_LATE.format(n=late),
                                   callback_data="cry:late"))
    kb.insert(InlineKeyboardButton(texts.BTN_CRYO_UNDERPAID.format(n=underpaid),
                                   callback_data="cry:underpaid"))
    kb.insert(InlineKeyboardButton(texts.BTN_CRYO_CHAINS, callback_data="cry:chains"))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="adm"))
    return kb


def crypto_deposits_kb(deposits, page: int, total_pages: int, view: str):
    kb = InlineKeyboardMarkup()
    for d in deposits:
        kb.add(InlineKeyboardButton(
            texts.MSG_CRYPTO_DEPOSIT_ROW.format(
                id=d["id"], chain=d["chain"],
                address=(d["address"] or "")[:10] + "\u2026",
                amount=fmt_money(d["amount_cents"], config.CURRENCY), oid=d["order_id"], status=d["status"])[:64],
            callback_data=cb("cryd", d["id"])))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("\u25c0\ufe0f", callback_data=cb("cryp", view, page - 1)))
    nav.append(InlineKeyboardButton(f"{page + 1}/{max(total_pages, 1)}",
                                    callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("\u25b6\ufe0f", callback_data=cb("cryp", view, page + 1)))
    kb.row(*nav)
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="cry:panel"))
    return kb


def crypto_deposit_detail_kb(deposit_id: int, view: str):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.insert(InlineKeyboardButton(texts.BTN_CRYO_CONFIRM_MANUAL,
                                   callback_data=cb("cryok", deposit_id)))
    kb.insert(InlineKeyboardButton(texts.BTN_CRYO_REJECT,
                                   callback_data=cb("cryno", deposit_id)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data=cb("cry", view)))
    return kb


def crypto_chains_kb(chain_states):
    """chain_states: list of (chain_id, enabled_bool)."""
    from crypto_payments import CHAINS
    kb = InlineKeyboardMarkup()
    for cid, enabled in chain_states:
        state = "\u2705" if enabled else "\u2b1c"
        kb.add(InlineKeyboardButton(
            texts.BTN_CHAIN_TOGGLE.format(state=state,
                                          label=CHAINS.get(cid, {}).get("button", str(cid))),
            callback_data=cb("cryc", cid)))
    kb.row(InlineKeyboardButton(texts.BTN_BACK, callback_data="cry:panel"))
    return kb


# --- Rent flow (control-plane plans) ---
def rent_plans_kb(plan_labels, selected_id):
    """Rent entry screen: just Continue to Payment + Menu (checkout Step-1 style).

    Plan selection (Monthly/Yearly) lives BEHIND the Continue button.
    plan_labels/selected_id kept for signature compatibility.
    """
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton(
            texts.BTN_CONTINUE_TO_PAYMENT, callback_data="rent:plans"
        )
    )
    kb.row(BTN_MENU)
    kb.add(InlineKeyboardButton(texts.BTN_RENT_MINE, callback_data="rent:mine"))
    return kb


def rent_plan_kb(plan_labels, selected_id=None):
    """Plan selection screen (behind Continue to Payment): Monthly / Yearly."""
    kb = InlineKeyboardMarkup()
    row = []
    for pid, label in plan_labels:
        mark = "\u2705 " if str(pid) == str(selected_id) else ""
        row.append(
            InlineKeyboardButton(f"{mark}{label}", callback_data=f"rent:select:{pid}")
        )
    if row:
        kb.row(*row)
    kb.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="rent:back"))
    kb.row(BTN_MENU)
    return kb


def rent_method_kb(plan_id):
    """Payment method selection: Balance, CryptoBot, Crypto payments."""
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(texts.BTN_RENT_BALANCE, callback_data=f"rent:method:{plan_id}:balance"),
        InlineKeyboardButton(texts.BTN_RENT_CRYPTOBOT, callback_data=f"rent:method:{plan_id}:cryptobot"),
    )
    kb.add(
        InlineKeyboardButton(texts.BTN_RENT_CRYPTO, callback_data=f"rent:method:{plan_id}:crypto"),
    )
    kb.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="rent:back"))
    kb.row(BTN_MENU)
    return kb


def rent_confirm_kb(plan_id, provider):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_RENT_CONFIRM, callback_data=f"rent:confirm:{plan_id}:{provider}"))
    kb.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="rent:back"))
    kb.row(BTN_MENU)
    return kb


def rent_back_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="rent:back"))
    kb.row(BTN_MENU)
    return kb


def rent_pay_kb(pay_url):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts.BTN_RENT_PAY, url=pay_url))
    kb.add(InlineKeyboardButton(texts.BTN_BACK, callback_data="rent:back"))
    kb.row(BTN_MENU)
    return kb
