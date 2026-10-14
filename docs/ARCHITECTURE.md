# Nova Shop Architecture

## Runtime topology

~~~text
                    Telegram
                       |
             +---------+---------+
             |                   |
          Bot API            Mini App
             |                   |
             v                   v
        Bot application      static UI
             |
      +------+------+
      |             |
      v             v
 Transactional   Integration
    database      adapters
      |             |
      |       +-----+----------------+
      |       |     |        |       |
      v       v     v        v       v
    orders  Stars  CryptoBot chains Payload
      |                       |
      +-----------+-----------+
                  v
             fulfillment
~~~

Store-credit traffic adds one hop: the Payload panel calls the bot's internal API (aiohttp, served by the bot process on localhost) for customer accounts, gift cards, manual orders and refunds. For money, the panel is a client of the bot — never a writer.

## Architectural rules

1. The client proposes; the server decides.
2. The bot database is the current transaction ledger.
3. Payload is the catalog/admin CMS and order mirror.
4. Payment evidence is retained separately from the business decision.
5. Fulfillment is idempotent and retryable.
6. Provider adapters do not own business truth.
7. Generated Mini App artifacts are outputs, never independent sources.
8. Payload never writes the bot database; panel money actions go through the bot internal API with idempotency keys.

## Current technology

- Python bot using aiogram 2.25.2.
- Async SQLite using aiosqlite for the current bot deployment.
- Next.js 16.3.3 + Payload 3.90.2 admin.
- Payload currently uses the SQLite adapter.
- Vanilla JavaScript Telegram Mini App.
- TON Connect for blockchain payment interaction.
- Trust Wallet Core for HD wallet derivation.
- External chain, rate and payment providers through HTTP adapters.
- Pricing: the shared `pricing-engine/` package (Dinero.js 2 + Decimal.js) serves the Mini App, parity-tested against the bot's Python totals, which remain authoritative.
- Panel↔bot money actions: the bot's localhost internal API (shared secret, idempotency keys on mutations).

## Target bounded contexts

~~~text
Catalog
Customers
Cart
Orders
Inventory
Payments
Wallet
Fulfillment
Referrals
Support
Tenancy
Integrations
Admin
~~~

Handlers should be thin. Application services enforce business rules. Domain code must not import Telegram, HTTP clients, Payload or payment-provider implementations.

The intended dependency direction is:

~~~text
interface
   ↓
application
   ↓
domain
   ↓
ports
   ↓
infrastructure
~~~

## Scaling boundary

The current crypto watcher runs inside the bot process. For horizontal scaling it should move behind a worker lease or queue so two bot instances cannot independently own the same sweep.

The current in-memory locks and rate limits are also process-local.
