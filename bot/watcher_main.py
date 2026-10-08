"""Standalone blockchain observer entry point (re-audit P3.19).

Run the crypto deposit watcher as its own process, separate from the
Telegram bot. This is the production topology:

    nova-shop-bot.service      — Telegram polling only
    nova-shop-watcher.service  — blockchain observation only

Both share the same SQLite database file (WAL mode allows concurrent
readers; the watcher only writes via short transactions).

Usage:
    cd bot && python watcher_main.py

Set WATCHER_STANDALONE=1 in the bot's environment to disable the
in-process watcher (it will be started by the watcher service instead).
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("watcher")


async def main():
    from crypto_watcher import crypto_watcher_loop
    logger.info("Starting standalone blockchain observer")
    await crypto_watcher_loop()


if __name__ == "__main__":
    asyncio.run(main())
