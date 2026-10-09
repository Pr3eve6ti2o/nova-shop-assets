# Session Handover — 2026-10-08 (for another AI)

This document describes everything done on 2026-10-08 so another AI can pick up
without re-doing work. Branch: `refactor/nova-shop-professional` @ `98192e0` (PUSHED 2026-10-08 ~21:57 IST; was @ `3e70a11`).

## System state (as of 18:55 IST)

| Component | Status | Notes |
|---|---|---|
| Test bot (@testssscbot) | RUNNING (PID 3612) | Professional branch, polling. Restarted 18:53 IST after proxy cred died. |
| Live `nova-shop` systemd | STOPPED | User order — never touch. |
| identity (:3002) | Active | Rebuilt after adding /api/rental/export. |
| website (:3003) | Active | Localhost-only. |
| admin (:3001) | Active | |
| vault socket | Live | /run/nova-rental-vault/vault.sock |
| postgres, redis, importer | Active | 12th VM replacement re-restored ~14:06 IST. |

## What was built today (all on `refactor/nova-shop-professional`, pushed @ 3e70a11)

### 1. Rent UI redesign (`da5ea54`)
- `bot/keyboards.py::rent_plans_kb` — Rent screen now shows: [💳 Continue to Payment] → [🏠 Menu] → [✅ Monthly | Yearly] selectors → [📋 My Rental]. Monthly/Yearly toggle with checkmarks. "Continue to Payment" (`rent:topay:<id>`) goes to payment-method screen.
- New `rent_method_kb` (Balance/CryptoBot + Back + Menu).
- Persistent "My Rental": new `users.has_rental` column; set on every successful subscription; backfilled on /start; shows "📋 My Rental" in main menu as a sort of invoice.
- Cart: /start "items in cart" message now has a "🛒 View cart (n)" button (was a dead end).

### 2. Etherscan V2 deposit fallback (`2e21bbc`, DeepSeek's code)
- **Problem:** Blockscout v2 returns 403 (Cloudflare) for Polygon and Base. USDT/USDC deposits there never detected.
- **Fix:** `fetch_etherscan_v2_token_txs` + `fetch_evm_token_txs_with_fallback` in `bot/crypto_payments.py`. Blockscout first, Etherscan V2 on empty. Same `{txid, to, base, confirmations}` format. Never raises.
- **Config:** `ETHERSCAN_API_KEY` in `bot/config.py` (env-only). Chain IDs: eth=1, op=10, base=8453, polygon=137.
- **Status:** ACTIVE. User provided key 2026-10-08 ~17:25 IST. Stored in `/home/hatch/workspace/nova-bot-test/.env`. Verified live: 6,995 txs returned; fallback path tested (Blockscout 403 → Etherscan clean).

### 3. Testnet mode (`2e21bbc`, DeepSeek's code)
- `CRYPTO_TESTNET=1` switches to `TESTNET_CHAINS` (tETH/Sepolia 11155111, tUSDC/Base Sepolia 84532) via `active_chains()`. Deposit flow, watcher, and formatting all switch. `TESTNET_XPUB_ETH` for the test xpub. All labels prefixed TESTNET. Mainnet unchanged when off.

### 4. Offline sweep tool (`95a5b3a` + `3e70a11`, Orion built per disclosed exception)
- **Problem:** Deposit funds are STRANDED — no way to withdraw from derived addresses through the bot.
- **Solution:** `bot/tools/sweep.py` — owner-run offline script. Seed via getpass only (never argv/env/log), dry-run by default, `--execute` for real.
- **BTC:** `bip_utils` BIP84 derivation + `embit` P2WPKH signing, mempool.space for UTXOs/fees/broadcast.
- **EVM:** `bip_utils` BIP44 + `eth-account` signing, JSON-RPC. Sweeps ERC-20 (chain-aware USDT/USDC contracts) first, then native.
- **Verified:** Derivation MATCHES the bot's `hdwallet-gen` at indices 0, 1, 5 for both BTC and ETH.
- **Usage:** `pip install bip-utils embit eth-account requests`, then `python3 tools/sweep.py --chain btc --destination <addr>` (dry-run by default).

### 5. Token-swap flow (pushed earlier, `396f81d`)
- Tenant applies from bot → owner approves via DM → tenant pastes new token → challenge → auto-execute. See `docs/TOKEN-SWAP-FLOW.md`.
- Still needed: set `SUPPORT_USERNAME` in bot `.env` + BotFather description (text in the doc).

## Proxy credential situation (CRITICAL for any AI working here)

The sandbox egress proxy credentials rotate frequently and die without warning.
Key lessons (also in `~/AGENTS.md`):

1. **Never trust `~/workspace/shop-bot/.proxy.env` blindly.** The minutely cron writes DEAD credentials to it regularly. Always verify with a real Telegram `getMe` call before using.
2. **The working credential may live in your shell env**, not the file. Test: `curl -x "$https_proxy" https://api.telegram.org/bot<TOKEN>/getMe`. HTTP 200/404 = proxy auth works (404 just means bad token). 407/000 = dead.
3. **A running bot keeps working** on its in-process credential even after the file goes stale. But when that credential rotates, the bot dies with `NetworkError`/`ServerDisconnectedError` in `bot-test.log`.
4. **To restart:** verify a credential with getMe FIRST, write it to the file, then launch: `set -a; source ~/workspace/shop-bot/.proxy.env; set +a; setsid nohup ~/workspace/nova-bot-test/run-test.sh >> ~/workspace/nova-bot-test/bot-test.log 2>&1 < /dev/null &`
5. **Never run `refresh-proxy-env.sh` from your own shell** — your env is stale; only the cron worker's env is fresh. The script now verifies with getMe before writing (won't clobber with dead creds).
6. **The 10-min `test-bot-egress-watch` cron** tries to relaunch the bot when egress works. It stays silent on no-op runs.

## Key paths

- Branch code: `~/workspace/nova-shop-repo` (git `refactor/nova-shop-professional`)
- Test rig: `~/workspace/nova-bot-test/run-test.sh` + `bot-test.log` + `.env` (has ETHERSCAN_API_KEY)
- Test DB: `~/workspace/nova-bot-test/data/nova_shop.db` (COPY of live — safe to test against)
- Live DB backup: `~/workspace/nova-shop/data/nova_shop.db.bak-20261007`
- Proxy: `~/workspace/shop-bot/.proxy.env` (600)
- Venv: `~/workspace/nova-shop/.venv` (has bip-utils, embit, eth-account installed)
- Identity: `~/workspace/nova-platform/nova-private/identity/` (not git-tracked; rebuild after adding routes: `npm run build`)


## Deep audit fixes (2026-10-08 evening, all on `refactor/nova-shop-professional`, local commits)

User uploaded `~/workspace/user/files/nova-shop-deep-audit-2026-10-08.txt` (another AI's file-by-file audit).
Orion verified each claim against the real code, split into P0–P4. DeepSeek was briefed for P1 but produced
ungrounded code (invented tables/APIs); Orion implemented directly per the disclosed exception.

### P0 — release blockers (`edd93d2`, `44aa41b`, `2209f2a`)
- `bot/requirements.txt`: pinned `aiohttp==3.8.6` (aiogram 2.25.2 breaks on aiohttp 3.9+).
- `.github/workflows/ci.yml`: rewrote secret-check steps (`set -euo pipefail`, explicit fail-on-find).
- `tools/build_miniapp.sh` (new): export catalog/policies → bundle; tolerates missing DB.
- `tools/export_catalog.py`: writes empty catalog instead of crashing on missing DB.
- `tools/build_miniapp_bundle.py`: tolerant CSS + idempotent rebuild. Pipeline verified → `miniapp/dist/index.html` builds.
- `miniapp/catalog.json` / `policies.json` gitignored (build artifacts).
- `admin/package-lock.json`: regenerated (`npm install --package-lock-only`); `npm ci --dry-run` passes.

### P1 — money-critical (`3a990b4`)
- **4.1 EVM transfer identity:** `crypto_deposits` gains `chain_id`, `token_contract`, `log_index` columns (migration in `create_tables`);
  new `UNIQUE(chain_id, token_contract, txid, log_index)` index. Fetch functions synthesize per-tx log ordinal;
  `crypto_watcher.py` passes full identity to `claim_crypto_deposit` (now accepts `chain_id`, `token_contract`, `log_index` kwargs).
- **2.1 Stars backend enforcement:** `_place_order` rejects non-Stars payment for digital-goods carts before order creation.
  Balance deliberately excluded (crypto top-up bypass).
- **3.1 Atomic checkout:** new `db.create_checkout_atomic` wraps order + items + promo claim + cart clear in one
  `BEGIN IMMEDIATE`; `_place_order` uses it. Stock still decrements at fulfillment per existing design.

### 3.2 — transactional fulfillment (`3bd3320`)
- New `db.fulfill_order_atomic`: claims digital keys, decrements physical stock, writes delivered values, marks order
  fulfilled — all under one `BEGIN IMMEDIATE`. `handlers/common.py::fulfill_order` delegates to it; old compensation-based
  `_rollback_fulfill` removed. Verified with in-memory test (overstock → atomic rollback, stock unchanged).

### P2 — security (`bce834a`)
- **14.1/14.2 True dual control for swaps:** `rental_swap_applications` gains `approved_by_1`/`approved_by_2` columns (migration).
  First approval → `approved_1`; second approval must be a DIFFERENT admin → `approved` + tenant notified.
- **12.2 HTTPS enforcement:** `NOVA_API_URL` with remote `http://` host raises at startup (localhost exempt).
- Verified already sound: 13.1 (no hardcoded secrets), 10.1 (TON memo binding + expiry→manual review), 10.2 (`validate_init_data`
  exists; no HTTP API edge in bot to wire it to), 8.1 (Payload push best-effort, never raises).

### P3 — sweep tool hardening (`82a4b99`, `bot/tools/sweep.py`)
- EIP-1559: `maxFeePerGas`/`maxPriorityFeePerGas` from `eth_feeHistory` (1 gwei floor); all txs type 2.
- RPC validation: `eth_chainId` must match expected; refuse on syncing node or wrong chain.
- Tx journal: append-only JSON written before broadcast, updated per-tx (crash-safe).
- Doc fix (7.4): memory-wipe claim corrected to best-effort (CPython cannot guarantee wiping).

### P4 — platform (`1ee6dc5`)
- **12.x `has_rental` → `has_rental_history`:** clarifies UI-convenience-only, never authorisation. Migration backfills;
  old `set_has_rental` kept as deprecated alias. Callers in `handlers/rent.py`, `handlers/common.py` updated.
- **21.x Outbox pattern:** new `outbox_events` table; `order.created` event written in same tx as order in
  `create_checkout_atomic`. Methods: `outbox_emit`, `outbox_claim_pending` (5-min retry backoff),
  `outbox_mark_processed`, `outbox_mark_failed`.

### Test bot status (21:56 IST)
- RUNNING (PID 12626) @ `1ee6dc5` — restarted 21:48 IST with P1–P4 code. Proxy creds rotating ~minutely;
  if it dies, use a getMe-verified credential from the current shell env (file creds often dead).
- Smoke tests: 10/10 pass on all commits.

## Second re-audit fixes (2026-10-08 late evening, `refactor/nova-shop-professional`, 8 LOCAL commits — NOT yet pushed, awaiting user's PAT)

### Rent-flow corrections (`1977e1c`, pushed 22:33 IST)
User corrected the rent UI: (1) rent screen shows ONLY "Continue to Payment" + Menu — Monthly/Yearly
selector appears AFTER tapping it (plans were wrongly shown as sub-buttons on the entry screen);
(2) payment screen now has Balance / CryptoBot / **Crypto payments** (direct-crypto option was missing);
(3) removed the "link your Telegram on the website first" gate (was never the user's spec) — bot now
auto-provisions users silently via new identity endpoint `/api/internal/users/ensure`.

### Re-audit P0 — release blockers (`fd77354`)
1. CI now runs `tools/build_miniapp.sh` (was: bundler directly, bypassing exporters); `MINIAPP_FAIL_CLOSED=1` in CI.
2. Legacy `UNIQUE(chain, txid)` dropped via SQLite table-rebuild migration; event identity is solely
   `(chain_id, token_contract, tx_hash, log_index)`.
3. Observations record the REAL token contract from the chain registry (was hardcoded `'native'`).
4. Deterministic `log_index`: per-tx ordinals sorted by (block, recipient, value); documented as synthetic.
5. Testnet routing: `chain_configured()`/`enabled_chains()` use `active_chains()`; testnet chains in stablecoin set.
6. TON Connect: `create_tonconnect_order_atomic()` — order+items+payment in one tx; duplicate txid rolls back all.

### Re-audit P1 — financial integrity (`3f85748`)
7. Payment-intent model: observations link to `deposit_id`/`order_id`/`user_id` with `settled_at` (intent → observations → settlement).
8. Fiat/crypto separated: `fiat_amount_minor`/`fiat_currency` vs `crypto_amount_atomic`/`crypto_asset`/`crypto_chain`/`token_contract`.
9. ETH USDT fallback: Blockscout → Etherscan V2 (was single-source).
10. Replay: `replay_observations_from(chain, from_block)` resets cursor; dedup makes replay safe.
11. Decimal quotes: `usd_cents_to_base_units` uses `Decimal(str(price))`, no float rounding.

### Product documentation (`bf3c47f`) + founder's vision (`0c27703`)
- `docs/NOVA-SHOP-PRODUCT.md` (301 lines): what is being built (shop bot + rental SaaS), components, payment rails
  incl. Stars-exclusivity rule, rental plans/lifecycle/dual-control swaps, data model, architectural decisions,
  exact rent button flow, repo layout, glossary. Written so another AI can produce user guides/API docs/runbooks.
- §11 "The Vision — How the Founder Is Building This": best Telegram shop bot that exists; English-only;
  sleek/minimal; company-grade engineering (verify before claiming; money paths tested with real money);
  rental platform not just a bot; self-custody $0 rails; professional reusable repo; external-models-build /
  Orion-verifies division of labor; two budgets never confused; straight talk beats comfort.

### Re-audit P2 — security (`994a844`)
13. `PERM_SWAP_APPROVE` (128): swap approve/deny requires it specifically (generic role_mask no longer grants it).
14. Atomic dual-approval: conditional `UPDATE ... WHERE` on state; concurrent approvals can't overwrite each other.
15. Second-approver routing: `_notify_admins_second_approval` actually DMs eligible approvers (was a no-op).
16. `PAYLOAD_URL` HTTPS enforcement for remote hosts (same rule as `NOVA_API_URL`).
17. Legacy per-user TON claim path deleted; all flows use per-intent `TC-` codes.

### Re-audit P3 — production architecture (`5774ae8`)
18. `bot/outbox_worker.py`: exponential backoff 5min→24h, max 10 attempts; wired into `app.py`.
19. `bot/watcher_main.py` standalone entry + `nova-shop-watcher.service`; `WATCHER_STANDALONE=1` disables in-process watcher.
20. PostgreSQL path: `bot/db/` factory (`DATABASE_URL` selects backend), `PostgresDB` scaffold, `docs/P3-POSTGRESQL-MIGRATION.md` 4-phase plan. SQLite remains default.
21. DB-backed sliding-window rate limits (`bot/rate_limit.py`, `rate_limit_hits` table), multi-replica safe.
22. Versioned migrations: `bot/migrations/` + runner (m001 baseline, m002 rate_limit_hits, m003 inventory_reservations).
23. Inventory reservations: `reserve_inventory()`/`release_reservation()`/`release_expired_reservations()` — no overselling.
24. `bot/product_dto.py`: whitelisted fields, availability status instead of raw stock (anti-probing).

### Re-audit P4 — platform verification (`0e3bcb8`, docs only)
25–31 verified already built in R0–R10: identity reproducible, better-auth + Telegram login, API-key lifecycle + docs,
quota enforcement, HMAC billing webhooks, customer dashboard, public website. Documented in `docs/P4-PLATFORM-VERIFICATION.md`.

### Bot import fix (`612c710`)
- `app.py`: correct `db` import from `loader`, not `database`.

### Test bot status (2026-10-09 01:44 UTC)
- RUNNING (PID 5182) @ `612c710` — restarted 01:44 UTC after proxy-credential expiry killed the previous instance.
  Launched with a getMe-verified credential exported into the process env (NOT from the file: the minutely
  `shop-bot-proxy-refresh` cron keeps writing dead credentials — 407 on most file creds; running process is
  unaffected until its own credential rotates, then it dies and must be relaunched the same way).
- The 8 commits above are LOCAL ONLY — `git log 1977e1c..HEAD`. Push needs the user's PAT (asked 23:02 IST, awaiting).
- Deposit detection verified healthy 2026-10-09 ~09:05 IST: Polygon Blockscout 403s (Cloudflare, expected) →
  Etherscan V2 fallback engages and responds live; deposit #9 (user's 1 USDT Polygon test) has zero on-chain
  transfers — the top-up never hit the chain, nothing to sweep. Fallback is silent on empty results by design
  (no log when Etherscan returns "No transactions found"); the per-minute Blockscout 403 warnings are harmless.
  Late-sweep of deposit #9 stops after 2026-10-09 09:08 UTC (24h window).

## Pending items (need the user)

- [ ] `SUPPORT_USERNAME` in bot `.env` + BotFather description (text in `docs/TOKEN-SWAP-FLOW.md`)
- [ ] B-1: production domain for `RENTAL_PUBLIC_BASE_URL`
- [ ] B-2: live-Telegram e2e test
- [ ] B-3: `RENTAL_PANEL_URL`
- [ ] Stripe provider token, BotFather /newapp, Payload password change (older items)

## Standing rules (from the user)

- DeepSeek does hands-on work (analysis, planning, coding); Orion instructs, routes, reviews, verifies, applies, tests. Exception (disclosed): when DeepSeek fails repeatedly on mechanics, Orion implements directly from the reviewed spec and says so.
- API keys/PATs pasted in chat are used transiently once, never saved.
- "Ask me access for anything you require in one time. do not ask me multiple times."
- Never re-publish the Mini App without explicit approval.
- Bot UI is English-only, sleek/minimal.
- Never run `apt-get install -f`.
- Live `nova-shop` service stays STOPPED.
