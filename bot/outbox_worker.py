"""Outbox worker (re-audit P3.18).

Replaces fire-and-forget asyncio.create_task() delivery with a durable
outbox pattern:

    DB transaction -> outbox_events -> worker -> Payload -> retry/backoff

The worker runs as a background asyncio task in the bot process (single
replica). For multi-replica production, use a distributed lock or a
dedicated worker process (see P3.19/P3.20).

Retry policy: exponential backoff (5min, 25min, 2h, ...), max 10 attempts.
Failed events are marked failed after exhausting retries.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# Backoff schedule in seconds: 5min, 15min, 1h, 4h, then 24h
_BACKOFF = [300, 900, 3600, 14400, 86400]


def _backoff_delay(attempts: int) -> int:
    idx = min(attempts - 1, len(_BACKOFF) - 1)
    return _BACKOFF[idx]


async def _deliver_payload_order(payload: dict) -> bool:
    """Deliver an order.created event to Payload CMS."""
    from payload_hooks import push_order_to_payload
    try:
        return await asyncio.to_thread(push_order_to_payload, payload)
    except Exception as e:
        logger.warning("outbox payload delivery failed: %s", e)
        return False


async def process_outbox_once(db, limit: int = 10) -> int:
    """Process one batch of pending outbox events. Returns count delivered."""
    events = await db.outbox_claim_pending(limit)
    delivered = 0
    for ev in events:
        ev_id = ev["id"]
        ev_type = ev["event_type"]
        try:
            payload = json.loads(ev["payload"])
        except Exception:
            await db.outbox_mark_failed(ev_id, "invalid_payload")
            continue

        ok = False
        if ev_type == "order.created":
            ok = await _deliver_payload_order(payload)
        else:
            logger.warning("outbox: unknown event type %s (id=%s)", ev_type, ev_id)

        if ok:
            await db.outbox_mark_processed(ev_id)
            delivered += 1
        else:
            attempts = (ev["attempts"] or 0) + 1
            if attempts >= 10:
                await db.outbox_mark_failed(ev_id, "max_retries")
                logger.error("outbox: event %s failed after 10 attempts", ev_id)
            # else: next_attempt_at already set by claim; will retry
    return delivered


async def outbox_worker_loop(db, interval: int = 30):
    """Background loop: poll outbox every `interval` seconds."""
    logger.info("outbox worker started (interval=%ss)", interval)
    while True:
        try:
            n = await process_outbox_once(db)
            if n:
                logger.info("outbox: delivered %d event(s)", n)
        except Exception as e:
            logger.exception("outbox worker error: %s", e)
        await asyncio.sleep(interval)
