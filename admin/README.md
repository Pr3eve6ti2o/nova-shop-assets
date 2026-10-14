# Admin — Payload CMS

Payload 3.x + Next.js admin panel for catalog, order, and user management.

Collections: `users` (roles + API keys), `categories`, `products` (botId/status/featured), `orders` (panel read/update; created via bot API only), `customers` and `gift-cards` (read-model mirrors of the bot, synced through the bot internal API), `media`.

## Setup

```bash
npm install
cp .env.example .env   # set PAYLOAD_SECRET (≥ 32 chars), DATABASE_URL
npm run dev            # → http://localhost:3001/admin
```

## Store credit (bot internal API)

The Customers and Gift Cards screens act on the bot's ledger through its localhost internal API: credit/debit with a mandatory note, gift-card create/revoke, manual orders, refund-to-credit, and buyer-info write-back on unshipped orders. Set `NOVA_BOT_API_URL` / `NOVA_BOT_API_SECRET` in `.env` (the secret must match the bot's `INTERNAL_API_SECRET`). With them unset, those actions report "not configured" and the rest of the panel works normally. Payload never writes the bot database.

First login credentials are generated on first run — **change the password immediately** and delete any credential files.

## Catalog → bot sync

Catalog edits must be synced to the bot:

```bash
python ../tools/sync_payload_to_bot.py
python ../tools/export_catalog.py
python ../tools/build_miniapp_bundle.py
```
