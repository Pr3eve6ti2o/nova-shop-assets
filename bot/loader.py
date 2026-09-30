"""Bot, Dispatcher and Database singletons for Nova Shop Bot."""
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

import config
from database import Database

logger = logging.getLogger(__name__)

if not config.BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Copy .env.example to .env and set BOT_TOKEN "
        "(get one from @BotFather)."
    )

_proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or None
if _proxy:
    logger.info("Using egress proxy for Telegram API requests.")

bot = Bot(token=config.BOT_TOKEN, parse_mode=types.ParseMode.HTML, proxy=_proxy)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
db = Database("data/nova_shop.db")

logger.info("Loader initialized (bot, dispatcher, database).")
