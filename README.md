# Nova Shop

A production-grade Telegram e-commerce platform: an English-only Telegram shop bot with crypto payments, a Telegram Mini App storefront, and a Payload CMS admin panel.

**Live:** [@testssscbot](https://t.me/testssscbot) · [Mini App](https://muse.ai/s/nova-shop-mini-app-xim6wudxohxjxiy)

## Repository layout

```
├── bot/            # Telegram bot (Python 3.12, aiogram 2.x)
│   ├── handlers/   # shop, cart, checkout, crypto, payments, admin, …
│   ├── tests/      # smoke tests (10 groups, all passing)
│   ├── requirements.txt, Dockerfile, .env.example
├── miniapp/        # Telegram Mini App storefront (vanilla JS, single-file)
│   ├── app.js, styles.css, index.html   # source
│   └── dist/index.html                  # built bundle (132 KB)
├── admin/          # Payload CMS 3.x + Next.js (catalog, orders, users)
├── tools/          # catalog sync, bundle builder, wallet utils, restock notifier
├── tonconnect/     # TON Connect manifest + wallet icon (served via jsDelivr)
├── brand/          # brand assets
└── docs/           # architecture, security, deployment, audit reports
```

## Features

- **Bot:** sleek 3-screen checkout wizard, Telegram Stars, CryptoBot, direct crypto (BTC/ETH/TRX/TON) with HD-wallet deposit addresses, TON Connect, promos, referrals, reviews, support tickets, order tracking, legal pages (/terms /privacy /refund)
- **Mini App:** filters, wishlist, search suggestions, product sheets (specs, FAQ, reviews, bundles), cart with CloudStorage persistence, TON Connect payments, stock alerts, order history, referral links
- **Admin:** Payload CMS for catalog/orders/users, order push from bot

## Quickstart

```bash
# 1. Bot
cd bot
cp .env.example .env        # fill in BOT_TOKEN, keys
pip install -r requirements.txt
python app.py

# 2. Mini App — rebuild after catalog changes
cd ..
python tools/sync_payload_to_bot.py
python tools/export_catalog.py
python tools/build_miniapp_bundle.py
# → miniapp/dist/index.html (publish via BotFather /newapp)

# 3. Admin panel
cd admin && npm install && npm run dev   # → http://localhost:3001/admin
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for systemd, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design, [docs/SECURITY.md](docs/SECURITY.md) for the security model.

## Status

Deep-audited 2026-09-30 (frontend, backend, security — 53 findings, all criticals fixed). See [docs/AUDIT-2026-09-30.md](docs/AUDIT-2026-09-30.md).

## License

MIT — see [LICENSE](LICENSE).
