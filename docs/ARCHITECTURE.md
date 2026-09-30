# Architecture

## System overview

```
┌─────────────┐     sendData      ┌──────────────┐
│  Mini App   │ ───────────────► │     Bot      │──► Telegram API
│ (static JS) │ ◄─────────────── │  (aiogram)   │
└─────────────┘   bot messages   └──────┬───────┘
                                       │ thread
                                       ▼
                                ┌──────────────┐     ┌───────────┐
                                │ Payload CMS  │◄────│  SQLite   │
                                │  (Next.js)   │     │ (bot DB)  │
                                └──────────────┘     └───────────┘
```

## Payment rails

| Rail | Flow |
|---|---|
| Telegram Stars | Native invoice → `successful_payment` |
| Card | Telegram provider token |
| CryptoBot | Invoice API + 60s recovery poller |
| Direct crypto (BTC/ETH/TRX) | HD-derived deposit address per order, chain watchers |
| TON Connect | Wallet `sendTransaction` → toncenter verification (sender + amount + 15-min window, txid claimed) |
| COD | Physical goods only |

## Money invariants

1. Integer cents everywhere; no floats in payment math.
2. Every payment claim is idempotent (`UNIQUE(provider, external_id)`).
3. Stock, promos, deposits use atomic single-statement guards.
4. Fulfillment goes through `fulfill_order()` — never inline.
5. Cancelled orders are never finalized (watcher bails + alerts admin).
6. Promo claims release on every cancellation path.

## Background jobs

`crypto_watcher_loop` (60s): direct-deposit sweeps, late-deposit bucket, CryptoBot recovery, TON Connect pending sweep, CryptoBot invoice expiry.

## Mini App ↔ bot contract

The Mini App is static; all mutations go through `tg.sendData()` (which closes the app):
- `{items, promo}` → order checkout
- `{type:"tonconnect_paid", …}` → TON verification
- `{type:"stock_alert"}` → queued, piggybacked on checkout
- `{type:"get_orders"}` / `{type:"get_referral"}` → bot replies in chat
