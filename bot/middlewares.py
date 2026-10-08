"""Middlewares: rate limiting, maintenance gate, callback-answer safety.

Registered once via dp.setup_middleware(); the dispatcher fans the
on_pre_process_* / on_process_* / on_post_process_* hooks out to every
update type (message, callback_query, ...). Raising CancelHandler in a
pre_process hook skips the handler.
"""
import logging
import time
from collections import deque

from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware

import config
import texts

logger = logging.getLogger(__name__)

RATE_WINDOW = 60          # seconds
RATE_GLOBAL = 30          # actions per window per user
RATE_PAYMENT = 5          # payment attempts per window per user
_ADMIN_CACHE = {}
_ADMIN_CACHE_TTL = 5      # seconds


async def _is_admin(db, tg_id: int, perm: int = None) -> bool:
    if tg_id in config.ADMINS:
        return True
    if perm is None:
        perm = config.PERM_ALL
    now = time.monotonic()
    cached = _ADMIN_CACHE.get((tg_id, perm))
    if cached and now - cached[0] < _ADMIN_CACHE_TTL:
        return cached[1]
    user = await db.get_user_by_tg(tg_id)
    if not user:
        result = False
    else:
        result = bool((user["role_mask"] or 0) & perm)
    _ADMIN_CACHE[(tg_id, perm)] = (now, result)
    return result


class RateLimitMiddleware(BaseMiddleware):
    """30 actions/min/user globally; 5 payment attempts/min. Admins bypass.

    P3.21: database-backed sliding window (multi-replica safe). Falls back
    to in-memory if the rate_limit_hits table is missing (e.g. old DB).
    """

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._hits = {}
        self._pay_hits = {}

    async def _allowed_distributed(self, bucket: str, user_id: int,
                                   limit: int) -> bool:
        try:
            from rate_limit import is_allowed
            return await is_allowed(self.db, bucket, user_id, limit,
                                    RATE_WINDOW)
        except Exception:
            # Table missing or DB error — fall back to in-memory
            return self._allowed_memory(
                self._hits if bucket == "global" else self._pay_hits,
                user_id, limit)

    def _allowed_memory(self, bucket: dict, user_id: int, limit: int) -> bool:
        now = time.monotonic()
        dq = bucket.setdefault(user_id, deque())
        while dq and now - dq[0] > RATE_WINDOW:
            dq.popleft()
        if not dq:
            bucket.pop(user_id, None)
        if len(dq) >= limit:
            return False
        dq.append(now)
        bucket[user_id] = dq
        return True

    async def on_pre_process_message(self, message, data):
        if not message.from_user:
            return
        uid = message.from_user.id
        if await _is_admin(self.db, uid):
            return
        if not await self._allowed_distributed("global", uid, RATE_GLOBAL):
            await message.answer(texts.ERR_RATE_LIMITED)
            raise CancelHandler()

    async def on_pre_process_callback_query(self, query, data):
        uid = query.from_user.id
        if await _is_admin(self.db, uid):
            return
        if not await self._allowed_distributed("global", uid, RATE_GLOBAL):
            await query.answer(texts.ERR_RATE_LIMITED, show_alert=True)
            raise CancelHandler()
        if (query.data or "").startswith(("pay", "cok", "crypto")) or data.get("state"):
            if not await self._allowed_distributed("payment", uid, RATE_PAYMENT):
                await query.answer(texts.ERR_PAY_RATE_LIMITED, show_alert=True)
                raise CancelHandler()


class MaintenanceMiddleware(BaseMiddleware):
    """When maintenance mode is ON, non-admins get a notice; admins pass."""

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_pre_process_message(self, message, data):
        if not message.from_user:
            return
        if await self.db.maintenance_on() and not await _is_admin(
                self.db, message.from_user.id, config.PERM_MAINTENANCE):
            await message.answer(texts.ERR_MAINTENANCE)
            raise CancelHandler()

    async def on_pre_process_callback_query(self, query, data):
        if await self.db.maintenance_on() and not await _is_admin(
                self.db, query.from_user.id, config.PERM_MAINTENANCE):
            await query.answer(texts.ERR_MAINTENANCE, show_alert=True)
            raise CancelHandler()


class BlockedMiddleware(BaseMiddleware):
    """Blocked users get a notice and nothing else. Runs before other gates."""

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def _is_blocked(self, tg_id: int) -> bool:
        try:
            user = await self.db.get_user_by_tg(tg_id)
        except Exception:
            return False
        return bool(user and user["is_blocked"])

    async def on_pre_process_message(self, message, data):
        if not message.from_user:
            return
        if await self._is_blocked(message.from_user.id):
            await message.answer(texts.MSG_ACCOUNT_BLOCKED)
            raise CancelHandler()

    async def on_pre_process_callback_query(self, query, data):
        if await self._is_blocked(query.from_user.id):
            await query.answer(texts.MSG_ACCOUNT_BLOCKED, show_alert=True)
            raise CancelHandler()


class CallbackSafetyMiddleware(BaseMiddleware):
    """Safety net: never leave a callback query unanswered.

    Handlers answer their queries first (UX rule); if one somehow doesn't
    (early return, missed branch), the empty ack here prevents the client
    spinner from hanging. Answering an already-answered query raises, which
    we swallow.
    """

    async def on_pre_process_callback_query(self, query, data):
        query._answered = False
        original_answer = query.answer
        async def tracked_answer(*args, **kwargs):
            query._answered = True
            return await original_answer(*args, **kwargs)
        query.answer = tracked_answer

    async def on_post_process_callback_query(self, query, results, data):
        if not getattr(query, "_answered", False):
            try:
                await query.answer()
            except Exception:
                logger.debug("fallback callback answer failed", exc_info=True)
