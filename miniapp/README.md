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

## Trust model & `webapp_auth.py`

The bridge's trust anchor is Telegram itself: `sendData` payloads arrive
as `web_app_data` messages authored by the platform for the authenticated
user, so no initData check is needed (or possible — initData is not part
of a `sendData` payload). `bot/webapp_auth.py` (HMAC-SHA256 initData
validation, fully unit-tested) is therefore deliberately dormant today:
it exists for a future backend-API upgrade path where the Mini App would
call an HTTP endpoint and present initData as credentials. Do not wire
it into the sendData bridge; do not delete it as "dead code" either —
if an HTTP API is ever added, requests must pass
`validate_init_data` before any other handling.

## Rebuilding

```bash
python tools/export_catalog.py --db <live-shop-db> \
  && python tools/export_policies.py \
  && python tools/build_miniapp_bundle.py
```

The `--db` matters: the default path is the repo's placeholder DB, which
is how an empty bundle (`products: []`, no merchant TON address, TON pay
button hidden) shipped once. After rebuilding, re-publish the hosted
Mini App artifact — the bundle in this repo is not the live app.
