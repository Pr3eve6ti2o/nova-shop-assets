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
# Opus P1: MemoryStorage loses FSM state on restart and splits across workers.
# Production multi-worker deployments must use RedisStorage; single-worker
# keeps memory storage. Warn so the limitation is visible.
if os.getenv("WORKERS", "1") != "1":
    logger.warning(
        "MemoryStorage with WORKERS>1 — FSM state is per-process. "
        "Use RedisStorage for multi-worker deployments.")
dp = Dispatcher(bot, storage=storage)

# Opus P0: absolute database path — a relative "data/nova_shop.db" lets the
# bot and the standalone watcher open DIFFERENT databases depending on cwd.
_DB_PATH = os.getenv("DATABASE_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "nova_shop.db")
_DB_PATH = os.path.abspath(_DB_PATH)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
db = Database(_DB_PATH)

logger.info("Loader initialized (bot, dispatcher, database at %s).", _DB_PATH)
