"""Environment configuration for Nova Shop Bot.

Required:
    BOT_TOKEN - Telegram bot token from @BotFather.

Optional:
    ADMINS - comma-separated Telegram user IDs with full admin rights.
    PAYMENTS_PROVIDER_TOKEN - Telegram Payments provider token (fiat card payments).
                              Card button is hidden when unset.
    STARS_PER_USD - Stars per 1 USD for XTR conversion (default 60).
    CURRENCY - ISO 4217 currency code for fiat payments (default USD).
    REFERRAL_PERCENT - % of referee's first paid order credited to referrer (default 5).
    DELIVERY_FEE_CENTS - flat delivery fee in cents (default 0 = free delivery).
    WEBHOOK_HOST / WEBHOOK_PATH - enable webhook mode when both are set.
    --- Crypto (all optional, free tiers) ---
    CRYPTOBOT_TOKEN - Crypto Pay API token from @CryptoBot -> Crypto Pay -> Create App.
                      Enables the CryptoBot payment rail (USDT default, +3% fee).
    CRYPTOBOT_TESTNET - set to 1 to use testnet-pay.crypt.bot (default 0).
    CRYPTOBOT_FEE_PERCENT - fee added on CryptoBot invoices (default 3).
    XPUB_BTC - account xpub (zpub ok) for BTC address derivation. Seed stays OFFLINE.
    XPUB_ETH - account xpub for ETH (m/44'/60'/0').
    XPUB_TRX - account xpub for TRON (m/44'/195'/0').
    TON_DEPOSIT_ADDRESS - static TON wallet address for the memo scheme.
    CRYPTO_TTL_MINUTES - deposit payment window in minutes (default 45).
    --- Mini App (optional) ---
    MINIAPP_URL - https://… URL of the hosted Mini App (Cloudflare Pages etc.).
                  Unset = classic bot only.
"""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Copy .env.example to .env and set BOT_TOKEN "
        "(get one from @BotFather)."
    )


def _parse_id_list(raw: str) -> list:
    """Parse a comma-separated id list; empty/missing -> []."""
    ids = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise RuntimeError(f"Invalid Telegram user id in ADMINS: {part!r}")
    return ids


ADMINS: list = _parse_id_list(os.getenv("ADMINS", ""))

PAYMENTS_PROVIDER_TOKEN = os.getenv("PAYMENTS_PROVIDER_TOKEN") or None

STARS_PER_USD: int = int(os.getenv("STARS_PER_USD", "60") or 60)
CURRENCY: str = (os.getenv("CURRENCY", "USD") or "USD").upper()
REFERRAL_PERCENT: int = int(os.getenv("REFERRAL_PERCENT", "5") or 5)
DELIVERY_FEE_CENTS: int = int(os.getenv("DELIVERY_FEE_CENTS", "0") or 0)

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") or None
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH") or None
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST and WEBHOOK_PATH else None

# --- Crypto payments (all optional) ---
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN") or None
CRYPTOBOT_TESTNET = (os.getenv("CRYPTOBOT_TESTNET", "0") or "0").strip() == "1"
CRYPTOBOT_FEE_PERCENT: int = int(os.getenv("CRYPTOBOT_FEE_PERCENT", "3") or 3)

XPUB_BTC = os.getenv("XPUB_BTC") or None
XPUB_ETH = os.getenv("XPUB_ETH") or None
XPUB_TRX = os.getenv("XPUB_TRX") or None
TON_DEPOSIT_ADDRESS = os.getenv("TON_DEPOSIT_ADDRESS") or None

CRYPTO_TTL_MINUTES: int = int(os.getenv("CRYPTO_TTL_MINUTES", "45") or 45)

# --- Mini App (optional) ---
MINIAPP_URL = os.getenv("MINIAPP_URL") or None

# Permission bits (bitmask RBAC)
PERM_STATS = 1
PERM_CATALOG = 2
PERM_ORDERS = 4
PERM_USERS = 8
PERM_BROADCAST = 16
PERM_PROMOS = 32
PERM_MAINTENANCE = 64
PERM_ALL = 127

PERM_NAMES = {
    PERM_STATS: "Stats",
    PERM_CATALOG: "Catalog",
    PERM_ORDERS: "Orders",
    PERM_USERS: "Users",
    PERM_BROADCAST: "Broadcast",
    PERM_PROMOS: "Promos",
    PERM_MAINTENANCE: "Maintenance",
}
