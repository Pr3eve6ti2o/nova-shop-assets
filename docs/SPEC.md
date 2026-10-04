# Nova Shop Bot — Build Specification

## 1. Vision
A best-in-class, **English-only** Telegram shop bot synthesizing the best ideas from
`Serenawaifu/Shop-bot` (product photos, simple hosting), `Serenawaifu/Telegram-shop`
(digital-goods values, promo engine, bitmask RBAC, transactional money path, audit log,
broadcast with progress, rate limiting), and top-tier UX patterns from the best
open-source shop bots (edit-in-place navigation, live cart badge, quantity steppers,
amounts on CTAs, stepped checkout with edit-back, itemized invoices).

## 2. Tech stack (FIXED — do not change)
- Python 3.12, **aiogram 2.25.2** (NOT aiogram 3 — the 2.x API), SQLite via **aiosqlite**
- All user-visible strings live in `texts.py` — **English only**, zero hardcoded UI text elsewhere
- Money stored as **integer cents** everywhere; format helper `fmt_money(cents)`
- Async throughout; a single `Database` class wrapping aiosqlite with `async with` per-operation connections
- `requirements.txt` pins: `aiogram==2.25.2`, `aiosqlite`, `python-dotenv==1.0.1`
  (On Python 3.12 aiohttp<3.9 has no wheels — install note in README documents the
  `aiohttp>=3.9` workaround; do NOT pin aiohttp in requirements.txt.)
- Project root: `~/workspace/nova-shop/`

## 3. Directory layout
```
nova-shop/
  app.py                 # entrypoint: logging, middleware, startup/shutdown, polling|webhook
  config.py              # env parsing + validation (BOT_TOKEN required, ADMINS, PAYMENTS_PROVIDER_TOKEN, etc.)
  loader.py              # Bot/Dispatcher/db creation; reads https_proxy env -> Bot(proxy=...)
  texts.py               # ALL English strings (buttons, messages, templates) — the single source of copy
  keyboards.py           # all keyboard builders (inline-first; one small reply keyboard for main nav)
  database.py            # Database class (aiosqlite), schema creation, all queries
  states.py              # FSM StateGroups
  middlewares.py         # rate limiting, maintenance-mode gate, answer-callback safety
  handlers/
    __init__.py
    start.py             # /start, deep links (p_<id>, ref_<code>), main menu
    shop.py              # categories, product list (pagination), product detail, search
    cart.py              # cart view, steppers, promo, clear-confirm
    checkout.py          # wizard: contact -> delivery -> address -> payment -> confirm
    payments.py          # invoice creation, pre_checkout_query, successful_payment, Stars
    orders.py            # order history, status roadmap, reorder
    profile.py           # profile card, wishlist, reviews-made, referral info
    reviews.py           # leave-a-review flow (purchasers only)
    support.py           # /help, contact-support flow -> forwards to admins
    admin/
      __init__.py
      panel.py           # admin console (permission-filtered buttons), stats dashboard
      catalog.py         # product/category CRUD wizards
      orders.py          # order list, detail, status transitions (+ user notify)
      users.py           # lookup, balance adjust, ban/unban, role assign
      promos.py          # promo CRUD wizard
      broadcast.py       # compose -> confirm -> send with live progress
      maintenance.py     # maintenance toggle
  utils.py               # fmt_money, paginator helper, cb data helpers
  run.sh                 # continuous-run loop with backoff (executable)
  refresh-proxy-env.sh   # (provided by parent — do not recreate)
  .env.example
  tests/test_smoke.py    # plain-assert tests: config parsing, money fmt, cb data length, db CRUD
  README.md
```

## 4. Database schema (SQLite, created by `Database.create_tables()`)
```sql
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, tg_id INTEGER UNIQUE NOT NULL, name TEXT,
  phone TEXT, address TEXT, is_blocked INTEGER DEFAULT 0,
  ref_code TEXT UNIQUE, referred_by INTEGER REFERENCES users(id),
  role_mask INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, emoji TEXT DEFAULT '📦', sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, category_id INTEGER REFERENCES categories(id),
  name TEXT NOT NULL, description TEXT DEFAULT '', photo_file_id TEXT,
  price_cents INTEGER NOT NULL, old_price_cents INTEGER,
  kind TEXT NOT NULL DEFAULT 'physical',          -- 'digital' | 'physical'
  stock INTEGER NOT NULL DEFAULT -1,              -- -1 = infinite (digital)
  rating_sum INTEGER DEFAULT 0, rating_count INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS product_values(        -- digital inventory (license keys etc.)
  id INTEGER PRIMARY KEY, product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  value TEXT NOT NULL, is_used INTEGER DEFAULT 0, used_in_order INTEGER,
  UNIQUE(product_id, value));
CREATE TABLE IF NOT EXISTS cart_items(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  qty INTEGER NOT NULL, UNIQUE(user_id, product_id));
CREATE TABLE IF NOT EXISTS wishlist(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE(user_id, product_id));
CREATE TABLE IF NOT EXISTS promos(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, -- 'percent'|'fixed'
  value INTEGER NOT NULL,                      -- percent 1-90 | fixed cents
  max_uses INTEGER DEFAULT 0, used_count INTEGER DEFAULT 0,
  expires_at TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS promo_usages(promo_id INTEGER, user_id INTEGER,
  used_at TEXT, UNIQUE(promo_id, user_id));
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',      -- pending|confirmed|preparing|shipped|delivered|cancelled
  subtotal_cents INTEGER, discount_cents INTEGER DEFAULT 0, total_cents INTEGER,
  payment_method TEXT,                          -- 'card'|'stars'|'cod'
  delivery_kind TEXT,                           -- 'delivery'|'pickup'
  address TEXT, phone TEXT, promo_code TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS order_items(
  order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER, name TEXT, qty INTEGER, price_cents INTEGER, delivered_value TEXT);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY, provider TEXT NOT NULL,      -- 'telegram'|'stars'
  external_id TEXT NOT NULL, user_id INTEGER, order_id INTEGER,
  amount_cents INTEGER, currency TEXT, status TEXT DEFAULT 'pending', -- pending|paid|failed
  created_at TEXT, UNIQUE(provider, external_id));
CREATE TABLE IF NOT EXISTS reviews(
  user_id INTEGER, product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT, created_at TEXT,
  UNIQUE(user_id, product_id));
CREATE TABLE IF NOT EXISTS referral_earnings(
  id INTEGER PRIMARY KEY, referrer_id INTEGER, referee_id INTEGER,
  order_id INTEGER UNIQUE, amount_cents INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, ts TEXT, actor_tg_id INTEGER, action TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);  -- maintenance_mode, referral_percent
```
Seed on first run: `kv('maintenance_mode','0')`, `kv('referral_percent','5')`.

## 5. Permission model (bitmask RBAC, from Telegram-shop)
Bits: `1=STATS, 2=CATALOG, 4=ORDERS, 8=USERS, 16=BROADCAST, 32=PROMOS, 64=MAINTENANCE`.
- `config.ADMINS` (tg ids) get mask `127` (all) at first /start.
- Admin console renders ONLY buttons whose bit the user holds. Every admin handler re-checks the bit.
- `IsAdmin(bit)` filter.

## 6. Global UX rules (non-negotiable)
1. **Edit in place**: category/product/cart/checkout navigation rewrites ONE message
   (`edit_text`/`edit_caption`/`edit_media`). New messages ONLY for: order placed, payment
   success/failure, admin notifications, broadcast.
2. **Every callback query is answered**: navigation → empty ack; confirmations → toast
   (`show_alert=False`); real errors → alert (`show_alert=True`).
3. **Back/Home everywhere**: last row `◀️ Back` (exactly one level up); `🏠 Menu` on any
   screen 2+ levels deep. Breadcrumb in header: `🛍️ Shop › Sneakers`.
4. **Callback data < 64 bytes**: short integer ids only, e.g. `cat:3:0`, `p:42`, `pa:42:+`.
   Never put names/prices in callback data — re-read from DB.
5. **Confirm destructive actions**: clear cart / cancel order / delete product → confirm screen,
   safe option first.
6. **Designed empty states with CTA**: never a bare "empty".
7. **One leading emoji per button**, never emoji-only; toggles encode state (`✅`/`⬜`).
8. **Amounts on CTAs**: `🛒 Add to Cart — $12.99`, `📦 Checkout — $45.97`,
   `⭐ Pay with Stars (100 ⭐)`.
9. **Rate limiting middleware**: 30 actions/min/user global; payment attempts 5/min; admin bypass.
10. **Maintenance mode**: non-admins get a notice; admins see a banner row in console.


## 7. Screens & flows (exact buttons; ALL copy must come from texts.py)

### 7.1 Start / main menu
- `/start` (deep links: `p_<product_id>` → product detail; `ref_<ref_code>` → attribute referral,
  self-referral blocked; unknown → normal menu). Registers user if new (generates ref_code).
- Welcome message: hero line + 2-line value prop (from texts.py).
- Persistent **reply keyboard** (main nav only): row1 `🛍️ Shop` `🔍 Search`; row2 `🛒 Cart (N)` `📦 My Orders`; row3 `👤 Profile` `❓ Help`. Cart count live.
- Inline **🏠 Menu** button returns here by EDITING the current message.

### 7.2 Shop: categories → products → detail
- Categories: 2-column grid `emoji + name`; footer `🔍 Search`, `🏠 Menu`.
- Product list (per category): one compact row per product `Name — $X.XX` (+`⭐4.5` if rated);
  6 per page; nav row `[◀️ Prev] [2/8] [Next ▶️]` (hide dead ends; counter button = noop).
  Header breadcrumb `🛍️ Shop › {Category}`. Empty: "Nothing here yet." + `◀️ Back`.
- Product detail (photo message, edit media/caption in place):
  Caption: **bold name**, description (≤2 lines), `💰 Price: $X.XX` (strikethrough old price
  if `old_price_cents`), `📦 In stock: N` or `♾️ Digital delivery`, `⭐ 4.5 (12 reviews)`.
  Buttons: `[➖] [1] [➕]` (stepper; ➖ at 1 = noop toast), `🛒 Add to Cart — $X.XX` (toast
  "Added to cart ✓", stays on page, cart badge updates), `⚡ Buy Now` (adds 1, jumps to
  checkout confirm), `🤍 Add to Wishlist` ⇄ `❤️ In Wishlist`, `⭐ Reviews (12)` →
  review list + `✍️ Leave a Review` (purchasers only; else toast "Buy it first to review"),
  `◀️ Back` `🏠 Menu`.
- Reviews screen: list `⭐⭐⭐⭐⭐ — text (name, date)`; rating picker row of 5 buttons
  `⭐`…`⭐⭐⭐⭐⭐` → optional text step (skip button) → saved → toast.
- Search: `🔍 Search` → ForceReply "Type product name…" → paginated results; empty state
  `No results for "xyz".` + `🔄 Clear`.

### 7.3 Cart
- One summary message (edit in place). Header `🛒 Your Cart` + `Total: $X.XX`.
- Per item row-block: `**Name** ×2 — $25.98` with `[➖][2][➕][🗑️]` beneath (2 rows per item max).
- Footer: `🎟️ Promo Code` (shows `✅ CODE −10%` + `✖️` when applied), `🗑️ Clear Cart` →
  confirm screen "Remove all N items? [Keep Them] [Yes, Clear]", `📦 Checkout — $X.XX`
  (full-width), `◀️ Continue Shopping`.
- Empty: "Your cart is empty — let's fix that." + `🛍️ Browse Catalog`.
- Stock re-check on open: drop items that went out of stock (toast which).

### 7.4 Checkout wizard (FSM, one question per step, each step has ◀️ Back)
1. Review → shows lines + total, button `➡️ Continue`.
2. Delivery: `[🚚 Delivery ✅] [🏃 Pickup ⬜]` toggle row → Continue.
3. Contact (delivery only; pickup skips to 5): explanation line + **reply-keyboard**
   `📱 Share My Phone Number` (request_contact) + `✏️ Type Manually`. Remove reply kb after.
4. Address (delivery only): `📍 Share Location` (request_location) + `✏️ Type Manually`.
5. Payment method — buttons carry amounts:
   `💳 Card — $X.XX` (Telegram Payments invoice, needs PAYMENTS_PROVIDER_TOKEN),
   `⭐ Stars — N ⭐` (XTR invoice; conversion rate in config, default e.g. $1=60⭐),
   `💵 Cash on Delivery` (only if delivery_kind=delivery; else `🤝 Pay on Pickup`).
   If provider token missing → card button hidden with admin hint in logs.
6. Promo (skippable): `🎟️ Have a Promo Code?` → ForceReply → instant validate
   (`✅ CODE applied: −10%` toast + totals re-render) / `❌ Invalid or expired` / `⏭️ Skip`.
7. Confirm: summary (items, contact, address/date, payment, totals incl. discount) +
   per-section `✏️` edit buttons jumping back to that step + `[❌ Cancel] [✅ Place Order]`.

### 7.5 Payments
- Fiat: `send_invoice` with itemized `LabeledPrice[]` (per product line, `Discount (CODE)`,
  `Delivery`), photo, `payload="order:<id>"`. `pre_checkout_query`: MUST answer ≤10s —
  verify order exists, belongs to user, status=pending, amount == server total (cents).
  Decline otherwise with clear message. `successful_payment`: idempotent
  (UNIQUE(provider, telegram_payment_charge_id)) → mark paid → fulfill → receipt message.
- Stars: same flow, currency `XTR`, single price line, no provider token.
- COD/pickup: order → `pending`, admin notified with `✅ Confirm` / `❌ Cancel` buttons.
- Fulfillment: digital → pop unused `product_values` (transaction), reveal in `<code>` blocks
  in receipt; if stock runs out mid-checkout → fail gracefully, refund path noted, admin alert.
  Physical → decrement stock, notify admins.
- Receipt message (NEW message): order id, lines, totals, payment method, status roadmap.

### 7.6 Orders & profile
- `📦 My Orders`: paginated list `🧾 #1234 — $45.97 — ✅ Delivered`; detail shows vertical
  roadmap `✅ Confirmed → 🔄 Preparing → …` + items + `⭐ Rate Items` + `🔁 Buy Again`.
- `👤 Profile`: id, balance?, orders count, referral stats; buttons: `🎁 My Purchases`
  (digital values re-viewable), `❤️ Wishlist`, `🎲 Referral Program` (link + earnings),
  `🏷️ Redeem Promo`, `📋 History`.
- Referral: `t.me/<bot>?start=ref_<code>`; on referee's FIRST paid order, credit
  `referral_percent` (kv, default 5%) to referrer → toast + earnings ledger row.
- `❓ Help`: FAQ text + `✉️ Contact Support` → FSM message → forwarded to admins with
  `💬 Reply` deep-link; admin reply routes back.

### 7.7 Admin console (`/admin` or `🎛️ Admin` — permission-filtered)
- Dashboard: users (total / new 24h / blocked), revenue 14d + total, orders by status,
  top-5 products, avg check. Buttons per held bit.
- Catalog: categories (add/rename/delete with product-count guard), products
  (wizard: name → description → photo → price → kind digital/physical → stock or values
  bulk entry → category → confirm; edit price/stock/toggle active/delete with confirm).
- Orders: filter by status (row of status buttons + counts), detail with
  `⏭️ Set: Confirmed/Preparing/Shipped/Delivered/Cancelled` → user notified each change.
- Users: search by id → card (name, orders, spent, referred) + `💰 Adjust Balance`
  (skip — no balance in v1; instead `🚫 Block/Unblock`, `🛡️ Set Role`).
- Promos: list + create wizard (code → percent|fixed → value → max uses → expiry → optional
  category → done), toggle active, delete.
- Broadcast: compose (text+photo) → preview → `🚀 Send` with live progress edits
  (sent/total, errors) honoring Telegram 429 retry_after; `⏹️ Stop`.
- Maintenance: `🔧 Maintenance: ON/OFF` toggle → non-admins get notice; banner in console.
- Every money/admin mutation writes `audit_log`.

## 8. Non-functional requirements
- `app.py`: structured logging (timestamped), global `@dp.errors_handler` (log + swallow),
  startup banner (mode, admins count, payments configured Y/N), graceful shutdown.
- `loader.py`: validate BOT_TOKEN (clear RuntimeError), `Bot(proxy=https_proxy env or None)`.
- Rate-limit middleware BEFORE handlers; maintenance gate right after.
- `pre_checkout_query` handler must be FAST (no network except DB).
- No price/amount ever taken from callback data or user input — always DB.
- `tests/test_smoke.py`: config validation, fmt_money, callback-data length audit
  (import keyboards, assert all `callback_data` literals < 64 bytes), DB round-trip
  (user→product→cart→order→payment idempotency), promo math.
- `run.sh` (executable, backoff loop), `.env.example` (BOT_TOKEN, ADMINS,
  PAYMENTS_PROVIDER_TOKEN, STARS_RATE, CURRENCY default USD, REFERRAL_PERCENT),
  `Dockerfile` (python:3.11-slim, non-root, .dockerignore), README (setup, features,
  admin guide, env table, testing).
- `py_compile` clean on all files; smoke tests must PASS in the provided venv
  (`~/workspace/shop-bot/.venv` has aiogram 2.25.2 — reuse it for tests via PYTHONPATH
  or create project venv; document choice).
