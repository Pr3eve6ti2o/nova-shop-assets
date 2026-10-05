# Operations Runbook

## Runtime

Run the bot and admin as separate services.

The bot currently owns Telegram updates, checkout, payment observation and fulfillment. The crypto watcher currently shares the bot process lifecycle; at scale it should become a separately leased worker so only one worker performs each sweep.

## Telemetry

Record:

- application version and commit;
- process startup/shutdown;
- database schema version;
- payment-provider health;
- chain observer/reconciliation lag;
- last successful chain cursor;
- fulfillment failures;
- catalog sync failures;
- admin authentication failures;
- webhook failures.

Never log bot tokens, provider tokens, API keys, mnemonics, private keys or recovery material.

## Webhooks

When using Telegram webhooks, configure Telegram secret_token and verify the X-Telegram-Bot-Api-Secret-Token header at the HTTP edge or bot ingress.

Reference: https://core.telegram.org/bots/api#setwebhook

## Backups

Back up:

- bot transactional database;
- Payload database;
- media;
- configuration metadata;
- wallet recovery material through the dedicated recovery procedure.

A backup is only proven after a restore drill.

## Horizontal scaling

The current user locks, rate-limit buckets and asyncio claim lock are process-local. They protect one process, not a cluster.

When scaling horizontally:

- keep SQL uniqueness and conditional writes as final correctness guards;
- use a shared database;
- move recurring jobs to a worker/queue;
- add distributed rate limits where required;
- give every worker a visible lease/heartbeat.

## Deployment sequence

~~~text
build
 ↓
static checks
 ↓
tests
 ↓
database migration
 ↓
deploy
 ↓
health check
 ↓
small end-to-end order test
 ↓
monitor
~~~

Rollbacks must account for both application and schema compatibility.
