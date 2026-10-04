# Security

## Model

- **Secrets:** `.env`, `secrets/`, `data/`, `admin/.env` are gitignored (0600 on disk). Seed is AES-256-GCM encrypted.
- **No secrets in code or logs.** Verified by audit.
- **SQL:** all queries parameterized; no f-string SQL.
- **XSS:** Mini App uses `esc()` on all interpolated data; bot HTML messages escape DB strings via `utils.h()`.

## Payment verification

- **TON Connect:** sender address must match the claimed sender; tx must be within 15 minutes; amount in integer nanotons (no slippage); txid claimed via unique constraint (no replay/double-spend).
- **Direct crypto:** address derivation via official Trust Wallet wallet-core; watchers match on address + amount + confirmations.
- **CryptoBot:** HMAC webhook verification available.

## Auth

- Admin actions gated by permission bitmask (`IsAdmin`) at the dispatcher layer.
- Order/ticket/support reads verify `user_id` ownership (no IDOR).
- `initData` HMAC validation in `webapp_auth.py` (for future HTTP API routes).

## Hardening backlog

- Run bot as non-root systemd user with `NoNewPrivileges`.
- Persist rate-limiter buckets in SQLite (currently in-memory).
- Rotate Payload admin credentials; delete credential files.

See [AUDIT-2026-09-30.md](AUDIT-2026-09-30.md) for the full audit.
