# Token Swap Flow — Implementation Notes

**Branch:** `refactor/nova-shop-professional` (NOT main)
**Date:** 2026-10-08
**Status:** Implemented, smoke-tested, app boots clean. Test bot is DOWN
(sandbox egress proxy outage) so no live Telegram e2e yet.

## What the user asked for

Tenants can **apply** for a bot token swap from inside the bot, but the swap
must be **approved by the bot owner** (the admin) as a safety measure before
anything happens. Tenants reach support via the in-bot ticket flow or a
public support username published in the bot's description.

## How it works (user-visible)

1. **My Rental → "🔄 Request token swap"** (only with an active rental).
   Explainer screen mentions support contact, then asks for a reason.
2. Tenant confirms → **application created** (status `pending`) → the owner
   gets a DM: *"Token swap application #N"* with **Approve / Deny** buttons.
3. **Approve** → tenant gets "approved" DM with a **Continue** button.
   **Deny** → tenant is notified with support contact info.
4. Tenant taps Continue → pastes the **new** BotFather token → token is
   validated via `getMe` → verified swap starts via the control plane:
   proof-of-control challenge (code shown, tenant sends it to the NEW bot,
   taps "I've sent it") → on pass the swap **executes automatically**.
   The owner's earlier approval acts as `approver_2` (dual control).
5. **"💬 Contact support"** button on the My Rental screen: deep-links to
   `t.me/<SUPPORT_USERNAME>` when configured, otherwise opens the in-bot
   ticket list (`/support` flow).

## Files changed

| File | Change |
|---|---|
| `bot/handlers/rent_swap.py` | **New.** Full flow: application FSM, owner approve/deny (admin-gated), token paste + validation, challenge, auto-execute. Callback namespace `rswap:*`. Local SQLite table `rental_swap_applications`. Token lives only in FSM memory, never logged, wiped on every terminal path; pasted message deleted best-effort. |
| `bot/handlers/__init__.py` | Register `rent_swap` (after `rent_token`). |
| `bot/handlers/rent.py` | `_rent_success_kb()` gains "🔄 Request token swap" + "💬 Contact support" buttons. |
| `bot/states.py` | New `SwapFlow` (`waiting_reason`, `waiting_token`). |
| `bot/config.py` | New `SUPPORT_USERNAME` env (stripped of leading `@`). |

## Control-plane endpoints used (identity service, x-api-key)

- `GET /api/internal/rental/tenants/by-user?user_id=` → tenant id
- `GET /api/internal/rental/tenants/{id}/overview` → current bot instance
- `POST /api/internal/rental/token/validate` `{token}` → getMe validation
- `POST /api/internal/rental/support/swaps` → initiateSwap (returns
  `swap_id`, `challenge_id`, `code`); body: `tenant_id`, `new_token`,
  `ticket_ref`, `actor`, `owner_telegram_id`, `owner_user_id`
- `GET /api/internal/rental/token/challenge?nonce=` → poll `passed`/`pending`
- `POST /api/internal/rental/support/swaps/{id}/execute`
  `{actor, approver_2}` → performs the swap after challenge pass

## Setup required (one-time, by the human owner)

1. Set `SUPPORT_USERNAME` in the bot `.env` (e.g. `SUPPORT_USERNAME=myhelpdesk`).
   **Do not commit the .env.**
2. Set the bot's **description** in @BotFather → /setdescription to:

```
Nova Shop — your Telegram storefront, powered by Nova.

Rent your own shop bot, manage products and orders, accept crypto.

Support: @<SUPPORT_USERNAME> (or tap Contact support in the bot)
```

3. (Optional) `/setabouttext`: `Nova Shop rental platform. Support: @<SUPPORT_USERNAME>`

## Testing done

- `bot/tests/test_smoke.py`: **ALL 10 GROUPS PASSED** (config parsing incl.
  `SUPPORT_USERNAME`, callback-data < 64 bytes audit incl. new `rswap:*`
  callbacks, DB round-trip, crypto).
- `bot/app.py` boots cleanly through all imports (reaches Telegram connect;
  blocked only by the sandbox proxy outage, unrelated).

## Not done / known limits

- No live Telegram e2e (proxy down). When the proxy recovers, test: apply →
  approve → paste token → challenge → execute on a throwaway bot.
- `SUPPORT_USERNAME` is empty until the owner sets it; the Contact button
  then falls back to the in-bot ticket list.
- Swap applications live in the bot's local SQLite (`rental_swap_applications`);
  the verified swap itself lives in the control plane (`rental_support_swaps`).
