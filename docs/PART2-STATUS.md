# Part 2 Status — Customer Authentication (29) + API Keys (30)

## Already built (R0–R10)

### Authentication (`identity/src/lib/auth.ts`)
- better-auth with email/password (min 8 chars), 30-day sessions
- Telegram login: `/api/auth/telegram`, `/api/auth/telegram/link`
- Internal lookup: `/api/internal/users/by-telegram`

### API Keys (`identity/src/lib/api-keys.ts`)
- Scoped keys: `entitlements:read`, `subscriptions:read/write`, `payments:read`, `api_keys:manage`
- SHA-256 hashed storage, timing-safe comparison
- Lifecycle: ACTIVE → REVOKED/EXPIRED/ROTATED/SUSPENDED
- 24h rotation grace period
- Endpoints: `GET /api/keys` (list), `POST /api/keys` (create),
  `/api/keys/[kid]/rotate`, `/api/keys/[kid]` (revoke)

## Gaps for productisation
- [ ] Customer-facing docs for API key management
- [ ] Rate limiting on key creation (abuse prevention)
- [ ] Key usage analytics dashboard

## Verdict
Core code complete. Remaining work is docs + UX, not architecture.
