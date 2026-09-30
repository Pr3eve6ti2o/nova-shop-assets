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


async def _is_admin(db, tg_id: int) -> bool:
    if tg_id in config.ADMINS:
        return True
    user = await db.get_user_by_tg(tg_id)
    return bool(user and user["role_mask"])


class RateLimitMiddleware(BaseMiddleware):
    """30 actions/min/user globally; 5 payment attempts/min. Admins bypass."""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._hits = {}
        self._pay_hits = {}

    def _allowed(self, bucket: dict, user_id: int, limit: int) -> bool:
        now = time.monotonic()
        dq = bucket.setdefault(user_id, deque())
        while dq and now - dq[0] > RATE_WINDOW:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

    async def on_pre_process_message(self, message, data):
        if not message.from_user:
            return
        uid = message.from_user.id
        if await _is_admin(self.db, uid):
            return
        if not self._allowed(self._hits, uid, RATE_GLOBAL):
            await message.answer(texts.ERR_RATE_LIMITED)
            raise CancelHandler()

    async def on_pre_process_callback_query(self, query, data):
        uid = query.from_user.id
        if await _is_admin(self.db, uid):
            return
        if not self._allowed(self._hits, uid, RATE_GLOBAL):
            await query.answer(texts.ERR_RATE_LIMITED, show_alert=True)
            raise CancelHandler()
        if (query.data or "") == "cok":
            if not self._allowed(self._pay_hits, uid, RATE_PAYMENT):
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
        if await self.db.maintenance_on() and not await _is_admin(self.db,
                                                                  message.from_user.id):
            await message.answer(texts.ERR_MAINTENANCE)
            raise CancelHandler()

    async def on_pre_process_callback_query(self, query, data):
        if await self.db.maintenance_on() and not await _is_admin(self.db,
                                                                  query.from_user.id):
            await query.answer(texts.ERR_MAINTENANCE, show_alert=True)
            raise CancelHandler()


class CallbackSafetyMiddleware(BaseMiddleware):
    """Safety net: never leave a callback query unanswered.

    Handlers answer their queries first (UX rule); if one somehow doesn't
    (early return, missed branch), the empty ack here prevents the client
    spinner from hanging. Answering an already-answered query raises, which
    we swallow.
    """

    async def on_post_process_callback_query(self, query, results, data):
        try:
            await query.answer()
        except Exception:
            pass  # already answered by the handler
