# Nova Shop

> Telegram-native commerce platform for storefronts, checkout, fulfillment, crypto observation, and merchant operations.

[![CI](https://github.com/Pr3eve6ti2o/nova-shop-assets/actions/workflows/ci.yml/badge.svg)](https://github.com/Pr3eve6ti2o/nova-shop-assets/actions/workflows/ci.yml)

Nova Shop is a production-oriented Telegram commerce codebase. It combines a Telegram Bot, Telegram Mini App, Payload CMS administration, payment integrations, self-custody wallet observation, catalog synchronization, and an optional multi-tenant SaaS layer.

It is designed around one rule:

> **Clients propose actions. The server verifies facts. The database claims state. Fulfillment happens once.**

## What it contains

~~~text
Telegram
   |
   +--> Bot --------------------+
   |     checkout                |
   |     orders                  |
   |     fulfillment             |
   |     customer support        |
   |     payment orchestration   |
   |                            |
   +--> Mini App ---------------+
                                  |
                                  v
                            Bot transaction DB
                                  |
              +-------------------+-------------------+
              |                   |                   |
              v                   v                   v
          Payment APIs        Chain observers     Payload CMS
              |                   |                   |
              +-------------------+-------------------+
                                  |
                                  v
                           Admin / operations
~~~

## Major capabilities

### Storefront

- Telegram bot storefront with catalog, search, categories, cart, wishlist, reviews, support, referrals, promotions, and order history.
- Telegram Mini App storefront with product sheets, filtering, sorting, wishlist, cart, recent searches, stock alerts, referral UI, and checkout bridge.
- Physical and digital product modeling.
- Digital inventory/license-key delivery and physical stock fulfillment.

### Post-purchase (order lifecycle)

Borrowed from Medusa's fulfilment model, with two paths so each order type gets only the steps that make sense for it:

- **Physical goods:** admin advances the order (confirmed → preparing → shipped), the customer is notified at every step with a button back to the order, and delivery completes when the customer taps "I've received it" — ratings and returns unlock from that real handover.
- **Digital goods:** none of that. Keys are delivered at fulfilment, the order page shows a collapsed Placed → Confirmed → Delivered timeline, and rating is available immediately.
- The order page itself answers "what happens now?": dated status timeline, the delivery/pickup details on file, and a plain next-step line per status. Payment methods render by name (balance and comp included).
- The checkout delivery-details step (address/phone collection) is intentionally disabled: physical orders run as pickup.

### Payments

The code contains several payment rails:

| Rail | Current role |
|---|---|
| Telegram Stars | Digital goods/services inside Telegram |
| Telegram/provider payments | Eligible physical/service orders |
| CryptoBot | External crypto payment rail where applicable |
| Direct blockchain payments | Self-custody observation for supported physical/permitted flows |
| TON Connect | Wallet interaction + on-chain verification |
| Cash on delivery | Physical-order flow |
| Account balance (store credit) | Internal-ledger checkout, admin credit/debit, gift cards |
| Comp / manual orders | Merchant-created orders charged to balance or comped, settled in the ledger |

**Telegram payment compliance matters:** digital goods and services sold inside Telegram bots/Mini Apps must use Telegram Stars. Third-party/provider and crypto routes must not be exposed for those digital orders merely because the implementation supports them. See https://core.telegram.org/bots/payments-stars

### Store credit and merchant credit tools

Borrowed from Medusa's store-credit model and adapted to the bot ledger:

- Every customer has a store-credit account: the existing balance, backed by credit lots (FIFO spends, optional expiry) and an append-only ledger whose rows carry actor, note and reference provenance.
- Admins can credit or debit any customer with a mandatory note — from the Telegram admin console or the Payload Store Credit panel. Admin credits never earn the top-up bonus; debits fail closed against the current balance.
- Gift cards (`NOVA-XXXX-XXXX-XXXX`) are issued by the bot, redeemed to balance by customers, and can be revoked; partial redemption is supported.
- Manual orders let a merchant check a customer out without an external payment: charged to balance or comped, always priced from the catalogue.
- Order refunds can be returned to store credit (partial or full) from the bot or the panel.

### Pricing engine

`pricing-engine/` is the shared money-calculation package (Node ≥ 20, ESM):

- Dinero.js for fiat (integer minor units only) and Decimal.js for crypto quotes.
- A parity contract (`pricing-engine/test-vectors.json`) runs the same vectors through the JavaScript engine and the bot's own checkout totals, so the two implementations cannot drift.
- The Mini App bundles the engine for cart subtotals and TON conversions; the Python bot remains the runtime authority for totals.

### Crypto

Current code supports Bitcoin, EVM stablecoin rails, TRON, TON, and additional Base/Optimism/Polygon stablecoin variants.

The crypto layer uses:

- public-only HD-wallet derivation;
- derivation counters scoped per xpub — chains sharing one xpub share one counter, so a deposit address is never issued twice (migration m016);
- persistent Wallet Core daemon;
- integer atomic-unit accounting;
- underpayment/top-up handling;
- chain/provider-specific confirmation state;
- duplicate/replay protection;
- late-payment review;
- periodic reconciliation concepts.

Wallet generation belongs in the separate Bawa reference repository. Nova Shop should consume public derivation material; private recovery material must never be part of the running web/bot process.

### Admin

Payload CMS provides:

- catalog/category/media administration;
- order visibility, manual order creation and refund-to-credit actions;
- a customer store-credit mirror with credit/debit actions and transaction history;
- gift card issue/revoke;
- staff/admin authentication;
- service-to-service catalog/order synchronization.

The current architecture intentionally treats Payload as the CMS/administrative surface and the bot database as the live transactional ledger.

Payload never writes the bot database. Panel money actions call the bot's localhost internal API (shared secret + idempotency keys); buyer-info edits on unshipped orders are written back through the same API and refused once an order has shipped.

### SaaS

The repository also contains an optional multi-tenant layer for merchant lifecycle/billing. Tenant isolation must remain explicit at every data and API boundary before this mode is used for multiple untrusted merchants.

## Repository layout

~~~text
.
├── bot/
│   ├── handlers/          # Telegram presentation/application entrypoints
│   ├── saas/              # tenant lifecycle/billing
│   ├── tests/              # bot smoke coverage
│   ├── app.py             # runtime entrypoint
│   ├── config.py          # validated environment configuration
│   ├── database.py        # current transactional repository + schema
│   ├── internal_api.py    # localhost API the Payload panel uses for money actions
│   ├── crypto_payments.py # current payment/chain integration hub
│   ├── crypto_watcher.py  # background observation/finalization loop
│   ├── webapp_auth.py     # Telegram Mini App initData validator
│   └── texts.py           # current UI/legal copy source
├── miniapp/
│   ├── index.html
│   ├── app.js              # current source monolith; migration target below
│   ├── styles.css
│   ├── catalog.json        # generated
│   ├── policies.json       # generated
│   └── dist/index.html     # generated deploy artifact
├── admin/
│   ├── src/collections/    # Payload data/admin model
│   ├── scripts/            # CMS bootstrap utilities
│   └── package-lock.json
├── pricing-engine/         # shared money math (Dinero.js fiat + Decimal.js crypto)
├── tools/
│   ├── build_miniapp_bundle.py
│   ├── export_catalog.py
│   ├── export_policies.py
│   ├── sync_payload_to_bot.py
│   ├── notify_restock.py
│   └── wallet utilities
├── tonconnect/
├── brand/
├── docs/
└── LICENSE
~~~

## Data ownership

This is currently a deliberate dual-database design:

~~~text
Payload
  ↓
catalog authoring
  ↓
sync
  ↓
Bot SQLite
  ↓
orders / payments / inventory / customer state
~~~

Payload order documents are a mirror for administration. They are not the settlement ledger.

Store credit follows the same rule in reverse: the panel's Customers and Gift Cards collections are read models mirrored from the bot, and every credit, debit, gift-card, manual-order and refund action is executed by the bot through its internal API — the panel holds no money state of its own.

For growth and multi-process consistency, the preferred direction is shared Postgres plus durable event/outbox processing. Payload officially supports Postgres and migration workflows. https://payloadcms.com/docs/database/postgres

## Security model

### Never trust the client

Mini App state, callbacks, prices, quantities, and payment claims are client-controlled inputs. Recalculate important values from server-side state.

For any future browser HTTP API, validate Telegram's raw initData server-side and never use initDataUnsafe as an authority. https://core.telegram.org/bots/webapps

### Never fulfill on “payment intent”

Only a verified payment observation that satisfies the order's network, asset, recipient, amount and finality policy can enter fulfillment.

### Never put secrets in the repository

Do not commit:

- BOT_TOKEN;
- PAYLOAD_SECRET;
- provider/API keys;
- database files;
- wallet recovery material;
- production environment files.

### Webhooks

Production Telegram webhook ingress should use Telegram's secret_token and verify the X-Telegram-Bot-Api-Secret-Token header. https://core.telegram.org/bots/api#setwebhook

## Development

### Bot

~~~bash
cd bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
~~~

Run the unit suite (103 tests — money paths, pricing parity, the internal API contract, the order lifecycle, and smoke coverage):

~~~bash
cd bot
python -m unittest discover -s tests -p "test_*.py"
~~~

### Admin

Use npm because package-lock.json is tracked. Copy `admin/.env.example` to `.env` first — the build refuses to run without a `PAYLOAD_SECRET` of at least 32 characters. Set `NOVA_BOT_API_URL` / `NOVA_BOT_API_SECRET` to enable the panel's store-credit actions against the bot's internal API.

~~~bash
cd admin
npm ci
npm run dev
~~~

### Pricing engine

~~~bash
cd pricing-engine
npm test
~~~

CI:

~~~bash
npm run lint
npm run build
npm run test:int
~~~

### Mini App

Rebuild generated assets:

~~~bash
python tools/sync_payload_to_bot.py
python tools/export_catalog.py
python tools/export_policies.py
python tools/build_miniapp_bundle.py
~~~

Do not manually edit miniapp/dist/index.html.

## Target architecture

The codebase is being migrated toward:

~~~text
presentation
   ↓
application services
   ↓
domain
   ↓
ports/interfaces
   ↓
infrastructure adapters
~~~

Domain code must not import Telegram, Payload, HTTP providers, blockchain SDKs, or the database implementation.

See [docs/CODEBASE-STRUCTURE.md](docs/CODEBASE-STRUCTURE.md).

## Production readiness

Nova Shop is feature-rich but should not be described as externally audited or production-certified.

Before real-money deployment, complete:

1. Telegram payment-rail classification enforcement.
2. Payload collection and field-level RBAC.
3. Chain-native payment-event identity.
4. Transactional/durable fulfillment.
5. Explicit bot database migrations.
6. Cluster-safe locking/rate limiting and worker leases.
7. Secret/dependency scanning.
8. Reconciliation and restore drills.
9. Stable HTTPS legal/TON Connect metadata.
10. External security review.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Product & architecture documentation](docs/NOVA-SHOP-PRODUCT.md)
- [Payments](docs/PAYMENTS.md)
- [Data model](docs/DATA-MODEL.md)
- [Security](docs/SECURITY.md)
- [Codebase structure](docs/CODEBASE-STRUCTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Release checklist](docs/RELEASE.md)
- [Deep audit — 2026-10-15](docs/AUDIT-2026-10-15.md)
- [Deep audit — 2026-10-05](docs/AUDIT-2026-10-05.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Product specifications](docs/SPEC.md) / [SPEC2.md](docs/SPEC2.md)

## Current implementation note

The current repository contains a working, flat bot architecture. The target structure is documented before a risky mass-migration. This is intentional: every domain extraction should be accompanied by focused tests and a reversible deployment step.

## License

MIT.
