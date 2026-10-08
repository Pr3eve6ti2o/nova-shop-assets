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
