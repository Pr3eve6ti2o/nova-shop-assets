"""ALL user-visible English strings for Nova Shop Bot.

This is the single source of copy. No UI text may be hardcoded anywhere else.
Placeholders use .format() style: {name}, {price}, etc.

EMOJI LEXICON — use only these, always with the same meaning:
    SHOP / STORE            Shop, browse, catalog, storefront
    CART                    cart, add to cart
    ORDERS                  orders, order history
    PROFILE                 profile, account
    SUPPORT                 support chat
    SEARCH                  search
    STAR                    ratings & reviews; Telegram Stars (payment context)
    CARD                    card payment
    CASH                    cash on delivery
    HANDSHAKE               pay on pickup
    CRYPTOBOT               CryptoBot payments
    COIN                    direct crypto deposits
    CHECK                   success, confirm
    WARN                    warning, needs attention
    CROSS                   error, cancel, destructive
    BACK                    back (navigation)
    HOME                    main menu
    MONEY                   money, prices, totals
    TICKET                  promo codes
    PIN                     address, location
    PHONE                   phone, contact
    TRUCK                   delivery
    RUNNER                  pickup
    RECEIPT                 receipt, order summary
    GIFT                    referrals, rewards
    KEY                     license keys, digital purchases
    PENCIL                  edit
    PLUS                    add
    TRASH                   delete, clear (destructive)
    HOURGLASS               waiting, in progress
    CHART                   stats, dashboard
    MEGA                    broadcast
    WRENCH                  maintenance, settings
    BULB                    tip
    USERS                   users, groups
    SHIELD                  roles, permissions
    BAN                     block
    PACKAGE                 stock, parcels
"""

# ---------------------------------------------------------------- buttons ---
BTN_SHOP = "\U0001f6cd\ufe0f Shop"
BTN_INFO = "\u2139\ufe0f Info"
BTN_RENT = "\U0001f4e6 Rent"
MSG_INFO = (
    "\u2139\ufe0f <b>About Nova Shop</b>\n\n"
    "Instant delivery of digital goods, right inside Telegram.\n\n"
    "<b>Team</b>\n"
    "Built and run by the Nova team.\n\n"
    "<b>Support</b>\n"
    "Need help? Use the Support button."
)
MSG_RENT = (
    "\U0001f4e6 <b>Rent Bot Features</b>\n\n"
    "Premium features with API access, billed monthly.\n\n"
    "<b>Plans</b>\n"
    "• Starter — $9/mo\n"
    "• Pro — $29/mo\n"
    "• Enterprise — $99/mo\n\n"
    "Contact support to activate."
)
BTN_SEARCH = "\U0001f50d Search"
BTN_CART = "\U0001f6d2 Cart"
BTN_ORDERS = "\U0001f4e6 Orders"
BTN_PROFILE = "\U0001f464 Profile"
BTN_SUPPORT = "\U0001f198 Support"
BTN_ADMIN = "\U0001f6e0\ufe0f Admin"
BTN_MENU = "\U0001f3e0 Menu"
BTN_BACK = "\U0001f519 Back"
BTN_PREV = "\u25c0\ufe0f Prev"
BTN_NEXT = "Next \u25b6\ufe0f"
BTN_ADD_CART = "\U0001f6d2 Add to cart \u00b7 {price}"
BTN_BUY_NOW = "\u26a1 Buy now \u00b7 {price}"
BTN_WISH_ADD = "\U0001f90d Add to Wishlist"
BTN_WISH_IN = "\u2764\ufe0f In Wishlist"
BTN_REVIEWS = "\u2b50 Reviews ({n})"
BTN_LEAVE_REVIEW = "\u2712\ufe0f Leave a Review"
BTN_SKIP = "\u23ed\ufe0f Skip"
BTN_PROMO = "\U0001f39f\ufe0f Promo code"
BTN_PROMO_REMOVE = "\u2716\ufe0f Remove Promo"
BTN_CLEAR_CART = "\U0001f5d1\ufe0f Clear Cart"
BTN_CHECKOUT = "\u2705 Checkout \u00b7 {total}"
BTN_CONTINUE_SHOPPING = "\U0001f6cd\ufe0f Continue shopping"
BTN_BROWSE = "\U0001f6cd\ufe0f Browse products"
BTN_KEEP_THEM = "\u21a9\ufe0f Keep items"
BTN_YES_CLEAR = "\U0001f5d1\ufe0f Yes, Clear It"
BTN_CONTINUE = "\u27a1\ufe0f Continue"
BTN_DELIVERY = "\U0001f69a Delivery"
BTN_PICKUP = "\U0001f3c3 Pickup"
BTN_SHARE_PHONE = "\U0001f4de Share My Phone Number"
BTN_SHARE_LOCATION = "\U0001f4cd Share Location"
BTN_HAVE_PROMO = "\U0001f39f\ufe0f Have a promo code?"
BTN_PLACE_ORDER = "\U0001f4b3 Continue to Payment"
BTN_CHANGE_PAYMENT = "\U0001f504 Change payment method"
BTN_CANCEL = "\u274c Cancel"
BTN_TRACK_ORDER = "\U0001f4e6 Track Order"
BTN_CARD = "\U0001f4b3 Card \u2014 {total}"
BTN_STARS = "\u2b50 Stars \u2014 {n}"
BTN_COD = "\U0001f4b5 Cash on Delivery"
BTN_PAY_PICKUP = "\U0001f91d Pay on Pickup"
BTN_BUY_AGAIN = "\U0001f501 Buy Again"
BTN_RATE_ITEMS = "\u2b50 Rate Items"
BTN_PURCHASES = "\U0001f511 My Purchases"
BTN_BALANCE = "\U0001f4b3 Balance"
BTN_TOPUP = "\U0001f4b3 Top Up"
BTN_CUSTOM_AMOUNT = "\u270f\ufe0f Custom Amount"
BTN_PAY_BALANCE = "\U0001f4b3 Pay with Balance ({balance})"
BTN_PAY_WITH_BALANCE = "\U0001f4b3 Pay with Balance"
BTN_USDT_MENU = "USDT"
BTN_USDC_MENU = "USDC"
MSG_INSUFFICIENT_BALANCE = "Insufficient balance \u2014 top up first."
BTN_ORDER_LINK = "\U0001f517 Order Link"
BTN_CRYPTO_PAYMENT = "\U0001f4b0 Crypto Payment"
BTN_CRYPTOBOT = "\U0001f48e CryptoBot"
MSG_CRYPTO_MENU = (
    "\U0001f4b0 <b>Crypto Payment</b>\n\n"
    "Choose a cryptocurrency:"
)
BTN_WISHLIST = "\u2764\ufe0f Wishlist"
BTN_REFERRAL = "\U0001f465 Referral Program"
BTN_REDEEM = "\U0001f39f\ufe0f Redeem promo"
BTN_HISTORY = "\U0001f4cb History"
BTN_SUPPORT_CTA = "\U0001f4ac Contact Support"
BTN_REPLY = "\U0001f4ac Reply"
BTN_CONFIRM = "\u2705 Confirm"
BTN_EDIT = "\u2712\ufe0f"
BTN_SEND = "\U0001f680 Send"
BTN_STOP = "\u23f9\ufe0f Stop"

# Payment method labels (shared by checkout, orders, receipts).
PAY_METHOD_LABEL = {
    "card": "\U0001f4b3 Card",
    "stars": "\u2b50 Telegram Stars",
    "telegram": "\u2b50 Telegram Stars",  # m10: provider="telegram" fell through to raw text
    "tonconnect": "\U0001f48e TON (TON Connect)",
    "cod": "\U0001f4b5 Cash on Delivery",
    "cryptobot": "\U0001f48e CryptoBot",
    "direct_btc": "\U0001fa99 BTC (direct)",
    "direct_eth": "\U0001fa99 USDT-ERC20 (direct)",
    "direct_trx": "\U0001fa99 USDT-TRC20 (direct)",
    "direct_ton": "\U0001fa99 TON (direct)",
    "usdt_base": "\U0001fa99 USDT (Base)",
    "usdc_base": "\U0001fa99 USDC (Base)",
    "usdt_op": "\U0001fa99 USDT (Optimism)",
    "usdc_op": "\U0001fa99 USDC (Optimism)",
    "usdt_polygon": "\U0001fa99 USDT (Polygon)",
    "usdc_polygon": "\U0001fa99 USDC (Polygon)",
}
PAY_METHOD_PICKUP = "\U0001f91d Pay on Pickup"

# Admin buttons
BTN_ADM_STATS = "\U0001f4ca Stats"
BTN_ADM_CATALOG = "\U0001f6cd\ufe0f Catalog"
BTN_ADM_ORDERS = "\U0001f9fe Orders"
BTN_ADM_USERS = "\U0001f465 Users"
BTN_ADM_PROMOS = "\U0001f39f\ufe0f Promos"
BTN_ADM_BROADCAST = "\U0001f4e2 Broadcast"
BTN_ADM_MAINT = "\U0001f527 Maintenance"
BTN_CAT_ADD = "\u2795 Add Category"
BTN_PROD_ADD = "\u2795 Add Product"
BTN_DELETE = "\U0001f5d1\ufe0f Delete"
BTN_TOGGLE = "\U0001f501 Toggle Active"
BTN_EDIT_PRICE = "\U0001f4b0 Edit Price"
BTN_EDIT_STOCK = "\U0001f4e6 Edit Stock"
BTN_ADD_VALUES = "\U0001f511 Add License Keys"
BTN_USER_BLOCK = "\U0001f6ab Block"
BTN_USER_UNBLOCK = "\u2705 Unblock"
BTN_SET_ROLE = "\U0001f6e1\ufe0f Set Role"
BTN_PROMO_ADD = "\u2795 New Promo"
BTN_MAINT_ON = "\U0001f527 Maintenance: ON"
BTN_MAINT_OFF = "\U0001f527 Maintenance: OFF"

# ----------------------------------------------------------------- common ---
TOAST_ADDED_CART = "Added to cart"
TOAST_REMOVED = "Removed"
TOAST_SAVED = "Saved"
TOAST_DELETED = "Deleted"
TOAST_WISH_ADDED = "Added to wishlist"
TOAST_WISH_REMOVED = "Removed from wishlist"
TOAST_QTY_MIN = "Minimum quantity is 1"
TOAST_BUY_FIRST = "Buy it first to leave a review"
TOAST_NEED_ADMIN = "You need admin rights for that"
TOAST_PROMO_APPLIED = "\u2705 {code} applied: {desc}"
TOAST_PROMO_REMOVED = "Promo removed"
TOAST_REVIEW_SAVED = "Thanks for your review!"
TOAST_COPIED = "Copied"
TOAST_ORDER_STATUS = "Order #{oid} \u2192 {status}"
TOAST_MAINT_ON = "Maintenance mode ON"
TOAST_MAINT_OFF = "Maintenance mode OFF"
TOAST_BROADCAST_STOPPED = "Broadcast stopped"
TOAST_USER_BLOCKED = "User blocked"
TOAST_USER_UNBLOCKED = "User unblocked"
TOAST_SCANNING = "Scanning the blockchain\u2026"
TOAST_CRYPTO_ALREADY = "Already confirmed"

ERR_GENERIC = "\u26a0\ufe0f Something went wrong. Please try again."
ERR_RATE_LIMITED = "\u23f3\ufe0f You're tapping too fast \u2014 please wait a few seconds."
ERR_PAY_RATE_LIMITED = "\u23f3\ufe0f Too many payment attempts \u2014 please wait a minute."
ERR_MAINTENANCE = "\U0001f527 The shop is under maintenance. Please come back soon!"
ERR_NOT_FOUND = "\u26a0\ufe0f Not found \u2014 it may have been removed."
ERR_OUT_OF_STOCK = "\u26a0\ufe0f Sorry, this item just went out of stock."
ERR_PAY_DECLINED = "\u274c Payment couldn't be completed: {reason}"
ERR_INVALID_QTY = "\u26a0\ufe0f Please enter a positive number."
ERR_INVALID_AMOUNT = "\u26a0\ufe0f That amount isn't valid. Please pick a positive amount."

# ------------------------------------------------------------- start/menu ---
MSG_WELCOME = (
    "<b>\U0001f6cd\ufe0f Welcome to Nova Shop \u2014 your store inside Telegram.</b>\n\n"
    "<blockquote>Hand-picked products at honest prices, checkout in under a minute, "
    "and live tracking on every order. Pay by card, Telegram Stars, or crypto.</blockquote>\n\n"
    "\U0001f4a1 <i>Tip: tap \U0001f6cd\ufe0f Shop to browse, or \U0001f50d Search "
    "to jump straight to a product.</i>"
)
MSG_WELCOME_BACK = (
    "<b>Welcome back! \U0001f44b</b>\n\n"
    "{summary}"
)
MSG_WELCOME_BACK_LINE_CART = "\U0001f6d2 Items waiting in your cart: {n}"
MSG_WELCOME_BACK_LINE_ORDER = "\U0001f4e6 Order #{oid} \u2014 {status}"
MSG_WELCOME_BACK_LINE_NONE = "Your cart is empty \u2014 the catalog has new arrivals."
MSG_MENU = "\U0001f3e0 <b>Main Menu</b>\nWhat would you like to do?"
MSG_HELP = (
    "<b>\U0001f198 Help & FAQ</b>\n\n"
    "<b>How do I order?</b>\nBrowse the catalog \u2192 add items to cart \u2192 checkout. "
    "One tap per step, and you can go back and edit anything before paying.\n\n"
    "<b>How can I pay?</b>\n\U0001f4b3 Card (Telegram Payments) \u00b7 \u2b50 Telegram Stars "
    "\u00b7 \U0001f48e CryptoBot \u00b7 \U0001fa99 direct crypto (BTC, USDT, TON \u2014 no platform fee; network fees apply) "
    "\u00b7 \U0001f4b5 cash on delivery.\n\n"
    "<b>Where is my order?</b>\nOpen \U0001f4e6 Orders for the live status of every order.\n\n"
    "<b>Digital goods?</b>\nLicense keys are delivered instantly, right in this chat, after payment.\n\n"
    "<b>Support hours</b>\nOur team replies within ~2 hours, 08:00\u201320:00 IST, every day.\n\n"
    "<b>Refunds</b>\nDigital goods: full refund if the key doesn't work and we can't replace it. "
    "Physical goods: full refund before shipping; after shipping, refunds follow our returns process. "
    "Just message support with your order number.\n\n"
    "<b>Payment didn't go through?</b>\n"
    "\u2022 <i>Not detected yet</i> \u2014 crypto deposits need a few minutes and network confirmations.\n"
    "\u2022 <i>Payment window expired</i> \u2014 start a new payment; nothing was charged.\n"
    "\u2022 <i>Provider unreachable</i> \u2014 try again shortly or pick another method.\n\n"
    "Still stuck? Tap below \u2014 a human will reply.\n\n"
    "<b>Policies</b>\nOur Terms, Privacy Policy and Refund Policy: /terms \u00b7 /privacy \u00b7 /refund"
)
MSG_SUPPORT_ASK = (
    "\U0001f4ac <b>Contact Support</b>\n\n"
    "Describe your issue in one message and our team will get back to you here."
)
MSG_SUPPORT_REPLY_ASK = "\U0001f4ac <b>Reply to user {tg_id}</b>:\nSend your reply as the next message."
MSG_SUPPORT_REPLIED = "\u2705 Reply sent to the user."
MSG_SUPPORT_FROM_ADMIN = "\U0001f4e9 <b>Support reply:</b>\n\n{text}"

# ------------------------------------------------------------------- shop ---
MSG_CATEGORIES = "\U0001f6cd\ufe0f <b>Shop</b>\nPick a category to start browsing:"
MSG_CATALOG_TITLE = "\U0001f6cd\ufe0f <b>Catalog</b>\nAll products:"
MSG_CATEGORY_EMPTY = "\U0001f4ed <b>{name}</b>\n\nNothing here yet \u2014 check back soon!"
MSG_PRODUCT_LINE = "{name} \u2014 {price}{rating}"
MSG_RATING_SUFFIX = "  \u2b50{avg}"
MSG_PRODUCT_CAPTION = (
    "<b>{name}</b>\n\n"
    "{description}\n\n"
    "\U0001f4b0 Price: <b>{price}</b>{old_price}\n"
    "{stock_line}\n"
    "{rating_line}"
)
MSG_OLD_PRICE = "  <s>{price}</s>"
MSG_STOCK_PHYSICAL = "\U0001f4e6 In stock: <b>{n}</b>"
MSG_STOCK_DIGITAL = "\u267e\ufe0f Digital delivery \u2014 instant after payment"
MSG_RATING_LINE = "\u2b50 <b>{avg}</b> ({n} reviews)"
MSG_NO_RATING = "\u2b50 No reviews yet \u2014 be the first!"
MSG_SEARCH_ASK = "\U0001f50d <b>Search</b>\n\nEnter a product name\u2026"
MSG_SEARCH_RESULTS = "\U0001f50d Results for \u201c{query}\u201d:"
MSG_SEARCH_EMPTY = "\U0001f50d Nothing found for \u201c{query}\u201d.\nTry a different spelling."
MSG_REVIEWS_TITLE = "\u2b50 <b>Reviews \u2014 {name}</b>"
MSG_REVIEW_LINE = "{stars} \u2014 {text}\n<i>{name}, {date}</i>"
MSG_REVIEW_NO_TEXT = "{stars}\n<i>{name}, {date}</i>"
MSG_NO_REVIEWS = "No reviews yet \u2014 be the first to share your experience."
MSG_REVIEW_ASK_RATING = "\u2b50 <b>Your rating</b>\n\nHow many stars would you give it?"
MSG_REVIEW_ASK_TEXT = "\u2712\ufe0f <b>Your review</b> (optional):\nSend the text, or tap Skip."
MSG_BREADCRUMB = "\U0001f6cd\ufe0f Shop \u203a {cat}"

# ------------------------------------------------------------------- cart ---
MSG_CART_TITLE = "\U0001f6d2 <b>Your Cart</b>"
MSG_CART_EMPTY = (
    "\U0001f6d2 <b>Your cart is empty</b> \u2014 let's fix that!\n"
    "Browse the catalog and add something you like."
)
MSG_CART_LINE = "<b>{name}</b> \u00d7{qty} \u2014 {line_total}"
MSG_CART_TOTAL = "\n\U0001f4b0 <b>Total: {total}</b>"
MSG_CART_PROMO_LINE = "\n\U0001f39f\ufe0f <code>{code}</code> \u2212{discount} applied"
MSG_CART_DROPPED = "\u26a0\ufe0f Removed from cart (out of stock): {names}"
MSG_CLEAR_CONFIRM = "\U0001f5d1\ufe0f <b>Remove all items from your cart?</b>"
MSG_CART_CLEARED = "\U0001f5d1\ufe0f Cart cleared."
MSG_PROMO_ASK = "\U0001f39f\ufe0f <b>Promo code</b>\n\nSend the code as a message."
MSG_PROMO_INVALID = "\u274c Invalid or expired promo code."
MSG_PROMO_MIN = "\u274c This code needs a minimum order of {minimum} USD."
MSG_PROMO_USED = "\u274c You've already used this code."

# --------------------------------------------------------------- checkout ---
MSG_CO_DETAILS = (
    "\U0001f4cb <b>Step 1 \u2014 Delivery details</b>\n\n"
    "\U0001f4de Phone: {phone}\n"
    "{address_line}\n"
    "Use the buttons below, or type your details."
)
MSG_CO_DETAILS_ADDRESS_LINE = "\U0001f4cd Address: {address}\n"
MSG_CO_DETAILS_SAVED_NOTE = "\n\u2713 Using your saved details \u2014 tap \U0001f4de/\U0001f4cd to update."
MSG_CO_PAYMENT = (
    "\U0001f4b3 <b>Step {step} \u2014 Payment method</b>\n\n"
    "Choose how you'd like to pay. You'll see the exact total before confirming."
)
MSG_CO_CONFIRM = (
    "\U0001f9fe <b>Step {step} \u2014 Review &amp; confirm</b>\n\n"
    "{lines}\n\n"
    "{contact_block}"
    "{payment}\n\n"
    "{totals}\n\n"
    "\U0001f39f\ufe0f Have a promo code? Just reply with it.\n\n"
    "Everything correct? Tap \u2714\ufe0f <b>Continue to payment</b>, or \u2712\ufe0f edit any section."
)
MSG_CO_CONFIRM_ADDRESS_LINE = "\U0001f4cd {address}\n"
MSG_CO_CONFIRM_PICKUP_LINE = "\U0001f3c3 Pickup\n"
MSG_CO_TOTALS = (
    "Subtotal: {subtotal}\n"
    "{discount_line}"
    "{delivery_line}"
    "<b>Total: {total}</b>"
)
MSG_CO_DISCOUNT_LINE = "Discount ({code}): \u2212{discount}\n"
MSG_CO_DELIVERY_LINE = "Delivery: {fee}\n"
MSG_NEED_CARD_TOKEN = "\u26a0\ufe0f Card payments aren't set up yet \u2014 please choose another method."
MSG_NEED_CRYPTOBOT_TOKEN = "\u26a0\ufe0f CryptoBot payments aren't set up yet \u2014 please choose another method."
MSG_CHOOSE_PAYMENT_FIRST = "\u26a0\ufe0f Please choose a payment method first."
MSG_ORDER_NOT_FOUND = "\u274c Order not found."
MSG_ORDER_ALREADY_PAID = "\u2705 This order is already paid."
MSG_FULFILL_FAIL = "\u26a0\ufe0f We couldn't prepare your order: {note}\nSupport has been notified."
MSG_INVALID_PHONE = "\u26a0\ufe0f That doesn't look like a phone number \u2014 please check and try again."
MSG_INVALID_ADDRESS = "\u26a0\ufe0f Please send a fuller address (street and city)."

# --------------------------------------------------------------- payments ---
MSG_INVOICE_TITLE = "Nova Shop order #{oid}"
MSG_INVOICE_DESC = "Payment for your Nova Shop order."
MSG_PAY_WAITING = (
    "\u23f3 <b>Waiting for payment\u2026</b>\n\n"
    "Complete the payment in Telegram to confirm your order."
)
MSG_ALREADY_PLACING = "\u23f3 Your order is already being placed \u2014 please wait."
MSG_FREE_ORDER_PLACED = (
    "\u2705 <b>Order #{oid} confirmed!</b>\n\n"
    "No payment needed.\n"
    "{fulfillment}"
)
MSG_PAY_OK = (
    "\u2705 <b>Payment successful!</b>\n\n"
    "Order <b>#{oid}</b> is confirmed.\n"
    "{fulfillment}"
)
MSG_FULFILL_DIGITAL = "\U0001f511 <b>Your digital goods:</b>\n{values}"
MSG_FULFILL_VALUE_LINE = "\u2022 <b>{name}</b> \u00d7{qty}:\n{code}"
MSG_FULFILL_PHYSICAL = "\U0001f4e6 We'll notify you as soon as your order ships."
MSG_PAY_FAIL_STOCK = (
    "\u274c Payment received, but an item ran out of stock during checkout.\n"
    "Our team will contact you about a refund or replacement."
)
MSG_COD_PLACED = (
    "\u2705 <b>Order #{oid} placed!</b>\n\n"
    "You'll {method} \u2014 total <b>{total}</b>.\n"
    "We'll message you at every step, from confirmation to delivery."
)
# NOTE: MSG_COD_ADMIN is defined once, in the crypto-payments section below
# (an earlier duplicate here was removed; the later definition wins).
MSG_PRECHECKOUT_FAIL = (
    "\u26a0\ufe0f This order can't be paid: it may be missing, already paid, "
    "or the amount changed. Please try again."
)
MSG_RECEIPT = (
    "\U0001f9fe <b>Order #{oid}</b>\n\n"
    "{lines}\n\n"
    "{totals}\n\n"
    "Paid via {method}\n"
    "{roadmap}"
)
MSG_ADMIN_FULFILL_FAILED = (
    "\u274c <b>Fulfillment failed</b> for paid order #{oid}: {note}\n"
    "Manual refund or replacement may be needed."
)

# ----------------------------------------------------------------- orders ---
MSG_ORDERS_EMPTY = (
    "\U0001f4e6 <b>No orders yet.</b>\n"
    "Your order history will appear here."
)
MSG_ORDERS_TITLE = "\U0001f4e6 <b>My Orders</b>\nTap an order for details and live tracking."
MSG_ORDER_LINE = "\U0001f9fe #{oid} \u2014 {total} \u2014 {status}"
MSG_ORDER_DETAIL = (
    "\U0001f9fe <b>Order #{oid}</b>\n\n"
    "{lines}\n\n"
    "{totals}\n\n"
    "{payment}\n"
    "{delivery}\n\n"
    "{roadmap}"
)
MSG_STATUS_ROADMAP = "\U0001f4cd <b>Status</b>\n{roadmap}"
MSG_ROADMAP_DONE = "\u2705 {label}"
MSG_ROADMAP_TODO = "\u25fb {label}"
MSG_ROADMAP_CANCELLED = "\u274c Cancelled"
MSG_ORDER_NOTIFIED = "\U0001f4e6 Order #{oid} status: <b>{status}</b>"
MSG_REORDER_DONE = "\U0001f501 Items added back to your cart \u2713"

ORDER_STATUSES = ["pending", "confirmed", "preparing", "shipped", "delivered", "cancelled"]
STATUS_LABEL = {
    "pending": "\u23f3 Pending",
    "confirmed": "\u2705 Confirmed",
    "preparing": "\U0001f4e6 Preparing",
    "shipped": "\U0001f69a Shipped",
    "delivered": "\U0001f3c1 Delivered",
    "cancelled": "\u274c Cancelled",
}
STATUS_EMOJI = {
    "pending": "\u23f3", "confirmed": "\u2705", "preparing": "\U0001f4e6",
    "shipped": "\U0001f69a", "delivered": "\U0001f3c1", "cancelled": "\u274c",
}

# ---------------------------------------------------------------- profile ---
MSG_PROFILE = (
    "\U0001f464 <b>My Profile</b>\n\n"
    "\U0001f4cc Name: {name}\n"
    "\U0001f194 ID: <code>{tg_id}</code>\n"
    "\U0001f4e6 Orders: {orders}\n"
    "\U0001f4b0 Total spent: {spent}\n"
    "\U0001f465 Referral earnings: {earnings}\n"
    "\U0001f4b3 Balance: {balance}"
)
MSG_BALANCE = (
    "\U0001f4b3 <b>My Balance</b>\n\n"
    "Current balance: <b>{balance}</b>\n\n"
    "Top up to buy instantly without checkout."
)
MSG_BALANCE_TOPUP = (
    "\U0001f4b3 <b>Top Up Balance</b>\n\n"
    "Choose an amount.\n"
    "\U0001f381 Get a 5% bonus on every deposit."
)
MSG_BALANCE_INVOICE_CREATING = "Creating invoice..."
MSG_BALANCE_TOPUP_MANUAL = (
    "\U0001f4b3 <b>Top Up</b>\n\n"
    "Contact support to top up your balance."
)
MSG_BALANCE_INSUFFICIENT = (
    "\U0001f4b3 Insufficient balance. Please top up first."
)
MSG_BALANCE_CUSTOM_PROMPT = (
    "\u270f\ufe0f <b>Custom amount</b>\n\n"
    "Enter the amount in USD (minimum $1)."
)
MSG_BALANCE_CUSTOM_TOO_SMALL = (
    "\u274c Minimum top-up is <b>$1</b>. Please enter $1 or more."
)
MSG_BALANCE_CUSTOM_INVALID = (
    "\u274c That doesn't look like an amount. Type a number like <b>5</b> or <b>5.50</b>."
)
BTN_CONTINUE_TO_PAYMENT = "\U0001f4b3 Continue to Payment"
MSG_BALANCE_ORDER_PLACED = (
    "\u2705 <b>Order #{oid} confirmed!</b>\n"
    "Paid with balance.\n"
    "Remaining balance: <b>{balance}</b>"
    "{fulfillment}"
)
MSG_TOPUP_METHOD = "\U0001f4b3 <b>Top Up {amount}</b>\n\nHow would you like to pay?"
MSG_TOPUP_CREDITED = ("\u2705 <b>Balance topped up!</b>\n\nAdded: <b>{amount}</b>{bonus_line}\n"
                      "New balance: <b>{balance}</b>")
MSG_TOPUP_INVOICE_CREATING = "Creating your invoice\u2026"
MSG_PURCHASES_EMPTY = (
    "\U0001f511 <b>No digital purchases yet.</b>\n"
    "License keys from your orders will appear here."
)
MSG_PURCHASES_TITLE = "\U0001f511 <b>My Purchases</b>\n\nTap an order to view its keys again."
MSG_PURCHASE_BLOCK = "\U0001f9fe <b>#{oid}</b>"
MSG_PURCHASE_KEY_LINE = "\u2022 <b>{name}</b>:\n<code>{value}</code>"
MSG_WISHLIST_EMPTY = (
    "\u2764\ufe0f <b>Wishlist is empty.</b>\n"
    "Tap \U0001f90d on any product to save it here."
)
MSG_WISHLIST_TITLE = "\u2764\ufe0f <b>My Wishlist</b>"
MSG_REFERRAL = (
    "\U0001f465 <b>Referral Program</b>\n\n"
    "Share your link \u2014 when a friend places their first paid order, "
    "you earn <b>{percent}%</b> of the order total.\n\n"
    "\U0001f517 Your link:\n{link}\n\n"
    "\U0001f465 Friends joined: <b>{count}</b>\n"
    "\U0001f4b0 Earned: <b>{earned}</b>"
)
MSG_REFERRAL_CREDIT = (
    "\U0001f465 <b>Referral reward!</b>\n\n"
    "+{amount} for {name}'s first order. Keep sharing!"
)
MSG_REDEEM_ASK = "\U0001f39f\ufe0f <b>Redeem a promo code</b>\n\nSend the code as a message."
MSG_REDEEM_SAVED = "\u2705 Code <b>{code}</b> saved \u2014 it will apply at checkout."
MSG_HISTORY_EMPTY = "\U0001f4cb <b>No history yet.</b>"

# ------------------------------------------------------------------ admin ---
MSG_ADMIN_DENIED = "\U0001f6d4\ufe0f Admin access required."
MSG_ADMIN_CONSOLE = (
    "\U0001f6e0\ufe0f <b>Admin Console</b>\n"
    "{maintenance_banner}"
    "Choose a section:"
)
MSG_MAINT_BANNER = "\n\U0001f527 <b>MAINTENANCE MODE IS ON</b>\n"
MSG_ADMIN_STATS = (
    "\U0001f4ca <b>Dashboard</b>\n\n"
    "\U0001f465 Users: <b>{total}</b> (+{new24} in 24h, {blocked} blocked)\n"
    "\U0001f4b0 Revenue (14 days): <b>{rev14}</b> ({orders14} orders)\n"
    "\U0001f4b0 Total revenue: <b>{rev_total}</b>\n"
    "\U0001f9fe Average order: <b>{avg_check}</b>\n\n"
    "<b>Orders by status</b>\n{by_status}\n\n"
    "<b>Top products</b>\n{top}"
)
MSG_CAT_LIST = "\U0001f4e6 <b>Categories</b>\n\n{lines}\n\nTap a category to manage it."
MSG_CAT_LINE = "{emoji} <b>{name}</b> \u2014 {n} product(s)"
MSG_CAT_ASK_NAME = "\u2712\ufe0f Send the <b>new category name</b> (you can start with an emoji):"
MSG_CAT_CREATED = "\u2705 Category <b>{name}</b> created."
MSG_CAT_RENAMED = "\u2705 Category renamed to <b>{name}</b>."
MSG_CAT_DELETED = "\U0001f5d1\ufe0f Category deleted."
MSG_CAT_DELETE_GUARD = (
    "\u26a0\ufe0f This category has <b>{n}</b> product(s).\n"
    "Delete the product(s) first, then the category."
)
MSG_CAT_ASK_RENAME = "\u2712\ufe0f Send the <b>new name</b> for \u201c{name}\u201d:"
MSG_PROD_WIZ_NAME = "\u2712\ufe0f <b>New product \u2014 step 1/7</b>\n\nSend the product <b>name</b>:"
MSG_PROD_WIZ_DESC = "\u2712\ufe0f <b>Step 2/7 \u2014 description</b>\n\nSend a short description (or \u201c-\u201d to skip):"
MSG_PROD_WIZ_PHOTO = "\U0001f4f7 <b>Step 3/7 \u2014 photo</b>\n\nSend a product photo (or \u201c-\u201d to skip):"
MSG_PROD_WIZ_PRICE = "\U0001f4b0 <b>Step 4/7 \u2014 price</b>\n\nSend the price in {currency} (e.g. 19.99):"
MSG_PROD_WIZ_KIND = "\U0001f4e6 <b>Step 5/7 \u2014 product type</b>\n\nChoose a product type:"
MSG_PROD_WIZ_STOCK = "\U0001f4e6 <b>Step 6/7 \u2014 stock</b>\n\nSend the quantity (\u201c-1\u201d = infinite):"
MSG_PROD_WIZ_VALUES = (
    "\U0001f511 <b>Step 6/7 \u2014 license keys</b>\n\n"
    "Send keys, one per line (or \u201c-\u201d for unlimited digital stock):"
)
MSG_PROD_WIZ_CATEGORY = "\U0001f4e6 <b>Step 7/7 \u2014 category</b>\n\nChoose a category:"
MSG_PROD_WIZ_CONFIRM = "\u2705 <b>Confirm new product</b>\n\n{summary}"
MSG_PROD_CREATED = "\u2705 Product <b>{name}</b> created."
MSG_PROD_LINE_ADMIN = "#{id} <b>{name}</b> \u2014 {price} {state}"
MSG_PROD_STATE_ON = "\u2705 active"
MSG_PROD_STATE_OFF = "\u23f8\ufe0f Paused"
MSG_PROD_ASK_PRICE = "\U0001f4b0 Send the <b>new price</b> in {currency} for \u201c{name}\u201d:"
MSG_PROD_PRICE_SET = "\u2705 Price updated: <b>{price}</b>."
MSG_PROD_ASK_STOCK = "\U0001f4e6 Send the <b>new stock</b> for \u201c{name}\u201d (\u201c-1\u201d = infinite):"
MSG_PROD_STOCK_SET = "\u2705 Stock updated."
MSG_PROD_ASK_VALUES = "\U0001f511 Send license keys, <b>one per line</b>:"
MSG_PROD_VALUES_ADDED = "\u2705 Added <b>{n}</b> key(s) ({total} unused total)."
MSG_PROD_DELETE_ASK = "\U0001f5d1\ufe0f Delete product <b>{name}</b> permanently?"
MSG_ORDERS_ADMIN_TITLE = "\U0001f9fe <b>Orders</b> \u2014 filter by status:"
MSG_ORDER_ADMIN_LINE = "#{oid} \u2014 {total} \u2014 {name}"
MSG_ORDER_ADMIN_DETAIL = (
    "\U0001f9fe <b>Order #{oid}</b> \u2014 {status}\n\n"
    "{lines}\n\n"
    "{totals}\n\n"
    "\U0001f464 {name} (id <code>{tg_id}</code>)\n"
    "\U0001f4de {phone}\n"
    "\U0001f4cd {address}\n"
    "\U0001f4b3 {payment} \u00b7 \U0001f69a {delivery}"
)
MSG_USER_SEARCH_ASK = "\U0001f50d Send a <b>Telegram user ID</b> to look up:"
MSG_USER_CARD = (
    "\U0001f464 <b>{name}</b> (id <code>{tg_id}</code>)\n\n"
    "\U0001f4e6 Orders: {orders} \u00b7 \U0001f4b0 Spent: {spent}\n"
    "\U0001f465 Referred by: {ref}\n"
    "\U0001f6e1\ufe0f Role: {role}\n"
    "\U0001f6d4\ufe0f Blocked: {blocked}"
)
MSG_USER_NOT_FOUND = "\u26a0\ufe0f User not found."
MSG_ROLE_PICK = "\U0001f6e1\ufe0f <b>Role for {name}</b>\n\nToggle permission bits:"
MSG_ROLE_SAVED = "\u2705 Role updated."
MSG_PROMO_LIST = "\U0001f39f\ufe0f <b>Promo codes</b>"
MSG_PROMO_LINE = "<code>{code}</code> \u2014 {desc} \u00b7 {uses} \u00b7 {state}"
MSG_PROMO_WIZ_CODE = "\u2712\ufe0f <b>New promo \u2014 step 1/5</b>\n\nSend the code (e.g. SAVE10):"
MSG_PROMO_WIZ_KIND = "\U0001f39f\ufe0f <b>Step 2/5 \u2014 discount type</b>"
MSG_PROMO_WIZ_VALUE = "\u2712\ufe0f <b>Step 3/5 \u2014 value</b>\n\nSend {hint}:"
MSG_PROMO_WIZ_VALUE_PCT = "a percent from 1 to 90"
MSG_PROMO_WIZ_VALUE_FIXED = "a fixed amount in your shop currency (e.g. 5.00)"
MSG_PROMO_WIZ_MAXUSES = "\u2712\ufe0f <b>Step 4/5 \u2014 max uses</b>\n\nSend a number (\u201c0\u201d = unlimited):"
MSG_PROMO_WIZ_EXPIRY = (
    "\u2712\ufe0f <b>Step 5/5 \u2014 expiry</b>\n\n"
    "Send <code>YYYY-MM-DD</code> or \u201c-\u201d for no expiry:"
)
MSG_PROMO_CREATED = "\u2705 Promo <code>{code}</code> created."
MSG_PROMO_DELETED = "\U0001f5d1\ufe0f Promo deleted."
MSG_PROMO_ASK_DELETE = "\U0001f5d1\ufe0f Delete promo <code>{code}</code>?"
MSG_BROADCAST_ASK = (
    "\U0001f4e2 <b>Broadcast</b>\n\n"
    "Send the message to broadcast (text and/or photo)."
)
MSG_BROADCAST_PREVIEW = "\U0001f4e2 <b>Preview</b> \u2014 will go to <b>{n}</b> user(s):"
MSG_BROADCAST_PROGRESS = "\U0001f4e2 <b>Broadcasting\u2026</b>\n\nSent: <b>{done}/{total}</b>\nErrors: {errors}"
MSG_BROADCAST_DONE = "\U0001f4e2 <b>Broadcast finished</b>\n\nSent: <b>{done}</b>\nErrors: {errors}"
MSG_BROADCAST_STOPPED = "\u23f9\ufe0f Broadcast stopped at {done}/{total}."
MSG_MAINT_ASK = "\U0001f527 <b>Maintenance mode</b>\n\nWhen ON, regular users see a maintenance notice."
MSG_WIZARD_CANCELLED = "\u274c Cancelled \u2014 nothing was changed."

# ------------------------------------------------------- crypto payments ---
MSG_CO_PAYMENT_DIRECT = (
    "\U0001fa99 <b>Direct Crypto</b>\n\n"
    "Pick a chain. You'll get a fresh address \u2014 "
    "0% fees, you pay only the network fee to miners."
)

BTN_CRYPTOBOT_PAY = "\U0001f48e Pay in CryptoBot"
BTN_DEPOSIT_CHECK = "\U0001f504 Check My Deposit"
BTN_DIRECT_CRYPTO = "\U0001fa99 Direct Crypto (0% fees)"
BTN_NEW_PAYMENT = "\U0001f501 New Payment"
BTN_OTHER_METHODS = "\U0001f4b3 Other Payment Methods"
BTN_CRYPTO_PANEL = "\U0001fa99 Crypto"
BTN_CHAIN_TOGGLE = "{state} {label}"
BTN_CRYO_PENDING = "\u23f3 Pending ({n})"
BTN_CRYO_LATE = "\u23f0 Late ({n})"
BTN_CRYO_UNDERPAID = "\u26a0\ufe0f Underpaid ({n})"
BTN_CRYO_CHAINS = "\U0001f50c Chains"
BTN_CRYO_CONFIRM_MANUAL = "\u2705 Confirm Manually"
BTN_CRYO_REJECT = "\u274c Reject"

MSG_CRYPTOBOT_CREATED = (
    "<b>\U0001f48e CryptoBot Invoice</b>\n\n"
    "Order total: <b>{total}</b>\n"
    "CryptoBot fee (3%): <b>{fee}</b>\n"
    "<b>Invoice amount: {gross} USDT (CryptoBot may convert to another asset).</b>\n\n"
    "1. Tap below to pay in the CryptoBot app.\n"
    "2. We detect your payment automatically \u2014 no need to tap anything. You'll be notified here."
)
MSG_CRYPTOBOT_WAIT = "\u23f3 Waiting for CryptoBot payment\u2026"

MSG_DEPOSIT_SCREEN = (
    "<b>\U0001fa99 Direct Crypto Deposit</b>\n\n"
    "Send exactly <b>{amount}</b> to this address:\n"
    "<code>{address}</code>\n"
    "{memo_line}\n"
    "Order total: <b>{total}</b>\n"
    "Rate locked for 5 minutes.\n"
    "You pay only the network fee to miners \u2014 no extra charges.\n\n"
    "Usually credited within a few minutes after {confs} network confirmation(s).\n"
    "\u23f3 This address is reserved for you until <b>{ttl}</b>."
)
MSG_DEPOSIT_MEMO_LINE = "Memo (required): <code>{memo}</code>\n"

MSG_CRYPTO_STILL_UNPAID = (
    "\u23f3 Not detected yet.\n\n"
    "Crypto deposits need a few minutes and network confirmations. "
    "If you just sent it, give it a moment and check again."
)
MSG_CRYPTO_EXPIRED = (
    "\u231b <b>This payment window expired.</b>\n\n"
    "Nothing was charged. Start a new payment whenever you're ready."
)
MSG_CRYPTO_UNDERPAID = (
    "\u26a0\ufe0f <b>Partial payment detected.</b>\n\n"
    "Received: <b>{seen}</b> of <b>{expected}</b>.\n"
    "Please send the remaining <b>{remaining}</b> to the same address:\n"
    "<code>{address}</code>"
)
MSG_CRYPTO_PROVIDER_DOWN = (
    "\u26a0\ufe0f Payment provider is unreachable.\n\n"
    "Please try again shortly, or choose another method."
)
MSG_CRYPTO_PAID = (
    "\u2705 <b>Payment confirmed!</b>\n\n"
    "\U0001f9fe Order <b>#{oid}</b>\n"
    "{lines}\n\n"
    "Total paid: <b>{total}</b> via {provider}."
    "{digital}\n\n"
    "{roadmap}\n\n"
    "Questions? Tap \U0001f198 Support below."
)
MSG_CRYPTO_ADMIN_PAID = (
    "\U0001f48e <b>Crypto payment received</b>\n\n"
    "Order <b>#{oid}</b> \u00b7 {provider}\n"
    "Tx: <code>{tx}</code>\n"
    "Total: <b>{total}</b>"
)
MSG_CRYPTO_ADMIN_LATE = (
    "\u23f0 <b>Late crypto deposit needs review</b>\n\n"
    "Order <b>#{oid}</b> \u00b7 {chain}\n"
    "Tx: <code>{tx}</code>\n"
    "The payment window had expired \u2014 confirm or reject manually."
)
MSG_CRYPTO_ADMIN_DEPOSIT = (
    "\U0001fa99 <b>New crypto deposit</b>\n\n"
    "Order <b>#{oid}</b> \u00b7 {chain}\n"
    "Address: <code>{address}</code>\n"
    "Expected: <b>{amount}</b>"
)
MSG_CRYPTO_DEPOSITS_TITLE = "\U0001fa99 <b>Crypto deposits</b> \u2014 {view} ({n})"
MSG_CRYPTO_DEPOSITS_EMPTY = "Nothing here right now."
MSG_COD_ADMIN = (
    "\U0001f4b5 <b>New {kind} order</b>\n\n"
    "\U0001f9fe Order <b>#{oid}</b>\n"
    "{lines}\n\n"
    "\U0001f464 {name} (id <code>{tg_id}</code>)\n"
    "\U0001f4de {phone}\n"
    "\U0001f4cd {address}\n\n"
    "Total: <b>{total}</b>"
)

# Admin crypto panel
MSG_CRYPTO_PANEL = (
    "\U0001fa99 <b>Crypto Payments</b>\n\n"
    "Pending deposits: <b>{pending}</b>\n"
    "Late (need review): <b>{late}</b>\n"
    "Underpaid: <b>{underpaid}</b>"
)
MSG_CRYPTO_DEPOSIT_ROW = (
    "#{id} \u00b7 {chain} \u00b7 <code>{address}</code>\n"
    "Expected <b>{amount}</b> \u00b7 order #{oid} \u00b7 {status}"
)
MSG_CRYPTO_CHAINS = "\U0001fa99 <b>Chain toggles</b>\n\nTap to enable or disable each direct-crypto chain."
TOAST_CRYPTO_CONFIRMED = "Deposit confirmed \u2014 order paid!"
TOAST_CRYPTO_REJECTED = "Deposit rejected"
TOAST_CHAIN_ON = "{chain} enabled"
TOAST_CHAIN_OFF = "{chain} disabled"

# Fee transparency (shown on the payment step).
MSG_FEE_NOTE_CRYPTOBOT = (
    "\u2139\ufe0f CryptoBot adds a 3% processing fee \u2014 added to the total above. "
    "Direct crypto has 0% fees: you pay only the network fee to miners."
)

# ------------------------------------------------------------- mini app ---
BTN_OPEN_STORE = "\U0001f6cd\ufe0f Open Store"
MSG_MINIAPP_CART_IMPORTED = (
    "\u2705 <b>Store cart imported!</b>\n\n"
    "{lines}\n\n"
    "Total: <b>{total}</b>\n\n"
    "Continue to checkout below."
)
MSG_MINIAPP_BAD_PAYLOAD = (
    "\u26a0\ufe0f Couldn't read the store cart \u2014 please try again "
    "or shop directly here."
)

# ------------------------------------------------------------------ legal ---
# Shop policies. Plain-language summaries, not legal advice. Full text lives
# behind /terms, /privacy and /refund.

MSG_TERMS = (
    "<b>\U0001f4dc Terms of Service</b>\n\n"
    "<b>1. What we sell.</b> Nova Shop sells digital goods (license keys, codes, "
    "downloads) and physical goods through this Telegram bot and its Mini App storefront.\n\n"
    "<b>2. Orders.</b> Your order is formed when you tap \u201cContinue to Payment\u201d and payment is "
    "confirmed. Prices are shown in USD; crypto amounts are calculated at the rate "
    "locked when your payment is created and are valid for the payment window shown "
    "on the deposit screen.\n\n"
    "<b>3. Fees.</b> The price you see is the price you pay, except CryptoBot payments, "
    "which add a 3% processing fee \u2014 always shown before you pay. Direct crypto "
    "payments have 0% shop fees; you only pay the network (miner) fee to send.\n\n"
    "<b>4. Payment finality.</b> Telegram Stars payments are final and non-refundable "
    "under Telegram's own rules \u2014 we cannot reverse them. On-chain crypto transfers "
    "(BTC, ETH, TRX, TON) are irreversible once confirmed on the network. Card payments "
    "follow your card issuer's dispute process.\n\n"
    "<b>5. Delivery.</b> Digital goods are delivered in this chat instantly after payment "
    "confirmation. Physical goods ship within 24 hours of confirmation; delivery times "
    "after shipping depend on the courier.\n\n"
    "<b>6. Changes.</b> We may update these terms; material changes are announced in the "
    "bot at least 30 days before they take effect. Continued use after that means you "
    "accept the new terms.\n\n"
    "Questions: /support"
)

MSG_PRIVACY = (
    "<b>\U0001f512 Privacy Policy</b>\n\n"
    "<b>What we collect.</b> To run your orders we store: your Telegram ID and display "
    "name, phone number and delivery address (only if you place a delivery order), "
    "your cart, order history, and support messages. Payment details are processed by "
    "Telegram, CryptoBot, or the blockchain \u2014 we never see or store card numbers.\n\n"
    "<b>Why.</b> Solely to fulfil orders, prevent fraud, and provide support. Nothing else.\n\n"
    "<b>Sharing.</b> We do not sell or rent your data. It is shared only where needed to "
    "complete your order (e.g. a courier for physical delivery) or when required by law.\n\n"
    "<b>Retention.</b> Order records are kept as long as needed for accounting and "
    "disputes, then deleted on request where the law allows.\n\n"
    "<b>Your rights.</b> Ask for a copy of your data or for deletion any time via "
    "/support with the subject \u201cdata request\u201d \u2014 we aim to reply as soon as possible."
)

MSG_REFUND = (
    "<b>\U0001f4b8 Refund Policy</b>\n\n"
    "<b>Digital goods.</b> Final once delivered \u2014 except when the key or code doesn't "
    "work and we can't replace it: then you get a full refund or a working replacement, "
    "your choice.\n\n"
    "<b>Physical goods.</b> Full refund if you cancel before shipping. Arrived damaged or "
    "wrong? Tell us within 7 days.\n\n"
    "<b>How to claim.</b> Open /support, choose your order, describe the problem. We "
    "review every claim within 3 days and pay approved refunds within 10 days to the "
    "original payment method where possible.\n\n"
    "<b>Not refundable.</b> Telegram Stars (Telegram's rules, not ours) and confirmed "
    "on-chain crypto transfers cannot be reversed \u2014 double-check amounts before sending."
)

# ------------------------------------------------------- support tickets ---
BTN_NEW_REQUEST = "\u2709\ufe0f New request"
BTN_CLOSE_TICKET = "\U0001f512 Close ticket"
MSG_SUPPORT_TICKETS_TITLE = "\U0001f4ac <b>Support</b>\n\nWe aim to reply as soon as possible."
MSG_SUPPORT_NO_TICKETS = "You have no open requests."
MSG_SUPPORT_TICKET_ROW = "#{id} \u00b7 {subject} \u00b7 {status}"
MSG_SUPPORT_TICKET_OPEN = (
    "\u2705 <b>Request #{id} opened.</b>\n\n"
    "Our team aims to reply as soon as possible. "
    "We'll message you here."
)
MSG_SUPPORT_TICKET_DETAIL = (
    "\U0001f4ac <b>Request #{id}</b> \u2014 {status}\n\n"
    "{subject}\n\n"
    "Opened {created}."
)
TOAST_TICKET_CLOSED = "Request closed"
MSG_SUPPORT_TICKET_ADMIN = (
    "\U0001f4e9 <b>Support request #{ticket_id}</b> from {name} "
    "(id <code>{tg_id}</code>):\n\n{text}"
)

# ------------------------------------------------------- order cancel ---
BTN_CANCEL_ORDER = "\u274c Cancel order"
BTN_YES_CANCEL = "\u274c Yes, cancel it"
BTN_KEEP_ORDER = "\u21a9\ufe0f Keep order"
MSG_ORDER_CANCEL_ASK = (
    "\u26a0\ufe0f <b>Cancel order #{oid}?</b>\n\n"
    "This can't be undone. No payment has been taken for this order."
)
MSG_ORDER_CANCELLED = (
    "\u2705 Order #{oid} is cancelled. Nothing was charged."
)
TOAST_ORDER_CANCELLED = "Order cancelled"
MSG_ORDER_CANCEL_DENIED = (
    "\u26a0\ufe0f This order can no longer be cancelled "
    "\u2014 please contact /support."
)

# ------------------------------------------------------- admin guards ---
MSG_ADMIN_CONFIRM_UNPAID = (
    "\u26a0\ufe0f No payment recorded for this order. "
    "Confirming would release the goods for free \u2014 action blocked."
)
MSG_ADMIN_PAID_AFTER_CANCEL = (
    "\u26a0\ufe0f Payment received for order #{oid}, but the order was "
    "cancelled \u2014 goods NOT delivered. Handle the refund manually."
)

# ------------------------------------------------- crypto rail buttons ---
# Labels for the payment-method buttons built in crypto_payments.payment_rails().
# 💎 is reserved for CryptoBot per the emoji lexicon (TON uses 🔷).
BTN_CRYPTOBOT_RAIL = "\U0001f48e CryptoBot \u2014 {total} (+{fee_pct}% fee)"
