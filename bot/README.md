# Bot — Nova Shop Telegram Bot

Python 3.12 + aiogram 2.x. English-only UI, sleek minimal button layouts.

## Structure

```
bot/
├── app.py              # entrypoint, dispatcher wiring
├── config.py           # env config (no secrets in code)
├── database.py         # async SQLite (aiosqlite), atomic money ops
├── handlers/           # feature handlers
│   ├── start.py        # /start, deep links (p_<id>, ref_<code>)
│   ├── shop.py         # catalog browsing
│   ├── cart.py         # cart management
│   ├── checkout.py     # 3-screen wizard (details → payment → confirm)
│   ├── crypto.py       # direct-crypto deposit flows
│   ├── payments.py     # Stars / card payments
│   ├── miniapp.py      # Mini App sendData bridge (orders, TON Connect)
│   ├── orders.py       # order history, cancellation
│   ├── reviews.py      # ratings + reviews
│   ├── support.py      # ticketed support
│   ├── legal.py        # /terms /privacy /refund
│   ├── referrals.py    # referral program
│   ├── profile.py      # user profile
│   └── admin/          # catalog, orders, promos, users, broadcast
├── crypto_payments.py  # CryptoBot API, HD-wallet (Trust Wallet wallet-core),
│                       # chain watchers (mempool.space, Blockscout, toncenter)
├── crypto_watcher.py   # 60s background sweeps (deposits, invoices, TON pending)
├── keyboards.py        # all inline keyboards
├── texts.py            # all copy (English-only)
├── middlewares.py      # rate limiting, maintenance gate
├── payload_hooks.py    # order push to Payload CMS
├── webapp_auth.py      # initData HMAC validation (for future API routes)
└── tests/test_smoke.py # 10 smoke groups
```

## Key invariants

- **Money is integer cents.** No floats in payment math.
- **Atomic claims.** Stock decrement, promo usage, deposit claims, payment records are single-statement guards.
- **Idempotent finalize.** `record_payment` has `UNIQUE(provider, external_id)` — watcher vs manual-check races can't double-fulfill.
- **Never fulfill cancelled orders.** `finalize_crypto_order` bails with an admin alert.
- **Promo lifecycle.** Claims are released on every cancellation path (`release_order_promo`).

## Environment

Copy `.env.example` → `.env`. Never commit `.env`, `secrets/`, or `data/`.

## Running

```bash
pip install -r requirements.txt
python app.py
# systemd: see nova-shop.service
```
