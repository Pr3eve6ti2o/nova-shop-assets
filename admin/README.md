# Admin — Payload CMS

Payload 3.x + Next.js admin panel for catalog, order, and user management.

Collections: `users` (roles + API keys), `categories`, `products` (botId/status/featured), `orders` (panel read/update; created via bot API only), `media`.

## Setup

```bash
npm install
cp .env.example .env   # set PAYLOAD_SECRET, DATABASE_URL
npm run dev            # → http://localhost:3001/admin
```

First login credentials are generated on first run — **change the password immediately** and delete any credential files.

## Catalog → bot sync

Catalog edits must be synced to the bot:

```bash
python ../tools/sync_payload_to_bot.py
python ../tools/export_catalog.py
python ../tools/build_miniapp_bundle.py
```
