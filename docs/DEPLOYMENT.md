# Nova Shop Deployment

## Development

### Bot

~~~bash
cd bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
~~~

### Admin

The admin application tracks package-lock.json, so use npm consistently:

~~~bash
cd admin
npm ci
npm run dev
~~~

### Mini App

~~~bash
python tools/export_catalog.py
python tools/export_policies.py
python tools/build_miniapp_bundle.py
~~~

Publish the generated dist/index.html only after the bundle checks pass.

## Production process split

Prefer separate process identities for:

- bot API/polling;
- crypto/reconciliation worker;
- Payload admin;
- reverse proxy/TLS.

The current code can run the watcher inside the bot process, but horizontal deployments must introduce a worker lease/queue to prevent duplicate sweeps.

## Database

The current bot and Payload deployments use SQLite separately. This is acceptable for a small deployment only when the consistency boundary is understood.

For growth, shared Postgres is the preferred direction where cross-process transactions matter. Payload supports Postgres through its Drizzle adapter.

Reference: https://payloadcms.com/docs/database/postgres

## Migrations

Do not rely on startup ALTER TABLE statements that silently ignore errors. Use numbered bot migrations.

Use Payload's formal migration workflow in production.

Reference: https://payloadcms.com/docs/database/migrations

## Telegram webhooks

Configure Telegram secret_token and verify X-Telegram-Bot-Api-Secret-Token at the ingress boundary.

Reference: https://core.telegram.org/bots/api#setwebhook

## Backups

Back up databases, media and operational configuration. Keep wallet recovery material on a separate recovery path.

A backup is proven only after a restore drill.
