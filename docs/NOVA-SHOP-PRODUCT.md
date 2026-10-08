# Nova Shop — Product & Architecture Documentation

> **Purpose:** This document describes what is being built, for whom, and how
> it all fits together. It is written so that another AI (or developer) can
> produce accurate user-facing documentation, API references, and runbooks
> without guessing.

---

## 1. What is Nova Shop?

Nova Shop is a **Telegram-native e-commerce bot** that lets a store owner sell
physical and digital products directly inside Telegram. Customers browse a
catalogue, add to cart, and pay without leaving the chat.

On top of the shop, there is a **rental/SaaS platform**: other people ("tenants")
can rent their own shop-bot instance. They paste their own BotFather token, pick
a subscription plan, and get a working store powered by the Nova control plane.

### The two products

| Product | Audience | Description |
|---|---|---|
| **Shop Bot** | End customers | Telegram bot for browsing, cart, checkout, payments |
| **Rental Platform** | Tenants (store owners) | Rent-a-bot SaaS: subscription, token management, dashboard |

---

## 2. System components

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Telegram Bot   │────▶│  Control Plane   │────▶│  Payload CMS    │
│  (aiogram 2.x)  │     │  (Next.js/TS)    │     │  (admin panel)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                        │                         │
        ▼                        ▼                         ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Mini App       │     │  Identity Svc    │     │  Public Website │
│  (WebApp)       │     │  (better-auth)   │     │  (Next.js)      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

### 2.1 Telegram Bot (`bot/`)

- **Framework:** aiogram 2.25.2, Python 3.12
- **Entry:** `bot/app.py` (polling mode for testing; webhook for production)
- **Database:** SQLite (`data/nova_shop.db`) — single-file, WAL mode
- **Key handlers:**
  - `handlers/rent.py` — rental subscription flow
  - `handlers/rent_swap.py` — token-swap requests (dual control)
  - `handlers/miniapp.py` — TON Connect orders, WebApp data
  - `handlers/crypto.py` — direct crypto deposit flows
  - `keyboards.py` — all inline/reply keyboards
  - `texts.py` — all user-visible strings (English only, en-GB)

### 2.2 Control Plane (`nova-platform/nova-private/identity/`)

- **Framework:** Next.js (TypeScript), PostgreSQL via Drizzle ORM
- **Auth:** better-auth (email/password + Telegram login)
- **Purpose:** Single source of truth for plans, subscriptions, entitlements,
  users, API keys, billing

### 2.3 Payload CMS (`admin/`)

- Headless CMS for product catalogue management
- The bot pushes orders to Payload via `payload_hooks.py`
- Admin panel runs on `:3001` (never exposed publicly)

### 2.4 Mini App (`miniapp/`)

- Telegram WebApp storefront
- Built by `tools/build_miniapp.sh` → `export_catalog.py` → `export_policies.py`
  → `build_miniapp_bundle.py`
- Catalogue and policies are generated from the database, never hardcoded

### 2.5 Public Website (`nova-platform/nova-private/website/`)

- Landing page, pricing, login, customer dashboard, API docs
- Dashboard shows: subscription status, entitlements, API keys, referrals, teams

---

## 3. Payment rails

The bot supports multiple payment methods. **Checkout order:** Balance → Stars → Crypto.

### 3.1 Balance (internal ledger)

- Users top up their bot balance via crypto or CryptoBot
- Fastest checkout; no external calls

### 3.2 Telegram Stars (XTR)

- **Digital goods inside Telegram MUST use Stars exclusively** (Telegram policy)
- Backend enforces this: non-Stars payments for digital-goods carts are rejected
- UI should hide unavailable rails before confirmation (not just reject after)

### 3.3 CryptoBot (third-party)

- Invoices via CryptoBot API
- 3% fee (charged to customer)

### 3.4 Direct crypto (self-custody)

- **Chains:** BTC, ETH, TRX, TON (native) + USDT/USDC on Base, Optimism, Polygon, Ethereum
- **Model:** Unique deposit address per user per chain (HD wallet from xpub)
- **Detection:** Blockchain watcher polls explorers (Blockscout → Etherscan V2 fallback)
- **Important:** Funds stay at the derived address. There is NO auto-forwarding.
  Sweeping requires the offline sweep tool (seed never touches the server).

---

## 4. Rental platform (SaaS)

### 4.1 Plans

| Plan | Price | Period | Trial |
|---|---|---|---|
| Monthly | $8.99 | 30 days | 7 days (first time only) |
| Yearly | $89.99 | 365 days | 7 days (first time only) |

Plans are defined in the control plane (`/api/internal/plans`). The bot never
hardcodes prices.

### 4.2 Quotas

| Resource | Monthly | Yearly |
|---|---|---|
| Bot instances | 1 | 3 |
| Products | 100 | 500 |
| Orders/month | 1,000 | 10,000 |
| API keys | 5 | 10 |

### 4.3 Tenant lifecycle

1. **Onboard:** Tenant pastes BotFather token in the bot → proof-of-control
   challenge → subscription created
2. **Active:** Bot instance runs, tenant manages products via Payload or Mini App
3. **Past due:** 72h grace → suspend (deleteWebhook, token retained)
4. **Cancel:** Voluntary → hand-over (token released to tenant, 30-day data
   retention, then cryptographic shredding)
5. **Abuse:** deleteWebhook + token rotation + account blocklist

### 4.4 Token swap (support flow)

When a tenant loses/regenerates their BotFather token:

1. Tenant applies from the bot (**not** self-serve)
2. **Two distinct approvers** required (dual control):
   - Approver 1 reviews and approves → status `approved_1`
   - System notifies eligible second approvers (excludes approver 1)
   - Approver 2 approves → status `approved` → atomic token replacement
3. Approvers need `PERM_SWAP_APPROVE` permission (or be in `ADMINS`)
4. Approval transitions are atomic compare-and-set (no race conditions)

---

## 5. Data model (key tables)

### Shop database (SQLite)

| Table | Purpose |
|---|---|
| `users` | Telegram users; `has_rental_history` (UI only, never auth) |
| `orders` | Orders with `payment_status` + `fulfillment_status` |
| `order_items` | Line items |
| `payments` | Payment ledger: separate `fiat_amount_minor`/`fiat_currency` and `crypto_amount_atomic`/`crypto_asset`/`crypto_chain`/`token_contract` |
| `crypto_deposits` | Payment intents: expected amount, deposit address, status. Event identity: `(chain_id, token_contract, txid, log_index)` |
| `payment_observations` | Blockchain observations linked to `deposit_id`/`order_id`/`user_id`. Full audit trail: intent → observations → settlement |
| `reconciliation_cursors` | Per-chain block-height cursors for watcher resume/replay |
| `outbox_events` | Durable outbox for async delivery (e.g., to Payload) |
| `tonconnect_intent_claims` | Per-intent TON claim codes (single-use `TC-` codes) |
| `rental_swap_applications` | Token-swap requests with `approved_by_1`/`approved_by_2` |

### Control plane (PostgreSQL)

| Table | Purpose |
|---|---|
| `user` / `account` | better-auth users; Telegram linked via `account(providerId='telegram')` |
| `subscriptions` | Rental subscriptions with `purge_at` (30-day retention) |
| `api_keys` | Scoped API keys (SHA-256 hashed, timing-safe compare) |
| `plans` | Plan catalogue (single source of truth) |

---

## 6. Key architectural decisions

### 6.1 Money-critical transactionality

- **Checkout:** `create_checkout_atomic()` — order + items + promo + cart-clear in
  one `BEGIN IMMEDIATE` transaction
- **Fulfillment:** `fulfill_order_atomic()` — stock decrement + key assignment +
  status update atomically; no compensation rollback needed
- **TON Connect:** `create_tonconnect_order_atomic()` — order + items + payment
  atomically; duplicate txid rolls back everything

### 6.2 Event identity (EVM)

Two ERC-20 Transfer events in one transaction are distinct. Identity is
`(chain_id, token_contract, txid, log_index)` with a UNIQUE index.
The old `UNIQUE(chain, txid)` was removed via table rebuild migration.

`log_index` is deterministically assigned (sorted by block/recipient/value) because
the explorer APIs don't return canonical log indices. Documented as synthetic.

### 6.3 No hardcoded secrets or prices

- Prices come from `/api/internal/plans`
- API keys, tokens, xpubs are env-only, never in git
- `NOVA_API_URL` and `PAYLOAD_URL` reject remote `http://` (HTTPS enforced)

### 6.4 English-only UI

All user-visible text is in English (en-GB). No other languages in buttons,
messages, or the Mini App.

### 6.5 Sleek/minimal UX

The user's bar: as a consumer, they won't spend time on a bot with too many
buttons. Cut clutter, reduce taps, no dead buttons.

---

## 7. Rent flow (user journey)

```
Rent → [Continue to Payment] → Choose Monthly/Yearly → 
  Pay with: Balance | CryptoBot | Crypto payments → 
  Confirm → Subscription active → "My Rental" appears on main menu
```

- **No website linking required.** The bot auto-provisions users via
  `POST /api/internal/users/ensure` — the old "link your Telegram on the
  website" gate was removed.
- After subscribing (even once), "My Rental" shows on the main menu as an
  invoice-like view.

---

## 8. Repository layout

```
nova-shop-repo/                    # Branch: refactor/nova-shop-professional
├── bot/                           # Telegram bot (Python/aiogram)
│   ├── app.py                     # Entry point
│   ├── config.py                  # Env-only config, HTTPS enforcement
│   ├── database.py                # SQLite + all migrations
│   ├── crypto_payments.py         # Chain configs, quoting (Decimal)
│   ├── crypto_watcher.py          # Blockchain observer
│   ├── payload_hooks.py           # Payload CMS integration
│   ├── keyboards.py               # All keyboards
│   ├── texts.py                   # All UI strings (en-GB)
│   ├── handlers/                  # Message/callback handlers
│   └── tools/sweep.py             # Offline sweep tool (EIP-1559)
├── admin/                         # Payload CMS
├── miniapp/                       # Telegram WebApp (generated bundle)
├── tools/                         # build_miniapp.sh, exporters
├── docs/                          # This file, runbooks, checklists
└── .github/workflows/ci.yml       # CI (fail-closed Mini App build)
```

**Not in this repo** (external dependencies):
- `nova-platform/nova-private/identity/` — control plane (Next.js + PostgreSQL)
- `nova-platform/nova-private/website/` — public website + dashboard

---

## 9. Current status (2026-10-08)

### Completed
- P0–P4 from the first deep audit (all money-critical, security, platform fixes)
- Second re-audit P0 (release blockers) and P1 (financial integrity)
- Second re-audit P2 in progress (security: swap permissions, atomic approvals)

### Pending (need the user)
- **B-1:** Production domain for `RENTAL_PUBLIC_BASE_URL`
- **B-2:** Interactive Telegram walkthrough in `@testssscbot`
- `SUPPORT_USERNAME` in bot `.env`
- BotFather description text (in `docs/TOKEN-SWAP-FLOW.md`)

### Test environment
- Test bot running as `@testssscbot` (polling mode)
- Test database is a copy; live database untouched
- Live `nova-shop` systemd service stays STOPPED

---

## 10. Glossary

| Term | Meaning |
|---|---|
| **Tenant** | A customer renting a shop-bot instance |
| **Control plane** | Central API for plans, subscriptions, entitlements, users |
| **Payment intent** | A `crypto_deposits` row: expected amount + deposit address |
| **Observation** | A `payment_observations` row: a blockchain transfer seen by the watcher |
| **Settlement** | Linking observations to an intent and marking it claimed |
| **Dual control** | Two distinct approvers required for sensitive operations |
| **Outbox** | Durable event table for async delivery with retry |
| **xpub** | Extended public key for HD wallet address derivation |
| **Sweep** | Moving funds from deposit addresses using the offline tool |
