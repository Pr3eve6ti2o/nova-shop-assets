# Nova Shop Bot — EXTREME EDITION Spec (delta on top of SPEC.md)

## 0. Goal
Add (a) multi-rail crypto payments with automatic fallback, (b) a Telegram Mini App
storefront (progressive enhancement), (c) professional copy polish — all FREE tiers only,
English only. Existing v1 behavior must keep working; nothing here may break it.

## 1. Payment fallback chain (order matters — friction ascending)
At checkout the payment step lists ONLY configured rails, in this order, each with the
real amount on the button:
1. `⭐ Pay with Stars (N ⭐)` — always on.
2. `💎 CryptoBot — $X.XX (+3% fee)` — if CRYPTOBOT_TOKEN set. Fee labeled on the button
   (divine-panel pattern). Default asset USDT.
3. `💳 Card — $X.XX` — if PAYMENTS_PROVIDER_TOKEN set (existing).
4. `🪙 Direct Crypto` → sub-menu of configured chains — if any self-custody chain configured:
   `₿ BTC`, `Ξ ETH / USDT-ERC20`, `💎 TON`, `🔴 USDT-TRC20`. Zero gateway fees.
5. `💵 Cash on Delivery` / `🤝 Pay on Pickup` — existing.

Failure UX (asyny-big named states — implement exactly these user-facing states):
- `still_unpaid` → "Not detected yet. [🔄 Check Again]"
- `expired_unpaid` → "This payment window expired. [🔁 New Payment] [🏠 Menu]"
- `provider_unavailable` → "Payment provider is unreachable. Please press again later or choose another method. [💳 Other Methods]"
- Never invent a payment. Every failure names the next action.

## 2. CryptoBot rail (primary free crypto rail)
- Raw aiohttp calls (no new SDK dep): base `https://pay.crypt.bot/api`
  (testnet `https://testnet-pay.crypt.bot/api` when CRYPTOBOT_TESTNET=1),
  header `Crypto-Pay-API-Token: <token>`.
- `createInvoice(asset=USDT, amount=<usd total + 3% fee, rounded up to cents>,
  description=f"Nova Shop order #<id>", payload=str(order_id), expires_in=1800)` →
  store invoice_id; show user the `bot_invoice_url` button `💎 Pay in CryptoBot`
  + `🔄 I've Paid — Check` button.
- Recovery poller: every 60s, `getInvoices(invoice_ids=[pending...], status='paid')`;
  finalize newly-paid (idempotent: only if local status pending).
- HMAC webhook verification function (SHA256(token) as key over raw body) — include the
  code + docs, but webhooks stay OPTIONAL (no public URL in this deployment).
- Amounts: compute USD total → add 3% → round UP to whole cents. Show both lines:
  `Order total $X.XX` + `CryptoBot fee (3%) $Y.YY` = button amount.

## 3. Self-custody direct deposits (zero fees, xpub-only on server)
- New dep: `hdwallet` (pip) for xpub→address derivation (BTC/ETH/TRON).
- Chains & derivation (external chain, per-chain index counter in kv table
  `xpub_index_<chain>`, start at 1; index 0 reserved):
  - BTC: `m/84'/0'/0'/0/i` → bc1q… ; watch mempool.space `/address/{a}/txs`
    (fallback blockchain.info `/rawaddr/{a}`).
  - ETH/USDT-ERC20: `m/44'/60'/0'/0/i` → 0x… ; watch Blockscout
    `https://eth.blockscout.com/api/v2/addresses/{a}/token-transfers?type=ERC-20`
    filtered to USDT contract `0xdAC17F958D2e523a2206206994597C13D831ec7` (6 dec).
  - TRX/USDT-TRC20: `m/44'/195'/0'/0/i` → T… ; watch Tronscan
    `/token_trc20/transfers?contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t&relatedAddress={a}`.
  - TON: memo scheme — ONE static address (TON_DEPOSIT_ADDRESS) + unique memo
    `NOVA-<order_id>`; watch toncenter `/getTransactions?address=…`, match
    `in_msg.message == memo`. (No per-order keys needed.)
- Rates: CoinGecko free `simple/price?ids=bitcoin,ethereum,tron,the-open-network&vs_currencies=usd`,
  cached 5 min in memory; if unavailable → direct-crypto buttons hidden with log line.
- Confirmations before credit: BTC 3, ETH 12, TRON 19, TON 1.
- Tolerance: accept ≥ expected − 2% (flag `underpaid` for admin review, still fulfill?
  NO — hold as underpaid, show "send remaining X to the same address", keep TTL).
- Order TTL 45 min (`expires_at`); expiry → status `expired`, stop watching; late deposits
  go to a `late` bucket (visible in admin) for manual review — never auto-lost.
- Idempotency: `UNIQUE(chain, txid)` on crypto_deposits; poller + manual re-scan funnel
  through insert-or-ignore.
- Manual re-scan: `🔄 Check My Deposit` button (rate-limit 1 per 30s per user).
- Deposit screen: address in `<code>` block (tap-to-copy) + QR? (no QR lib — skip QR,
  address copy is enough) + chain name + exact expected amount + "usually credited
  within a few minutes after N confirmations" + TTL countdown line.
- Admin: `🪙 Crypto` panel → pending deposits list (chain, address, expected, seen tx),
  `✅ Confirm Manually` / `❌ Reject`, view late bucket, per-chain enable toggles
  (kv `crypto_<chain>_enabled`).

## 4. Background deposit watcher
- asyncio task started in app.py lifespan: every 60s sweep `crypto_deposits`
  WHERE status='pending' AND expires_at > now.
- Per chain: query free API (with fallback), match incoming txs ≥ expected−tolerance,
  check confirmations (re-query tx for confirmation count), on threshold → finalize
  (same fulfill path as other rails), notify user + admins, audit log.
- Respect rate limits: sequential per-address calls, small sleeps; mempool.space ≤10/min.
- On sweep error: log + continue (never crash the loop).

## 5. DB additions (new tables; do NOT alter v1 tables)
```sql
CREATE TABLE IF NOT EXISTS crypto_deposits(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  chain TEXT NOT NULL, address TEXT NOT NULL, derivation_index INTEGER,
  memo TEXT, expected_crypto TEXT NOT NULL, expected_usd_cents INTEGER NOT NULL,
  status TEXT DEFAULT 'pending',   -- pending|paid|expired|underpaid|late|cancelled
  txid TEXT, confirmations INTEGER DEFAULT 0, seen_amount_crypto TEXT,
  created_at TEXT, expires_at TEXT, UNIQUE(chain, txid));
CREATE TABLE IF NOT EXISTS cryptobot_invoices(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  invoice_id INTEGER UNIQUE NOT NULL, asset TEXT, amount TEXT, status TEXT DEFAULT 'active',
  created_at TEXT);
```
kv additions: `xpub_index_btc|eth|trx`, `crypto_btc_enabled` etc., `crypto_ttl_minutes=45`,
`cryptobot_fee_percent=3`.

## 6. Mini App (Option A: static + sendData — no backend needed)
- `miniapp/` static files: `index.html`, `app.js`, `styles.css`.
  Plain HTML/JS + `https://telegram.org/js/telegram-web-app.js` CDN. No build step.
- Features: theme-aware (bind `themeChanged`, use themeParams CSS vars), category chips,
  product grid (photo? catalog.json carries photo file_ids — NOT usable outside Telegram;
  so cards show name/price/rating/stock, no photos — document this), product sheet,
  cart with steppers, promo field, MainButton `CHECKOUT — $X.XX`, BackButton nav,
  haptic on add-to-cart, `sendData(JSON {items:[{id,qty}], promo})` (≤4096 bytes).
- `tools/export_catalog.py`: dumps active products/categories from SQLite → 
  `miniapp/catalog.json` (run at deploy time; document in README).
- Bot side: reply-keyboard button `🛍️ Open Store` with `web_app=WebAppInfo(url=MINIAPP_URL)`
  — ONLY if MINIAPP_URL set (progressive enhancement); handler for
  `content_types=WEB_APP_DATA`: parse, re-validate ids/qty/stock/prices server-side,
  then drop user into existing checkout-review step. Never trust amounts from payload.
- `miniapp/README.md`: free hosting (Cloudflare Pages recommended, GitHub Pages alt),
  BotFather `/newapp` steps, 4KB limit, theme notes, upgrade path to backend API
  (include `webapp_auth.py` with the exact HMAC-SHA256 initData validation algorithm
  for future use — tested with a known test vector).
- Keep classic bot 100% functional with MINIAPP_URL unset.

## 7. Copy polish (English, professional — apply across texts.py)
- `/start` (new user): bold hero (1 line: what the bot is) + blockquote 2–3 line pitch +
  italic tip + ≤4 button rows. Formula from research — no "Welcome!" walls.
- Returning user: dashboard summary ("Welcome back! 🛒 2 items in cart · 📦 1 order on the way").
- Fee transparency: CryptoBot fee labeled; "Rate via CoinGecko, refreshed every 5 min";
  lnp2pbot-style "no additional charges" line for direct crypto ("You pay only the network fee to miners").
- Help: SLA with hours ("Support replies within ~2 hours, 9:00–21:00 UTC"), refund policy
  summary, named failure states from §1.
- Receipts: itemized, order id, timestamp, payment method, "Questions? /help".
- Keep every string in texts.py. No emoji-only buttons. One leading emoji max.

## 8. Config additions (.env.example)
```
CRYPTOBOT_TOKEN=            # @CryptoBot → Crypto Pay → Create App (testnet: @CryptoTestnetBot)
CRYPTOBOT_TESTNET=0
XPUB_BTC=                   # account xpub (zpub ok) — seed stays OFFLINE
XPUB_ETH=                   # account xpub m/44'/60'/0'
XPUB_TRX=                   # account xpub m/44'/195'/0'/0'
TON_DEPOSIT_ADDRESS=        # static TON wallet for memo scheme
MINIAPP_URL=                # https://… (Cloudflare Pages) — unset = classic bot only
CRYPTO_TTL_MINUTES=45
```

## 9. Tests (extend tests/test_smoke.py — all must pass)
- HD derivation against known test vectors (use hdwallet docs vectors; assert exact addresses).
- initData HMAC validation: construct a vector with a known token, assert accept; tampered → reject.
- CryptoBot HMAC: SHA256(token)-keyed verification on a fixture body.
- Deposit matching: fixture tx lists → matcher returns paid/underpaid/none correctly.
- Promo/fallback: payment-method list builder returns correct rails for config combos.
- Mini App payload validation: oversized/unknown-id payloads rejected.
- Keep existing 4 groups green.

## 10. Non-negotiables
- aiogram 2.25.2 API. aiosqlite. English only. Money in cents (crypto amounts as
  integer base units: sats/wei/sun/nanotons — use Python ints, never floats for money).
- py_compile clean; smoke tests green in ~/workspace/nova-shop/.venv.
- Do NOT start polling with the real token (bot is LIVE via systemd — never double-poll).
- Do not touch the systemd unit or .env. Report files + test results + deviations.
