"""Internal API for the Payload admin (store-credit plan, Phase 3).

Why this exists: Payload runs on its own database and must never write
the bot's SQLite file — every money invariant (credit lots, the ledger,
guarded deductions) lives in the bot's DB layer. So Payload's store-
credit actions call this localhost-only HTTP API, and the bot performs
them through the same db.* methods the Telegram admin flows use.

Security shape: binds 127.0.0.1 only; every /internal/* request needs
the shared secret in X-Nova-Internal-Key (constant-time compare);
every mutation needs an Idempotency-Key — a replayed key returns the
stored first response and never moves money twice. Disabled by default
(INTERNAL_API_PORT=0); refuses to start with a short secret.
"""
import hmac
import json
import logging

from aiohttp import web

import config

log = logging.getLogger(__name__)

MAX_ADJUST_CENTS = 1_000_000  # $10,000 — mirrors handlers/admin/store_credit
SECRET_HEADER = "X-Nova-Internal-Key"


def _err(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": message, "code": code}, status=status)


@web.middleware
async def _auth(request: web.Request, handler):
    if request.path.startswith("/internal/"):
        key = request.headers.get(SECRET_HEADER, "")
        if not hmac.compare_digest(key, request.app["secret"]):
            return _err(401, "unauthorized", "bad or missing internal key")
    return await handler(request)


async def _body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _actor(body: dict) -> str:
    return str(body.get("actor") or "payload")[:64]


async def _idem_replay(request: web.Request):
    """Return the stored first response for this Idempotency-Key, or
    None when the key is fresh. Raises web.HTTPBadRequest (as a 400
    response) when a mutation arrives without a key."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, _err(400, "idempotency_key_required",
                          "mutations require an Idempotency-Key header")
    raw = await request.app["db"].kv_get(f"idem:{key}")
    if raw:
        return web.json_response(json.loads(raw)), None
    return None, None


async def _idem_save(request: web.Request, payload: dict) -> None:
    key = request.headers.get("Idempotency-Key")
    if key:
        await request.app["db"].kv_set(f"idem:{key}", json.dumps(payload))


def _customer_view(user, stats: dict, lots_total: int) -> dict:
    return {
        "tg_id": int(user["tg_id"]), "user_id": int(user["id"]),
        "name": user["name"],
        "balance_cents": stats["balance_cents"],
        "total_credits_cents": stats["total_credits_cents"],
        "total_debits_cents": stats["total_debits_cents"],
        "transactions": stats["transactions"],
        "lots_total_cents": lots_total,
    }


async def _get_user_or_404(request: web.Request):
    db = request.app["db"]
    try:
        tg_id = int(request.match_info["tg_id"])
    except (KeyError, ValueError):
        return None, _err(400, "bad_tg_id", "tg_id must be an integer")
    user = await db.get_user_by_tg(tg_id)
    if not user:
        return None, _err(404, "customer_not_found", "no such customer")
    return user, None


async def get_customer(request: web.Request) -> web.Response:
    user, err = await _get_user_or_404(request)
    if err:
        return err
    db = request.app["db"]
    stats = await db.account_stats(user["id"])
    lots = await db.credit_lots_total(user["id"])
    return web.json_response(_customer_view(user, stats, lots))


async def list_transactions(request: web.Request) -> web.Response:
    user, err = await _get_user_or_404(request)
    if err:
        return err
    try:
        limit = min(max(int(request.query.get("limit", 50)), 1), 200)
        offset = max(int(request.query.get("offset", 0)), 0)
    except ValueError:
        return _err(400, "bad_pagination", "limit/offset must be integers")
    rows = await request.app["db"].list_balance_transactions(
        user["id"], limit=limit, offset=offset)
    return web.json_response({"transactions": [dict(r) for r in rows]})


async def _adjust(request: web.Request, sign: int) -> web.Response:
    replay, err = await _idem_replay(request)
    if err:
        return err
    if replay:
        return replay
    user, err = await _get_user_or_404(request)
    if err:
        return err
    body = await _body(request)
    amount = body.get("amount_cents")
    note = str(body.get("note") or "").strip()
    if not isinstance(amount, int) or not 0 < amount <= MAX_ADJUST_CENTS:
        return _err(400, "bad_amount",
                    "amount_cents must be an integer in 1..1000000")
    if not 1 <= len(note) <= 500:
        return _err(400, "note_required",
                    "a note of 1..500 characters is required")
    db = request.app["db"]
    new_bal = await db.adjust_balance(
        user["id"], sign * amount,
        tx_type="admin_credit" if sign > 0 else "admin_debit",
        actor_type="payload", actor_id=_actor(body), note=note,
        reference="payload")
    if new_bal is None:
        return _err(409, "insufficient_balance",
                    "debit exceeds the customer's balance")
    await db.audit(0, "api_credit" if sign > 0 else "api_debit",
                   f"tg={user['tg_id']} amount={amount} "
                   f"actor={_actor(body)}")
    payload = {"tg_id": int(user["tg_id"]), "balance_cents": new_bal,
               "applied_cents": sign * amount}
    await _idem_save(request, payload)
    return web.json_response(payload)


async def credit(request: web.Request) -> web.Response:
    return await _adjust(request, +1)


async def debit(request: web.Request) -> web.Response:
    return await _adjust(request, -1)


async def giftcard_create(request: web.Request) -> web.Response:
    replay, err = await _idem_replay(request)
    if err:
        return err
    if replay:
        return replay
    body = await _body(request)
    value = body.get("value_cents")
    days = body.get("expires_days")
    note = body.get("note")
    if not isinstance(value, int) or not 0 < value <= MAX_ADJUST_CENTS:
        return _err(400, "bad_amount",
                    "value_cents must be an integer in 1..1000000")
    if days is not None and (not isinstance(days, int)
                             or not 0 <= days <= 3650):
        return _err(400, "bad_expiry", "expires_days must be in 0..3650")
    if note is not None and len(str(note)) > 500:
        return _err(400, "note_too_long", "note must be <= 500 characters")
    db = request.app["db"]
    card = await db.giftcard_create(
        value, created_by=f"payload:{_actor(body)}",
        note=str(note) if note else None, expires_days=days or None)
    await db.audit(0, "api_giftcard_create",
                   f"card {card['id']} value={value} actor={_actor(body)}")
    payload = {"id": int(card["id"]), "code": card["code"],
               "value_cents": int(card["value_cents"]),
               "remaining_cents": int(card["remaining_cents"]),
               "status": card["status"], "expires_at": card["expires_at"]}
    await _idem_save(request, payload)
    return web.json_response(payload, status=201)


async def giftcard_revoke(request: web.Request) -> web.Response:
    replay, err = await _idem_replay(request)
    if err:
        return err
    if replay:
        return replay
    try:
        card_id = int(request.match_info["card_id"])
    except (KeyError, ValueError):
        return _err(400, "bad_card_id", "card id must be an integer")
    db = request.app["db"]
    card = await db.giftcard_get_by_id(card_id)
    if not card:
        return _err(404, "gift_card_not_found", "no such gift card")
    if not await db.giftcard_revoke(card_id):
        return _err(409, "not_revocable",
                    "only an active gift card can be revoked")
    body = await _body(request)
    await db.audit(0, "api_giftcard_revoke",
                   f"card {card_id} actor={_actor(body)}")
    payload = {"id": card_id, "status": "revoked"}
    await _idem_save(request, payload)
    return web.json_response(payload)


async def manual_order(request: web.Request) -> web.Response:
    replay, err = await _idem_replay(request)
    if err:
        return err
    if replay:
        return replay
    body = await _body(request)
    tg_id = body.get("tg_id")
    kind = body.get("kind")
    items_in = body.get("items")
    if not isinstance(tg_id, int) or kind not in ("comp", "balance"):
        return _err(400, "bad_order",
                    "tg_id (int) and kind ('comp'|'balance') are required")
    if not isinstance(items_in, list) or not items_in:
        return _err(400, "bad_items", "items must be a non-empty list")
    items = []
    for it in items_in:
        try:
            items.append((int(it["product_id"]), int(it["qty"])))
        except (KeyError, TypeError, ValueError):
            return _err(400, "bad_items",
                        "each item needs integer product_id and qty")
    db = request.app["db"]
    user = await db.get_user_by_tg(tg_id)
    if not user:
        return _err(404, "customer_not_found", "no such customer")
    order_id, reason = await db.create_manual_order(
        user["id"], items, kind=kind, actor_tg_id=0,
        note=str(body.get("note") or "")[:500] or None)
    if not order_id:
        if reason == "insufficient_balance":
            return _err(409, "insufficient_balance",
                        "the customer's balance does not cover this order")
        return _err(400, reason or "bad_order", f"cannot create: {reason}")
    order = await db.get_order(order_id)
    payload = {"order_id": int(order_id), "status": order["status"],
               "total_cents": int(order["total_cents"]),
               "payment_method": order["payment_method"],
               "origin": order["origin"]}
    await _idem_save(request, payload)
    return web.json_response(payload, status=201)


async def refund_to_credit(request: web.Request) -> web.Response:
    replay, err = await _idem_replay(request)
    if err:
        return err
    if replay:
        return replay
    try:
        order_id = int(request.match_info["order_id"])
    except (KeyError, ValueError):
        return _err(400, "bad_order_id", "order id must be an integer")
    db = request.app["db"]
    order = await db.get_order(order_id)
    if not order:
        return _err(404, "order_not_found", "no such order")
    body = await _body(request)
    refunds = await db.refunds_for_order(order_id)
    already = sum(int(r["amount_cents"]) for r in refunds)
    remaining = int(order["total_cents"]) - already
    amount = body.get("amount_cents")
    if amount is None:
        amount = remaining
    if not isinstance(amount, int) or amount <= 0 or amount > remaining:
        return _err(409, "nothing_refundable",
                    "amount must be within the refundable remainder")
    note = str(body.get("note") or "").strip()[:500] \
        or "refund to store credit (Payload)"
    try:
        await db.record_refund(order_id, order["user_id"], amount,
                               "balance", admin_id=None, note=note)
    except ValueError as e:
        return _err(409, "refund_rejected", str(e))
    new_bal = await db.add_balance(
        order["user_id"], amount, tx_type="refund", order_id=order_id,
        actor_type="payload", actor_id=_actor(body), note=note,
        reference="refund", reference_id=str(order_id))
    status = order["status"]
    if already + amount >= int(order["total_cents"]):
        await db.set_order_status(order_id, "refunded")
        status = "refunded"
    payload = {"order_id": order_id, "refunded_cents": amount,
               "total_refunded_cents": already + amount,
               "remaining_cents": remaining - amount,
               "customer_balance_cents": new_bal, "status": status}
    await _idem_save(request, payload)
    return web.json_response(payload)


async def get_order(request: web.Request) -> web.Response:
    try:
        order_id = int(request.match_info["order_id"])
    except (KeyError, ValueError):
        return _err(400, "bad_order_id", "order id must be an integer")
    db = request.app["db"]
    order = await db.get_order(order_id)
    if not order:
        return _err(404, "order_not_found", "no such order")
    items = await db.get_order_items(order_id)
    return web.json_response({
        "order": {k: order[k] for k in (
            "id", "user_id", "status", "subtotal_cents", "discount_cents",
            "total_cents", "payment_method", "origin", "created_at",
            "updated_at")},
        "items": [dict(i) for i in items]})


def create_app(db, secret: str) -> web.Application:
    app = web.Application(middlewares=[_auth])
    app["db"] = db
    app["secret"] = secret
    r = app.router
    r.add_get("/healthz", lambda req: web.json_response({"ok": True}))
    r.add_get("/internal/customers/{tg_id}", get_customer)
    r.add_get("/internal/customers/{tg_id}/transactions", list_transactions)
    r.add_post("/internal/customers/{tg_id}/credit", credit)
    r.add_post("/internal/customers/{tg_id}/debit", debit)
    r.add_post("/internal/gift-cards", giftcard_create)
    r.add_post("/internal/gift-cards/{card_id}/revoke", giftcard_revoke)
    r.add_post("/internal/orders/manual", manual_order)
    r.add_post("/internal/orders/{order_id}/refund-to-credit",
               refund_to_credit)
    r.add_get("/internal/orders/{order_id}", get_order)
    return app


async def start_internal_api(db):
    """Start the API if configured; returns the AppRunner or None.

    Fail-closed: a missing/short secret disables the API (with a loud
    log) instead of ever running unauthenticated."""
    port = int(getattr(config, "INTERNAL_API_PORT", 0) or 0)
    secret = getattr(config, "INTERNAL_API_SECRET", "") or ""
    if not port:
        return None
    if len(secret) < 32:
        log.error("INTERNAL_API_PORT is set but INTERNAL_API_SECRET is "
                  "missing or shorter than 32 chars — API NOT started")
        return None
    runner = web.AppRunner(create_app(db, secret))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    log.info("Internal API listening on 127.0.0.1:%d (Payload)", port)
    return runner
