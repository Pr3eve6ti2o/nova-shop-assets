"""Push bot orders to the Payload CMS admin panel.

Best-effort helper used by the Telegram bot: POSTs a new order document to
Payload's Orders collection. It NEVER raises — on any failure (no config,
network error, Payload down) it just returns False so checkout is unaffected.

The maintainer wires this into handlers/checkout.py (see admin/README.md
"Order push wiring" for the exact insertion point).

Expected order dict keys:
    orderNumber (str, unique, e.g. "NS-123"), tgUserId (str),
    customerName (str), items (list of {productName, qty, priceCents}),
    totalCents (int), currency (str, default "USD"),
    paymentMethod (one of stars/card/cryptobot/crypto_self),
    status (default "pending"), rawPayload (dict, debug info)
"""
import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_ADMIN_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "admin", ".env")


def _config():
    """(PAYLOAD_URL, PAYLOAD_API_KEY) from env, falling back to admin/.env."""
    url = os.environ.get("PAYLOAD_URL", "").strip().rstrip("/")
    key = os.environ.get("PAYLOAD_API_KEY", "").strip()
    if (not url or not key) and os.path.exists(_ADMIN_ENV):
        # Security #11: use python-dotenv instead of hand-parsing (handles
        # quotes, comments, export prefixes correctly).
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(_ADMIN_ENV)
            if not url:
                url = str(vals.get("PAYLOAD_URL", "") or "").strip().rstrip("/")
            if not key:
                key = str(vals.get("PAYLOAD_API_KEY", "") or "").strip()
        except Exception:
            pass
    return url, key


def push_order_to_payload(order: dict) -> bool:
    """POST *order* to Payload CMS. Returns True on success, False otherwise.

    No-op (returns False) when PAYLOAD_URL or PAYLOAD_API_KEY is not
    configured. Never raises.
    """
    try:
        url, key = _config()
        if not url or not key:
            return False
        payload = {
            "orderNumber": order.get("orderNumber"),
            "tgUserId": str(order.get("tgUserId", "")),
            "customerName": order.get("customerName", ""),
            "items": [
                {"productName": i.get("productName", ""),
                 "qty": i.get("qty", 0),
                 "priceCents": i.get("priceCents", 0)}
                for i in (order.get("items") or [])
            ],
            "totalCents": order.get("totalCents", 0),
            "currency": order.get("currency", "USD"),
            "paymentMethod": order.get("paymentMethod"),
            "status": order.get("status", "pending"),
            "rawPayload": order.get("rawPayload") or {},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url + "/api/orders", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"users API-Key {key}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
        if not ok:
            logger.warning("payload order push returned HTTP %s", resp.status)
        return ok
    except Exception as e:  # noqa: BLE001 - best effort by design
        logger.warning("payload order push failed: %s", e)
        return False
