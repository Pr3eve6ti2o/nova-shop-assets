"""Nova Shop Bot — entrypoint."""
import asyncio
import logging
import os

from aiogram import executor, types

import config
from filters import IsAdmin
from loader import bot, db, dp
from middlewares import (
    BlockedMiddleware,
    CallbackSafetyMiddleware,
    MaintenanceMiddleware,
    RateLimitMiddleware,
)

_watcher_task: asyncio.Task | None = None

# Bind custom filters BEFORE handlers register (they use is_admin=...).
dp.filters_factory.bind(IsAdmin)

import handlers  # noqa: F401  (registers all handlers)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

dp.filters_factory.bind(IsAdmin)
dp.setup_middleware(BlockedMiddleware(db))
dp.setup_middleware(RateLimitMiddleware(db))
dp.setup_middleware(MaintenanceMiddleware(db))
dp.setup_middleware(CallbackSafetyMiddleware())

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.environ.get("PORT", 5000))


@dp.errors_handler()
async def errors_handler(update, exception):
    logger.exception("Unhandled error on update %s: %s",
                     getattr(update, "update_id", "?"), exception)
    return True  # swallow — one bad update must not kill polling


async def on_startup(dp_):
    await db.create_tables()
    await bot.delete_webhook()
    if config.WEBHOOK_URL:
        await bot.set_webhook(config.WEBHOOK_URL, secret_token=config.WEBHOOK_SECRET_TOKEN)
    try:
        await bot.set_my_commands([
            types.BotCommand("start", "Start the shop"),
            types.BotCommand("help", "Help & FAQ"),
            types.BotCommand("admin", "Admin console"),
        ])
    except Exception as e:
        logger.warning("set_my_commands failed: %s", e)
    me = await bot.me
    logger.info("=" * 50)
    logger.info("\U0001f6cd\ufe0f Nova Shop Bot started")
    logger.info("   Bot: @%s", me.username)
    logger.info("   Mode: %s", "WEBHOOK" if config.WEBHOOK_URL else "POLLING")
    logger.info("   Admins: %d configured", len(config.ADMINS))
    logger.info("   Card payments: %s", "YES" if config.PAYMENTS_PROVIDER_TOKEN else "NO")
    logger.info("   Stars rate: %d per USD", config.STARS_PER_USD)
    logger.info("   CryptoBot: %s", "YES" if config.CRYPTOBOT_TOKEN else "NO")
    logger.info("   Mini App: %s", config.MINIAPP_URL or "NO")
    logger.info("=" * 50)

    # Background crypto deposit watcher (SPEC2 §4): 60s sweeps, never crashes.
    # P3.19: disabled when WATCHER_STANDALONE=1 (watcher runs as its own service).
    global _watcher_task
    if not config.WATCHER_STANDALONE:
        from crypto_watcher import crypto_watcher_loop
        _watcher_task = asyncio.get_event_loop().create_task(crypto_watcher_loop())
    else:
        logger.info("In-process watcher disabled (WATCHER_STANDALONE=1)")

    # P3.18: outbox worker — durable delivery of order.created events
    # to Payload CMS with retry/backoff.
    from outbox_worker import outbox_worker_loop
    from loader import db as _db
    asyncio.get_event_loop().create_task(outbox_worker_loop(_db))


async def on_shutdown(dp_):
    logger.warning("Shutting down...")
    global _watcher_task
    if _watcher_task:
        _watcher_task.cancel()
        try:
            await _watcher_task
        except asyncio.CancelledError:
            pass
        _watcher_task = None
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    await dp_.storage.close()
    await dp_.storage.wait_closed()
    try:
        await bot.close()
    except Exception:
        pass
    logger.warning("Bot down")


if __name__ == "__main__":
    if config.WEBHOOK_URL:
        executor.start_webhook(
            dispatcher=dp,
            webhook_path=config.WEBHOOK_PATH,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            skip_updates=True,
            host=WEBAPP_HOST,
            port=WEBAPP_PORT,
        )
    else:
        executor.start_polling(
            dp, on_startup=on_startup, on_shutdown=on_shutdown, skip_updates=True,
            allowed_updates=["message", "callback_query", "pre_checkout_query"],
            timeout=20, relax=0.1,
        )
