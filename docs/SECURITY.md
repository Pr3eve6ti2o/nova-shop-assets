# Nova Shop Security Model

## Security objectives

Protect:

- payment correctness;
- order and fulfillment integrity;
- administrator privileges;
- customer data;
- wallet public-derivation boundaries;
- provider credentials;
- recovery material.

## Trust boundaries

### Telegram client → bot

Treat callback data and client-visible prices as untrusted. Reload authoritative state server-side.

### Mini App → HTTP API

When an HTTP API is used, validate raw Telegram initData server-side and never trust initDataUnsafe.

Reference: https://core.telegram.org/bots/webapps

### Provider/chain → application

A provider response is an observation. Match it against the expected order, network, asset, recipient, amount and finality policy before fulfillment.

### Admin → Payload

Use collection and field-level RBAC. Payload supports operation-specific collection access and field access before changes are applied.

References:
- https://payloadcms.com/docs/access-control/overview
- https://payloadcms.com/docs/access-control/fields

## Secrets

Never commit:

- BOT_TOKEN;
- CryptoBot/API keys;
- PAYLOAD_SECRET;
- Payload API keys;
- wallet mnemonics/private keys;
- database files;
- production environment files.

Payload API keys represent a specific authenticated user and inherit that user's access controls. Use a dedicated least-privilege integration user.

Reference: https://payloadcms.com/docs/authentication/api-keys

## Wallet boundary

The online bot should receive account-level public roots only. Spending material belongs in a separate trusted signer/recovery domain.

## Incident response

On suspected payment compromise:

1. stop automatic fulfillment;
2. enable maintenance mode;
3. preserve logs/database snapshots;
4. identify affected orders/providers/networks;
5. reconcile against the chain/provider;
6. rotate affected credentials;
7. review admin/API-key activity;
8. resume only after settlement is understood.

Never delete payment evidence while investigating.

## Known limitations

The repository is security-conscious but is not an external audit or custody certification. Process-local locks are not cluster locks, external providers can fail, and the current bot/Payload database split is not one ACID transaction.
