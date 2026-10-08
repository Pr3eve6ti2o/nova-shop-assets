# P4: Platform Verification (re-audit items 25-31)

All P4 items were built during the rental programme (Parts 0-4, 2026-10-08).
This document verifies each item exists and is functional.

## 25. Identity/control-plane dependency reproducible ✓

- `nova-platform/nova-private/identity/package.json` — pinned dependencies
- `drizzle.config.ts` — database configuration
- `.env.example` — required environment variables documented
- `npm install && npm run db:migrate && npm run dev` reproduces the service

## 26. Customer authentication ✓

- `src/lib/auth.ts` — better-auth configuration
- `src/app/api/auth/[...all]/` — auth endpoints
- `src/app/api/auth/telegram/` — Telegram login integration
- Supports: email/password + Telegram login

## 27. API key lifecycle ✓

- `src/app/api/keys/route.ts` — POST (create, 5/hr rate limit), GET (list)
- `src/app/api/keys/[kid]/route.ts` — GET, DELETE (revoke)
- `src/app/api/keys/[kid]/stats/route.ts` — usage statistics
- `docs/API-KEYS.md` — customer documentation
- Keys are SHA-256 hashed, timing-safe comparison

## 28. Usage/quota ✓

- `src/lib/quota.ts` — per-plan quotas:
  - Monthly: 1 bot, 100 products, 1k orders/mo, 5 API keys
  - Yearly: 3 bots, 500 products, 10k orders/mo, 10 API keys
- Enforced at provisioning and API request time

## 29. Billing/webhooks ✓

- `src/lib/billing-webhooks.ts` — HMAC-SHA256 verified dispatch
- Events: subscription.created, subscription.renewed, subscription.cancelled,
  payment.failed, trial.ending
- `docs/WEBHOOKS.md` — customer documentation

## 30. Customer dashboard ✓

- `website/app/dashboard/page.tsx` — subscription status, entitlements,
  API keys, usage, referrals, team management
- `website/app/api/dashboard/` — dashboard API endpoints

## 31. Public Nova website ✓

- `website/app/page.tsx` — landing page
- `website/app/pricing/` — pricing page
- `website/app/login/` — login page
- `website/app/checkout/` — checkout flow
- `website/app/api-docs/` — API documentation
- `website/app/security/` — security page
- `docs/CUSTOMER-GUIDE.md` — customer documentation

## Summary

P4 is COMPLETE. All 7 items were built and verified during the rental
programme. No new code was needed — this was a verification pass.
