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
- the store-credit ledger (balance_transactions) with actor/note/reference provenance, credit lots and gift cards;
- stock alerts;
- support and audit records.

### Payload CMS

Owns editorial/admin state:

- products;
- categories;
- media;
- human admin users;
- mirrored order documents;
- mirrored customers and gift cards (read models — money state stays in the bot).

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

Migrations are numbered modules in `bot/migrations/`, discovered and applied by `bot/migrations/runner.py` inside `create_tables()`, and tracked in `schema_migrations`. The current schema version is 16. m014 (store credit) added the ledger provenance columns (actor_type, actor_id, note, reference, reference_id) to `balance_transactions`, the `gift_cards` table, and `orders.origin`. m015 (post-purchase) completes the `orders.status` vocabulary (`preparing`, `completed`): where a historical table still carries the old CHECK constraint it rebuilds the table in place — rows, columns and indexes preserved, foreign keys verified — and it skips databases whose tables predate the constraint entirely. The newest, m016 (deep-audit fix programme), re-scopes the crypto derivation counters in `kv`: `xpub_index_<scope>` keys are now keyed by the xpub's config name (the derivation domain, e.g. `XPUB_ETH`) instead of per chain name — chains that share one xpub share one counter, so a derivation index can never be issued twice. The migration seeds each scoped counter from the maximum legacy per-chain value and never lowers it; the legacy per-chain keys are retained as history.

Payload itself has a formal migration workflow; production deployments should execute migrations deliberately.

Reference: https://payloadcms.com/docs/database/migrations
