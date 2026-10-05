# Nova Shop

A complete Telegram-native e-commerce platform. One codebase runs a storefront bot, a Mini App web shop, an admin CMS, and a multi-tenant SaaS layer — all designed around a single principle: **money must never move incorrectly**.

**Live:** [@testssscbot](https://t.me/testssscbot) · [Mini App](https://muse.ai/s/nova-shop-mini-app-xim6wudxohxjxiy)

---

## What this is

Nova Shop started from a simple observation: selling inside Telegram shouldn't require duct-taping five services together. So we built one coherent system where the bot, the web storefront, the admin panel, and the payment rails all share the same data model, the same money invariants, and the same audit trail.

The result is a platform that handles the full commerce lifecycle — browsing, cart, checkout, payment across six rails, fulfillment of digital and physical goods, refunds, reviews, referrals, promos, support tickets — plus a SaaS layer that lets you spin up independent storefronts for other merchants on the same infrastructure.

---

## Repository layout

```
├── bot/                  # Telegram bot (Python 3.12, aiogram 2.x)
│   ├── handlers/         # shop, cart, checkout, crypto, payments, admin, …
│   │   └── admin/        # catalog, orders, promos, users, broadcast, panel
│   ├── saas/             # multi-tenant SaaS: tenant lifecycle, billing
│   ├── tests/            # smoke tests (10 groups)
│   ├── requirements.txt, Dockerfile, .env.example
├── miniapp/              # Telegram Mini App storefront (vanilla JS)
│   ├── app.js, styles.css, index.html   # source
│   └── dist/index.html                  # built bundle
├── admin/                # Payload CMS 3.x + Next.js (catalog, orders, users)
├── tools/                # catalog sync, bundle builder, wallet utils
├── tonconnect/           # TON Connect manifest + icon (served via jsDelivr)
├── brand/                # brand assets
└── docs/                 # architecture, security, deployment, audits
```

---

## Features

### Storefront bot
- Sleek 4-button menu (Profile, Shop, Info, Rent) — English-only, minimal taps
- 3-screen checkout wizard: cart → details → payment
- Product catalog with categories, search, filters, reviews, stock alerts
- Digital goods (license keys) and physical goods with delivery/pickup
- Wishlist, order tracking with deep links, support tickets with SLAs
- Legal pages: `/terms`, `/privacy`, `/refund`

### Payment rails (six)
| Rail | How it works |
|------|--------------|
| Telegram Stars | Native invoice → `successful_payment` webhook |
| Card | Telegram Payments provider token |
| CryptoBot | Invoice API + 60-second recovery poller, 3% fee handling |
| Direct crypto | Per-order HD-wallet deposit addresses (BTC/ETH/TRX), chain watchers |
| TON Connect | Wallet `sendTransaction` → on-chain verification |
| Cash on delivery | Physical goods only, admin-confirmed |

### Mini App
Full web storefront inside Telegram: filters, wishlist with cloud sync, search suggestions, product sheets (specs, FAQ, reviews, bundles), persistent cart, TON Connect payments, stock alerts, order history, referral links.

### Admin
- Telegram-native admin panel (catalog, orders, promos, users, broadcast)
- Payload CMS web panel for catalog/order/user management
- Order push from bot → CMS on every placement

### SaaS platform
Multi-tenant layer: each merchant gets an isolated storefront with their own bot token, catalog, and billing (monthly/yearly plans, Stripe). Tenant lifecycle, grace periods, and audit logging built in.

---

## Money safety

Every payment path follows these invariants:

1. **Integer cents everywhere.** No floats in payment math.
2. **Idempotent payment records.** `UNIQUE(provider, external_id)` — duplicate webhooks can't double-charge.
3. **Atomic claims.** Stock decrements, promo consumption, deposit claims, and order-status transitions use single-statement conditional writes serialized behind a claim lock — concurrent requests can't oversell or double-fulfill.
4. **Single fulfillment path.** All goods flow through `fulfill_order()` — never inline.
5. **Crash recovery.** If the process dies between payment and fulfillment, the retry path re-attempts the atomic claim instead of losing the order.
6. **Cancelled orders never finalize.** Watchers bail and alert admins.
7. **Promo claims release** on every cancellation path.

---

## Quickstart

### 1. The bot

```bash
cd bot
cp .env.example .env        # fill in BOT_TOKEN (required)
pip install -r requirements.txt
python app.py
```

Required in `.env`:
- `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)

Recommended:
- `ADMINS` — your numeric Telegram user ID (comma-separated for multiple)
- `PAYMENTS_PROVIDER_TOKEN` — for card payments (from BotFather → Payments)
- `CRYPTOBOT_TOKEN` — for CryptoBot payments

Optional tuning: `STARS_PER_USD` (default 60), `CURRENCY` (default USD), `REFERRAL_PERCENT` (default 5), `DELIVERY_FEE_CENTS` (default 0).

Run the smoke tests before going live:

```bash
python tests/test_smoke.py   # expect: ALL 10 GROUPS PASSED
```

### 2. The Mini App

The Mini App is a static bundle served inside Telegram. Rebuild it after catalog changes:

```bash
# From the repo root:
python tools/sync_payload_to_bot.py     # pull catalog from Payload CMS
python tools/export_catalog.py          # export to bot data
python tools/build_miniapp_bundle.py    # → miniapp/dist/index.html
```

Publish via [@BotFather](https://t.me/BotFather) → `/newapp` → upload `miniapp/dist/index.html`.

For TON Connect payments, host `tonconnect/manifest.json` somewhere public (e.g. jsDelivr via GitHub) and set the manifest URL in the Mini App config.

### 3. The admin panel (Payload CMS)

```bash
cd admin
npm install
npm run dev          # → http://localhost:3001/admin
```

Create your admin user on first launch. Catalog changes made here need the Mini App rebuild steps above to go live. Orders placed by the bot are pushed here automatically (read/update in CMS; creation only via the bot API).

### 4. Crypto wallets (self-custody)

Direct-crypto payments derive a unique deposit address per order from your HD wallet:

```bash
cd tools/hdwallet-gen
node generate.js        # creates encrypted seed (shown once — back it up!)
```

The seed is AES-256-GCM encrypted to `bot/secrets/seed.enc.json`. Derivation runs through a persistent daemon for sub-10ms address generation at checkout. Chain watchers (60s loop) detect deposits via mempool.space, Blockscout, toncenter, and tronscan.

### 5. SaaS mode (optional)

The SaaS layer lets merchants rent storefronts on your infrastructure:

- Tenants are created with their own bot token, catalog namespace, and billing plan
- Plans: monthly/yearly, managed via Stripe
- Tenant isolation is fail-closed: expired or invalid tenants serve nothing
- Audit log per tenant (survives tenant deletion)

See `bot/saas/tenants.py` for the tenant lifecycle API.

---

## Deployment

### Systemd (recommended)

```bash
# Bot
sudo cp deploy/nova-shop.service /etc/systemd/system/
sudo systemctl enable --now nova-shop

# Admin panel
sudo cp deploy/nova-shop-admin.service /etc/systemd/system/
sudo systemctl enable --now nova-shop-admin
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for webhook mode, reverse proxy, backups, and log rotation.

### Docker

```bash
cd bot
docker build -t nova-shop .
docker run --env-file .env nova-shop
```

---

## Project documentation

| Doc | Contents |
|-----|----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System overview, payment rails, money invariants, background jobs |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, auth, secret handling, audit trail |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Systemd, Docker, webhook mode, backups |
| [docs/SPEC.md](docs/SPEC.md) / [SPEC2.md](docs/SPEC2.md) | Original product specifications |
| [docs/AUDIT-2026-09-30.md](docs/AUDIT-2026-09-30.md) | Independent security audit report |
| [tools/README.md](tools/README.md) | Wallet tools, sync scripts, bundle builder |

---

## Development

```bash
# Run smoke tests (required before every deploy)
cd bot && python tests/test_smoke.py

# Code style: Python 3.12, aiogram 2.x patterns
# - All user-facing text lives in texts.py (English-only)
# - All keyboards live in keyboards.py (primary CTA first, destructive last)
# - Money in integer cents; never floats
# - Every DB write that gates money goes through the claim lock
```

### Key files

| File | Purpose |
|------|---------|
| `bot/app.py` | Entry point, dispatcher wiring |
| `bot/database.py` | Async SQLite layer, atomic claim operations |
| `bot/handlers/checkout.py` | Checkout wizard, order placement |
| `bot/handlers/payments.py` | Payment webhooks, fulfillment triggers |
| `bot/handlers/common.py` | `fulfill_order()` — the single fulfillment path |
| `bot/crypto_payments.py` | CryptoBot, HD-wallet, rate sources |
| `bot/saas/tenants.py` | Multi-tenant lifecycle and billing |

---

## Status

Continuously audited by an automated Guard+Doctor loop (static analysis + targeted fixes, all gated behind smoke tests). Latest deep audit: 2026-09-30 (53 findings, all criticals resolved).

## License

MIT — see [LICENSE](LICENSE).
