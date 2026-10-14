# Changelog

All notable changes to Nova Shop are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]
- CryptoBot hardening (separate fix, ported from JumpCodeFrog's cryptobot.go): strict no-rounding provider amount parser; receipt validation (amount/asset/payload must match the stored invoice) on the sweep and both "I've Paid" checks before any money moves; paid-but-invalid invoices quarantined into the /payreview queue with raw provider facts preserved and a one-time admin alert; recovery sweep now credits paid balance top-ups (previously looped unfinalised forever); bounded provider-history window scan (1000-invoice windows, continuation offset) quarantining late payments for expired/cancelled invoices and orphan paid invoices — never auto-crediting them.
- Scraped-port completion (plan 1.3, 7.3, 7.4, 8.4): Doctor CLI ported from JumpCodeFrog's doctor.go; seed + smoke tools ported from their cmd/seed and cmd/telegram-smoke; inline product sharing ported from DoktorShift's handle_inline_query; buyer-info checkout modes (none/email/address, default none) on DoktorShift's buyer fields model.

### Added — Store credit, gift cards and manual orders (Medusa borrow)
- Ledger upgraded to Medusa's shape (migration m014): every balance transaction carries actor type/id, a note and a reference; orders record their origin.
- Admin credit/debit for any customer with a mandatory note and a customer notification — in the Telegram admin console and the Payload Store Credit panel. Credits never earn the 5% top-up bonus; debits fail closed and consume credit lots FIFO.
- Gift cards: bot-issued `NOVA-XXXX-XXXX-XXXX` codes with value, expiry and partial redemption to balance; revoke from the bot console or the panel; customers redeem from the Balance screen.
- Manual orders: merchants can check a customer out without an external payment — charged to balance or comped — priced only from the catalogue, born confirmed, audit-logged.
- Refund-to-credit from the panel and the bot (partial allowed; the order flips to `refunded` at the full amount). /refund ledger rows now carry the admin actor, note and order reference.
- Bot internal API (localhost-only aiohttp, shared-secret header, idempotency keys on every mutation): Payload's Customers and Gift Cards collections are read-model mirrors synced from it; buyer-info edits in the panel write back through it and are refused once an order has shipped (the hook runs beforeChange, so a refusal cannot drift the panel copy).
- Bot suite grown to 98 tests; the Payload↔bot flow is verified end to end (sync → credit → balance order → gift card → refund → comp order → buyer write-back → post-ship refusal).

### Added — Payment & Pricing Engine
- New `pricing-engine/` package (Node ≥ 20, ESM): Dinero.js 2 for fiat (integer minor units, floor-rounded percent promos, ceiling gateway gross-up) and Decimal.js for crypto quotes, byte-identical to the bot's conversion math.
- Parity contract: shared test vectors run against both the JavaScript engine and the bot's real checkout totals; the Mini App bundles the engine for cart subtotals and TON nanoton conversions. No bot runtime change — Python remains the totals authority.

### Added — Repo port programme (DoktorShift/telegramshop + JumpCodeFrog/telegram-shop-bot)
- Returns workflow with fulfilment stamps (shipped_at/delivered_at),
  atomic exactly-once refunds, and a /returns admin console (1.1/1.2).
- Server-side cart timestamps + Mini App cart_sync; campaign engine:
  abandoned-cart reminders, back-in-stock alerts, wishlist price-drop
  alerts, post-purchase thank-yous, onboarding nudge, credit expiry (2, 8.1).
- Threaded support tickets with full conversation history + /inbox (3).
- Payment review queue (/payreview) with fingerprint-quarantined
  anomalies and append-only resolutions; refunds ledger with a
  fail-closed per-order ceiling; /refund; /providers; signed outbound
  webhooks; admin forum-topic routing; daily revenue stats (6).
- Reviews restored end-to-end (handlers rebuilt to the codebase's own
  surviving spec); loyalty tiers (Bronze/Silver/Gold/VIP) accruing on
  fulfilment; category-scoped and personal promo codes (5).
- Store credit lots under the balance: FIFO spends, LIFO restores on
  failed fulfilment, optional grant expiry — balance always equals the
  sum of lot remainders (4).
- Test suite grown from 17 to 58 tests covering the money paths above.

### Added
- Docker packaging: `Dockerfile` + `docker-compose.yml` (SQLite on a named volume).
- `.env.example` documenting every environment variable the bot reads.
- `Makefile` with install/run/test/lint/docker targets.
- `CONTRIBUTING.md` with branch, commit, and testing conventions.

## [2026-10-13] — Deep-audit fix programme complete

### Fixed
- All P0/P1 findings from the third Opus deep audit of
  `refactor/nova-shop-professional` (atomic checkout/fulfilment, dual-control
  token swaps, EVM deposit identity, Stars enforcement, outbox pattern,
  versioned migrations, inventory reservations).
- `cb()` callback validation relaxed to allow namespaced prefixes (e.g.
  `ad:ord`), fixing an Admin-button crash; regression test added.

### Changed
- Rental UI: Monthly $8.99 / Yearly $89.99 behind "Continue to Payment";
  7-day first-time-only trial; recurring billing via balance auto-debit and
  CryptoBot invoices.
