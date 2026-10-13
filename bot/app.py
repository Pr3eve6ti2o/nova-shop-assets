"""Nova Shop Bot — entrypoint."""
import asyncio
import logging
import os
import sys

# Opus P0-5: configure logging BEFORE importing loader — loader import can
# fail (bad token, bad DB path) and those failures were invisible.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

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

# Opus P0: single-instance guard — two pollers/webhooks = double fulfilment.
# Must run before anything else touches Telegram or the database.
try:
    from single_instance import acquire_single_instance
except ImportError:
    acquire_single_instance = None

if acquire_single_instance is not None:
    acquire_single_instance()
else:
    # Fallback: pidfile guard when the helper module is unavailable.
    _pidfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "nova-shop-bot.pid")
    _pidfile = os.path.abspath(_pidfile)
    if os.path.exists(_pidfile):
        try:
            with open(_pidfile) as _f:
                _old_pid = int(_f.read().strip())
            os.kill(_old_pid, 0)
            sys.exit(f"Another bot instance is running (pid {_old_pid})")
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    with open(_pidfile, "w") as _f:
        _f.write(str(os.getpid()))

_watcher_task: asyncio.Task | None = None
_outbox_task: asyncio.Task | None = None
_campaign_task: asyncio.Task | None = None
_api_runner = None  # store-credit internal API (Payload), Phase 3

# Bind custom filters BEFORE handlers register (they use is_admin=...).
# Opus P2: bind once — duplicate bind was dead code.
dp.filters_factory.bind(IsAdmin)

import handlers  # noqa: F401  (registers all handlers)

logger = logging.getLogger(__name__)

# Opus P1: middleware order — aiogram 2.x runs setup_middleware in reverse
# registration order for pre-processing, so register in reverse priority.
dp.setup_middleware(CallbackSafetyMiddleware())
dp.setup_middleware(MaintenanceMiddleware(db))
dp.setup_middleware(RateLimitMiddleware(db))
dp.setup_middleware(BlockedMiddleware(db))

WEBAPP_HOST = "0.0.0.0"
# Opus P2-15: validate PORT — unvalidated int() crashes on garbage.
try:
    WEBAPP_PORT = int(os.environ.get("PORT", "5000"))
except ValueError:
    raise RuntimeError(f"PORT must be an integer, got {os.environ.get('PORT')!r}")
if not (1 <= WEBAPP_PORT <= 65535):
    raise RuntimeError(f"PORT must be 1-65535, got {WEBAPP_PORT}")

# Opus P2-16: cross-check WEBHOOK_PATH against WEBHOOK_URL.
if config.WEBHOOK_URL and config.WEBHOOK_PATH:
    if not config.WEBHOOK_URL.rstrip("/").endswith(
            "/" + config.WEBHOOK_PATH.strip("/")):
        raise RuntimeError(
            "WEBHOOK_PATH does not match WEBHOOK_URL — "
            "the webhook receiver path must be a suffix of the URL")

# Opus P0: skip_updates=True drops pre_checkout_query / successful_payment
# received while offline — customers get charged but never fulfilled.
# Never skip updates; process the backlog on startup.
SKIP_UPDATES = False

# Opus P1: allowed_updates must cover every update type the bot handles,
# and must be identical in polling and webhook modes.
ALLOWED_UPDATES = [
    "message", "callback_query", "pre_checkout_query", "shipping_query",
    "chat_member",
]


@dp.errors_handler()
async def errors_handler(update, exception):
    # Opus: never swallow CancelledError — it hides cancellation signals.
    if isinstance(exception, asyncio.CancelledError):
        raise exception
    logger.exception("Unhandled error on update %s: %s",
                     getattr(update, "update_id", "?"), exception)
    # Opus P2: alert admins on payment-critical failures instead of
    # silently swallowing.
    try:
        if update and getattr(update, "pre_checkout_query", None):
            _admin_ids = list(config.ADMINS)[:5]
            for _aid in _admin_ids:
                try:
                    await bot.send_message(
                        _aid,
                        f"⚠️ pre_checkout_query failed: {exception!r}")
                except Exception:
                    pass
    except Exception:
        pass
    return True  # swallow — one bad update must not kill polling


async def on_startup(dp_):
    await db.create_tables()
    await bot.delete_webhook()
    if config.WEBHOOK_URL:
        await bot.set_webhook(config.WEBHOOK_URL,
                              secret_token=config.WEBHOOK_SECRET_TOKEN,
                              allowed_updates=ALLOWED_UPDATES)
        # Opus P0/P1: aiogram 2.x does not verify X-Telegram-Bot-Api-Secret-Token.
        # Enforce it at the web layer via middleware (see webapp_secret.py)
        # and restrict source IPs where the platform allows.
        logger.warning(
            "Webhook mode: ensure the web server verifies "
            "X-Telegram-Bot-Api-Secret-Token — aiogram 2.x does not.")
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
    global _watcher_task, _outbox_task
    if not config.WATCHER_STANDALONE:
        from crypto_watcher import crypto_watcher_loop
        # Opus P2: asyncio.get_event_loop() is deprecated — use get_running_loop.
        _watcher_task = asyncio.get_running_loop().create_task(crypto_watcher_loop())
    else:
        logger.info("In-process watcher disabled (WATCHER_STANDALONE=1)")

    # P3.18: outbox worker — durable delivery of order.created events
    # to Payload CMS with retry/backoff.
    # Opus P1: retain the task reference — unreferenced tasks get GC'd.
    from outbox_worker import outbox_worker_loop
    from loader import db as _db
    _outbox_task = asyncio.get_running_loop().create_task(outbox_worker_loop(_db))

    # Port Part 2: campaign engine (abandoned cart, back-in-stock,
    # post-purchase, onboarding). CAMPAIGNS_ENABLED=0 disables sends.
    global _campaign_task
    if config.CAMPAIGNS_ENABLED:
        from campaign_worker import campaign_worker_loop
        from loader import bot as _bot
        _campaign_task = asyncio.get_running_loop().create_task(
            campaign_worker_loop(_db, _bot))
    else:
        logger.info("Campaign engine disabled (CAMPAIGNS_ENABLED=0)")

    # Store-credit internal API for Payload (Phase 3): localhost-only,
    # off unless INTERNAL_API_PORT + a >=32-char secret are configured.
    global _api_runner
    from internal_api import start_internal_api
    _api_runner = await start_internal_api(_db)


async def on_shutdown(dp_):
    logger.warning("Shutting down...")
    global _watcher_task, _outbox_task, _campaign_task
    # Opus P1: cancel with a timeout — unbounded await can hang shutdown
    # mid-credit.
    for _task, _name in ((_watcher_task, "watcher"),
                         (_outbox_task, "outbox"),
                         (_campaign_task, "campaign")):
        if _task:
            _task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(_task), timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
    _watcher_task = None
    _outbox_task = None
    _campaign_task = None
    global _api_runner
    if _api_runner is not None:
        try:
            await _api_runner.cleanup()
        except Exception:
            pass
        _api_runner = None
    # Opus P2: do not delete the webhook on shutdown in webhook mode —
    # it drops the production webhook on every restart.
    if not config.WEBHOOK_URL:
        try:
            await bot.delete_webhook()
        except Exception:
            pass
    await dp_.storage.close()
    await dp_.storage.wait_closed()
    # Opus P2: close the database connection on shutdown.
    try:
        await db.close()
    except Exception:
        pass
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
            skip_updates=SKIP_UPDATES,
            host=WEBAPP_HOST,
            port=WEBAPP_PORT,
        )
    else:
        executor.start_polling(
            dp, on_startup=on_startup, on_shutdown=on_shutdown,
            skip_updates=SKIP_UPDATES,
            allowed_updates=ALLOWED_UPDATES,
            timeout=20, relax=0.1,
        )
