# Data Ownership & Synchronization

## Current ownership

### Bot SQLite

Owns live transactional commerce state:

- Telegram users;
- carts and wishlists;
- orders and order items;
- payment records;
- direct crypto deposits;
- CryptoBot invoices;
- balances and referrals;
- stock alerts;
- support and audit records.

### Payload CMS

Owns editorial/admin state:

- products;
- categories;
- media;
- human admin users;
- mirrored order documents.

## Important distinction

The system currently has two databases. A successful bot transaction and a successful Payload update are not one ACID transaction.

payload_hooks.py is intentionally best-effort. It is therefore an administrative mirror, not the financial ledger.

## Preferred production direction

For a growing multi-process store, prefer a shared Postgres business database where cross-process transactional consistency matters. Payload supports Postgres through its Drizzle adapter and provides a migration workflow.

Reference: https://payloadcms.com/docs/database/postgres

A lower-risk alternative is keeping the databases split and adding a durable outbox:

~~~text
bot transaction
   ↓ same database transaction
outbox event
   ↓
delivery worker
   ↓
Payload
   ↓
retry / dead-letter / success
~~~

## Catalog direction

Payload remains the canonical catalog editor.

~~~text
Payload publish
      ↓
catalog sync
      ↓
bot catalog
      ↓
Mini App export
      ↓
generated bundle
~~~

The reverse seed_from_bot.py script is a bootstrap/migration utility, not the routine source-of-truth mechanism.

## Migration discipline

bot/database.py currently performs opportunistic ALTER TABLE statements and suppresses broad exceptions.

Replace this with numbered migrations and explicit schema-version tracking.

Payload itself has a formal migration workflow; production deployments should execute migrations deliberately.

Reference: https://payloadcms.com/docs/database/migrations
