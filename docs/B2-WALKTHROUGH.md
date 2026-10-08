# B-2: Interactive Walkthrough

## Status
Backend verified (all 6 schema checks pass). Bot polling as @testssscbot.

## Why this needs a human
Automated handler simulation hits import-chain issues (aiogram filter
registration requires the full dispatcher context). The bot runs fine in
production — the test harness can't replicate the dispatcher.

## Manual walkthrough steps

1. Open @testssscbot in Telegram
2. Send `/start` — verify main menu appears
3. Tap **My Rental** (or *Rent a bot* if no history)
4. Verify plan list shows Monthly/Yearly with prices from API
5. Tap a plan — verify detail screen
6. Tap **My Rental** → verify subscription status display
7. Test **Request token swap** flow (apply → reason)

## Expected results
- All text in English
- Prices match control plane ($8.99 / $89.99)
- No dead buttons
- Checkout order: Balance → Stars → Crypto

## Verified programmatically
- [x] Bot polling (PID 12626, no errors)
- [x] Database schema (6/6 checks)
- [x] Plan labels centralized (no hardcoded prices)
- [x] Smoke tests 10/10
