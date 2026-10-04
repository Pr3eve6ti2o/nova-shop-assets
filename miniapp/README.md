# Mini App — Nova Shop Storefront

Vanilla JS single-file Telegram Mini App. No framework, no build step beyond concatenation — the bundle is assembled by `tools/build_miniapp_bundle.py`.

## Structure

```
miniapp/
├── app.js        # all logic (~1,800 lines)
├── styles.css    # Telegram-themed design system
├── index.html    # shell
└── dist/
    └── index.html  # built bundle (132 KB) — this is what gets published
```

## Features

Home grid · product sheets (specs, FAQ, reviews, bundles, share) · filters (price, stock, sale, rating) · sort · wishlist · search suggestions · cart with undo · promo codes · TON Connect payments · stock alerts · order history · referral links · recently viewed.

## State & persistence

- `Telegram.WebApp.CloudStorage` for cart, wishlist, searches, alerts, recent views (no localStorage).
- Catalog is embedded at build time via `tools/export_catalog.py`.

## Telegram platform notes

- `tg.sendData()` **closes the Mini App** — fire-and-forget syncs are queued and piggybacked on checkout instead.
- Cart is cleared *before* `sendData` (post-send code never runs), with restore-on-failure.
- `pruneCart`/`pruneWish` are gated on catalog readiness (fixes a race that wiped carts).

## Rebuilding

```bash
python tools/export_catalog.py && python tools/build_miniapp_bundle.py
```
