# Professional Codebase Structure

## Current structure

The repository currently contains five runtime surfaces:

- bot/ — Telegram runtime and most business logic;
- miniapp/ — static storefront source plus generated bundle;
- admin/ — Next.js + Payload CMS;
- tools/ — synchronization/export/build scripts;
- tonconnect/, brand/, docs/ — integration, brand, and engineering assets.

This works, but several large modules mix responsibilities.

The largest examples are bot/database.py, which contains schema creation, migrations, repositories and business persistence in one module, and bot/crypto_payments.py, which combines chain configuration, pricing, provider HTTP, Wallet Core process management, and payment arithmetic.

## Target structure

~~~text
nova-shop-assets/
├── apps/
│   ├── bot/
│   │   ├── entrypoint.py
│   │   ├── config/
│   │   ├── presentation/
│   │   │   ├── handlers/
│   │   │   ├── keyboards/
│   │   │   ├── texts/
│   │   │   └── middleware/
│   │   ├── application/
│   │   │   ├── commands/
│   │   │   ├── queries/
│   │   │   └── services/
│   │   ├── domain/
│   │   │   ├── catalog/
│   │   │   ├── cart/
│   │   │   ├── orders/
│   │   │   ├── inventory/
│   │   │   ├── payments/
│   │   │   ├── customers/
│   │   │   ├── referrals/
│   │   │   ├── support/
│   │   │   └── tenants/
│   │   ├── infrastructure/
│   │   │   ├── database/
│   │   │   ├── wallet/
│   │   │   ├── chains/
│   │   │   ├── providers/
│   │   │   └── rates/
│   │   └── tests/
│   ├── admin/
│   └── miniapp/
├── packages/
│   ├── contracts/
│   ├── money/
│   ├── payment-model/
│   └── chain-model/
├── integrations/
│   ├── telegram/
│   ├── payload/
│   ├── cryptobot/
│   ├── tonconnect/
│   ├── rpc/
│   └── rates/
├── tools/
│   ├── catalog/
│   ├── payload/
│   ├── miniapp/
│   ├── wallet/
│   └── operations/
├── deploy/
│   ├── systemd/
│   ├── docker/
│   └── reverse-proxy/
├── docs/
└── brand/
~~~

## Layer rule

Telegram handlers translate updates into application commands.

Application services enforce business invariants.

Domain modules must not import Telegram, HTTP clients, Payload, or provider SDKs.

Infrastructure modules own database, provider, RPC, rates and wallet adapters.

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

Never make the domain depend on a provider.

## Migration strategy

Do not blindly move the entire repository in one commit.

1. Extract one pure domain/service function.
2. Add focused tests.
3. Route one handler group through it.
4. Move its repository/provider adapter.
5. Remove legacy implementation after all callers migrate.
6. Repeat by bounded context.

This keeps the production surface stable while the architecture improves.

## Generated assets

miniapp/dist/index.html, catalog.json, and policies.json are generated outputs.

Do not hand-edit generated bundles.

The tracked nova-shop-complete.zip should eventually move to GitHub Releases rather than remain a second source distribution in the source tree.
