# Changelog

All notable changes to Nova Shop are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]
### Fixed — Deep-audit fix programme (2026-10-15; see docs/AUDIT-2026-10-15.md)
- Crypto deposit addresses could be issued to multiple orders: every EVM chain shares one xpub and derivation path, but index counters were keyed per chain name. Counters are now scoped per xpub, and migration m016 seeds them from the legacy per-chain maxima so no issued index recurs (schema version 16). Manual crypto confirmation was broken end to end (it read a column `crypto_deposits` does not have, blocking every confirm as "underpaid") and marked deposits paid before finalising; the gate now compares observed vs expected units under the watcher's tolerance and honours the finalise result. Deposit rejects refuse deposits with funds on-chain, the chain-disable confirmation arm persists, the derivation daemon's teardown is inside its lock and it spawns without the bot's secrets, and the watcher no longer KeyErrors on testnet chains.
- Admin order handling: two admins could fulfil the same stuck order twice (double keys/stock/referral) through the read-then-act stale-claim retry — it now steals the claim atomically; the recovery path also crashed on an undefined `logger`. Concurrent cancels could release a promo twice (compare-and-set now wins the transition first); cancelling a paid order flags `refund_owed` in the audit log and alerts admins. "Mark refunded" records paid-minus-already-refunded from the ledger instead of the raw order total and no longer crashes on a missing order; the deny flow notifies the customer before confirming to the admin. The maintenance toggle accepts only exact `1`/`0` payloads.
- Support: the admin inbox rendered raw customer ticket bodies and names into an HTML message (stored injection; one malformed tag bricked the view) — now escaped. Admin replies could reach or be filed under the wrong customer via a stale ticket binding, an unbound reply prompt, or a reply flow left armed by closing the ticket — all closed; reply prompts are bound by message id and stale replies are refused.
- Checkout and shop: changing payment method on a pending order resurrected the cancelled order's delivery details and payment keys into live state (it now mirrors `start_checkout`'s hygiene and re-validates restored items); a systemic double-answer defect hid error alerts across shop, cart, orders and profile handlers; the quantity stepper treated unknown deltas as −1; cart navigation could trap users in the promo state; purchase-history pages beyond page 1 were unreachable and now have Newer/Older navigation.
- Core and rent: a crashed worker's exception could abort shutdown cleanup, and background tasks died silently (now supervised). The rental confirm flow validates the provider against an allowlist and re-validates the plan, gained a per-user submit lock, and only renders "Charged" for a genuinely ACTIVE balance charge; the unwired `saas/tenants.py` scaffold's stale $4.99/$49.99 prices now mirror the standing $8.99/$89.99 plan. The expired-credit sweep counted forfeitures it never took (the guarded debit's rowcount is now checked). Every finding was re-verified against the code first; refuted claims are listed in the audit doc. Suites after the programme: 103 unit, 29 pricing-engine, 112/113 functional (one pre-existing harness artefact).
- CryptoBot hardening (separate fix, ported from JumpCodeFrog's cryptobot.go): strict no-rounding provider amount parser; receipt validation (amount/asset/payload must match the stored invoice) on the sweep and both "I've Paid" checks before any money moves; paid-but-invalid invoices quarantined into the /payreview queue with raw provider facts preserved and a one-time admin alert; recovery sweep now credits paid balance top-ups (previously looped unfinalised forever); bounded provider-history window scan (1000-invoice windows, continuation offset) quarantining late payments for expired/cancelled invoices and orphan paid invoices — never auto-crediting them.
- Scraped-port completion (plan 1.3, 7.3, 7.4, 8.4): Doctor CLI ported from JumpCodeFrog's doctor.go; seed + smoke tools ported from their cmd/seed and cmd/telegram-smoke; inline product sharing ported from DoktorShift's handle_inline_query; buyer-info checkout modes (none/email/address, default none) on DoktorShift's buyer fields model.

### Added — Post-purchase order lifecycle (Medusa borrow)
- Two fulfilment paths, classified per order (`order_has_physical`): physical orders follow Medusa's progression — admin prepares and ships, the customer confirms receipt ("I've received it", compare-and-set to `delivered`), and ratings/returns unlock from the real handover. Digital orders skip all of it: delivered at fulfilment, collapsed Placed → Confirmed → Delivered timeline, rating available immediately.
- The order page now tells the story: a dated status timeline (placed/shipped/delivered stamps), the delivery or pickup block with the address/phone on file, and a plain next-step line per status. Status-change messages to the customer carry a Track Order button.
- Migration m015 completes the `orders.status` vocabulary (`preparing`, `completed`), rebuilding historical tables in place where their CHECK constraint lags (see DATA-MODEL).

### Fixed — Order lifecycle dead ends and gift-card entry points
- Orders could stick at `confirmed` forever: the base schema's status CHECK never gained `preparing` (the admin's only forward step crashed with an IntegrityError on such databases), and the admin fulfilment gate did not recognise balance/comp payments, refusing shipped/delivered for every balance-paid order as "unpaid". Both fixed.
- The ⭐ Rate Items button on the order page had no handler anywhere; it now opens a per-item picker into the existing review flow, gated to delivered (physical) or fulfilled (digital) orders. Balance and comp orders no longer render their payment method as "—".
- Gift cards "not working" was an entry-point failure, not an engine bug: the Profile Balance button opened the top-up screen and the promo doors rejected `NOVA-…` codes as invalid promos. Profile Balance now opens the Balance screen (which carries Redeem gift card), and both promo doors redeem gift-card codes with gift-specific responses; real promo codes are unaffected.
- The top-up amount picker's Back button (`bal:back`) rendered without a handler; it now returns to the Balance screen.

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
