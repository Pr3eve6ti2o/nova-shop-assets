# Release Checklist

## Code

- Python compilation and smoke tests pass.
- Admin npm lockfile is used consistently.
- Admin lint/build/unit tests pass.
- Mini App bundle is reproducible from source.
- No database/archive/secrets are accidentally committed.
- Changed payment logic has replay and failure tests.

## Commerce

- Digital in-Telegram orders expose Telegram Stars only where required by Telegram's current rules.
- Physical/service order payment rails are explicitly classified.
- Client-provided totals are ignored.
- Payment identity is chain-specific.
- Underpayment/top-up behavior is tested.
- Late payment behavior is tested.
- Reorg/finality behavior is tested.
- Fulfillment is idempotent.
- Inventory claims are atomic.
- Promo usage is safe under concurrency.

## Admin

- Staff cannot edit financial/settlement fields.
- Role changes are admin-only.
- API-key access is least-privilege.
- PAYLOAD_SECRET is non-empty.
- Production migrations are explicit.

## Mini App

- HTTP APIs validate raw Telegram initData server-side.
- initDataUnsafe is never authoritative.
- sendData payloads are schema-validated and re-priced server-side.
- TON Connect network, recipient, amount and expiry are verified server-side.

## Operations

- HTTPS is active.
- Telegram webhook secret is verified.
- Database backups and restoration are tested.
- Payment reconciliation has been exercised after a simulated outage.
- Recovery procedure has been rehearsed.
- Release tag and configuration version are recorded.

References:
- https://core.telegram.org/bots/webapps
- https://core.telegram.org/bots/payments-stars
- https://core.telegram.org/bots/api#setwebhook
- https://payloadcms.com/docs/access-control/overview
