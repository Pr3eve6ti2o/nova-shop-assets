# Changelog

All notable changes to Nova Shop are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]
- Scraped-port completion (plan 1.3, 7.3, 7.4, 8.4): Doctor CLI ported from JumpCodeFrog's doctor.go; seed + smoke tools ported from their cmd/seed and cmd/telegram-smoke; inline product sharing ported from DoktorShift's handle_inline_query; buyer-info checkout modes (none/email/address, default none) on DoktorShift's buyer fields model.

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
