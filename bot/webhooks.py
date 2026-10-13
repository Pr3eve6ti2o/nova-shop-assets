"""Outbound shop webhooks (port plan 6.4).

Events are written to the durable outbox as `webhook:<event>` and
delivered by the outbox worker with retry/backoff — the same machinery
as the Payload integration. Each delivery is a JSON POST:

    {"event": "order.created", "data": {...}}

signed with HMAC-SHA256 (hex) in X-Nova-Signature when
SHOP_WEBHOOK_SECRET is set — the JumpCodeFrog repo's plain shared
header was deliberately NOT copied; signatures can't be replayed
across bodies. Deliveries also carry X-Nova-Timestamp (unix
seconds), and the signature covers "<timestamp>.<body>" so a
captured delivery cannot be replayed verbatim later; receivers
should reject timestamps more than a few minutes old. No-ops
entirely when SHOP_WEBHOOK_URL is unset.
"""
import hashlib
import hmac
import json
import logging
import time

import config

logger = logging.getLogger(__name__)


async def webhook_emit(db, event: str, data: dict):
    """Queue a webhook event (fire-and-forget safe: never raises)."""
    if not getattr(config, "SHOP_WEBHOOK_URL", None):
        return
    try:
        await db.outbox_emit(f"webhook:{event}",
                             str(data.get("order_id", "")),
                             {"event": event, "data": data})
    except Exception as e:
        logger.warning("webhook_emit %s failed: %s", event, e)


def sign_body(body: bytes, timestamp: str = None) -> str:
    secret = getattr(config, "SHOP_WEBHOOK_SECRET", None) or ""
    if timestamp is not None:
        body = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def deliver_webhook(payload: dict) -> bool:
    """POST one event to the configured URL. True on a 2xx response."""
    import aiohttp
    url = getattr(config, "SHOP_WEBHOOK_URL", None)
    if not url:
        return False
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "X-Nova-Event": str(payload.get("event", ""))}
    if getattr(config, "SHOP_WEBHOOK_SECRET", None):
        ts = str(int(time.time()))
        headers["X-Nova-Timestamp"] = ts
        headers["X-Nova-Signature"] = sign_body(body, timestamp=ts)
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=body, headers=headers) as resp:
                return 200 <= resp.status < 300
    except Exception as e:
        logger.warning("webhook delivery failed: %s", e)
        return False
