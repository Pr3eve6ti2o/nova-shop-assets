# Nova Shop Documentation

Nova Shop is a Telegram-native commerce platform composed of a Telegram Bot, Telegram Mini App, Payload CMS admin, payment and blockchain integrations, catalog synchronization tools, and deployment assets.

## Documentation map

| Area | Document |
|---|---|
| System architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Security and threat model | [SECURITY.md](SECURITY.md) |
| Payment architecture | [PAYMENTS.md](PAYMENTS.md) |
| Data ownership and synchronization | [DATA-MODEL.md](DATA-MODEL.md) |
| Current target structure | [CODEBASE-STRUCTURE.md](CODEBASE-STRUCTURE.md) |
| Operations runbook | [OPERATIONS.md](OPERATIONS.md) |
| Release checklist | [RELEASE.md](RELEASE.md) |
| Deployment | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Product specification | [SPEC.md](SPEC.md), [SPEC2.md](SPEC2.md) |
| Previous audit | [AUDIT-2026-09-30.md](AUDIT-2026-09-30.md) |
| Current deep audit | [AUDIT-2026-10-05.md](AUDIT-2026-10-05.md) |

## Source-of-truth rules

- Payload is the catalog authoring source of truth.
- Bot SQLite is the current transactional commerce store.
- Payment observations and fulfillment state belong to the bot transactional domain.
- Mini App catalog/policy JSON and the dist bundle are generated artifacts.
- Wallet public derivation is an integration boundary, not business logic.
- Legal copy has one source in the bot and is exported to the Mini App.
- Bootstrap/seed scripts are not the routine synchronization mechanism.

## Trust boundary

The Mini App is an untrusted client. Any future HTTP API using Telegram Mini App identity must validate raw initData server-side and must never trust initDataUnsafe. Telegram documents these requirements at https://core.telegram.org/bots/webapps.

The current sendData bridge is intentionally handled as a Telegram bot update. The bot still reloads authoritative catalog, prices, stock, and payment state instead of trusting client-side totals.

## Repository status

This is an active application repository, not a demo-only template. It already contains a broad commerce feature set, but the architecture is still a staged monolith with a dual-database boundary.

The professionalization work is focused on explicit ownership, secure payment verification, durable migrations, least-privilege administration, clearer integrations, and a staged migration path.
