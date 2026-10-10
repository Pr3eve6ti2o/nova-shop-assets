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
if STARS_PER_USD <= 0:
    raise RuntimeError("STARS_PER_USD must be > 0")
CURRENCY: str = (os.getenv("CURRENCY", "USD") or "USD").upper()
REFERRAL_PERCENT: int = int(os.getenv("REFERRAL_PERCENT", "5") or 5)
if not (0 <= REFERRAL_PERCENT <= 100):
    raise RuntimeError("REFERRAL_PERCENT must be between 0 and 100")
DELIVERY_FEE_CENTS: int = int(os.getenv("DELIVERY_FEE_CENTS", "0") or 0)
if DELIVERY_FEE_CENTS < 0:
    raise RuntimeError("DELIVERY_FEE_CENTS must be >= 0")

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") or None
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH") or None
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN") or None
if WEBHOOK_HOST and WEBHOOK_PATH:
    WEBHOOK_URL = f"{WEBHOOK_HOST.rstrip('/')}/{WEBHOOK_PATH.lstrip('/')}"
    if not WEBHOOK_URL.startswith("https://"):
        raise RuntimeError("WEBHOOK_URL must use https://")
    if not WEBHOOK_SECRET_TOKEN or len(WEBHOOK_SECRET_TOKEN) < 16:
        raise RuntimeError("WEBHOOK_SECRET_TOKEN must be set to a strong value when webhook mode is enabled")
else:
    WEBHOOK_URL = None

# --- Crypto payments (all optional) ---
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN") or None
CRYPTOBOT_TESTNET = (os.getenv("CRYPTOBOT_TESTNET", "0") or "0").strip() == "1"
CRYPTOBOT_FEE_PERCENT: int = int(os.getenv("CRYPTOBOT_FEE_PERCENT", "3") or 3)
if CRYPTOBOT_FEE_PERCENT < 0:
    raise RuntimeError("CRYPTOBOT_FEE_PERCENT must be >= 0")

XPUB_BTC = os.getenv("XPUB_BTC") or None
XPUB_ETH = os.getenv("XPUB_ETH") or None
XPUB_TRX = os.getenv("XPUB_TRX") or None
TON_DEPOSIT_ADDRESS = os.getenv("TON_DEPOSIT_ADDRESS") or None

# M3: fail fast on misconfigured xpubs — a ypub/tpub/truncated key would
# otherwise surface only at checkout time as a generic derivation failure.
def _validate_xpubs():
    expected = {
        "XPUB_BTC": ("zpub", "xpub", "ypub"),  # BIP84/BIP49: zpub/ypub preferred, xpub tolerated
        "XPUB_ETH": ("xpub",),
        "XPUB_TRX": ("xpub",),
    }
    for env_key, prefixes in expected.items():
        val = globals().get(env_key)
        if not val:
            continue  # chain disabled — enabled_chains() handles this
        v = val.strip()
        if not v.startswith(prefixes):
            raise RuntimeError(
                f"Misconfigured {env_key}: expected prefix {prefixes}, got {v[:8]!r}... — "
                f"direct {env_key.split('_')[1].lower()} deposits will fail. Fix .env."
            )
    # P0: Prevent testnet/mainnet xpub cross-contamination. A testnet build
    # deriving from a mainnet xpub (or vice versa) generates addresses the
    # operator does not control — funds sent there are lost.
    testnet_xpub = globals().get("TESTNET_XPUB_ETH")
    mainnet_xpub = globals().get("XPUB_ETH")
    if testnet_xpub and mainnet_xpub:
        if testnet_xpub.strip() == mainnet_xpub.strip():
            raise RuntimeError(
                "Misconfigured TESTNET_XPUB_ETH: must differ from XPUB_ETH. "
                "NEVER reuse a mainnet xpub for testnet."
            )
_validate_xpubs()

CRYPTO_TTL_MINUTES: int = int(os.getenv("CRYPTO_TTL_MINUTES", "45") or 45)
if CRYPTO_TTL_MINUTES <= 0:
    raise RuntimeError("CRYPTO_TTL_MINUTES must be > 0")

# --- Mini App (optional) ---
MINIAPP_URL = os.getenv("MINIAPP_URL") or None
if MINIAPP_URL and not MINIAPP_URL.startswith("https://"):
    raise RuntimeError("MINIAPP_URL must use https://")

# Permission bits (bitmask RBAC)
PERM_STATS = 1
PERM_CATALOG = 2
PERM_ORDERS = 4
PERM_USERS = 8
PERM_BROADCAST = 16
PERM_PROMOS = 32
PERM_MAINTENANCE = 64
PERM_SWAP_APPROVE = 128  # P2.13: dedicated token-swap approval permission
# P0: was 127, silently excluded PERM_SWAP_APPROVE (128). Must cover all bits.
PERM_ALL = 255

PERM_NAMES = {
    PERM_STATS: "Stats",
    PERM_CATALOG: "Catalog",
    PERM_ORDERS: "Orders",
    PERM_USERS: "Users",
    PERM_BROADCAST: "Broadcast",
    PERM_PROMOS: "Promos",
    PERM_MAINTENANCE: "Maintenance",
    PERM_SWAP_APPROVE: "Swap Approve",
}

# Deposit bonus: 5% extra on every top-up
DEPOSIT_BONUS_PERCENT = 5

# --- Nova control plane (rent flow) ---
NOVA_API_URL = (os.getenv("NOVA_API_URL", "http://localhost:3002") or "http://localhost:3002").rstrip("/")
# Security (audit 12.2): control-plane traffic must use HTTPS unless it is
# loopback. A remote http:// URL would send the API key in cleartext.
if NOVA_API_URL.lower().startswith("http://"):  # P1-1: case-insensitive
    _host = NOVA_API_URL[7:].split("/")[0].split(":")[0].lower()
    if _host not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            f"NOVA_API_URL must use https:// for non-localhost hosts (got {NOVA_API_URL!r}). "
            "The API key is sent on every request."
        )
NOVA_API_KEY = os.getenv("NOVA_API_KEY") or None
# P1-2: API key required for non-localhost — fail closed.
if not NOVA_API_KEY:
    _is_local_url = NOVA_API_URL.lower().startswith(
        ("http://localhost", "http://127.0.0.1", "http://[::1]"))
    if not _is_local_url:
        raise RuntimeError(
            "NOVA_API_KEY is required for non-localhost NOVA_API_URL.")
RENTAL_TOKEN_ONBOARDING = os.getenv("RENTAL_TOKEN_ONBOARDING", "1") == "1"

# --- Managed bots (Telegram Bot API 9.6) express setup — pilot-gated ---
# Both must be set for the "Express setup" button to appear. Defaults keep
# the paste-token UI unchanged until the pilot backend lands
# (manager bot, provisioning_mode, vault rotation).
MANAGED_ONBOARDING_ENABLED = os.getenv("MANAGED_ONBOARDING_ENABLED", "0") == "1"
MANAGER_BOT_USERNAME = (os.getenv("MANAGER_BOT_USERNAME", "") or "").strip().lstrip("@")

# --- Rental support contact ---
# Public support username shown in-bot and in the bot description.
# Tenants reach support via this username or the in-bot ticket flow.
SUPPORT_USERNAME = (os.getenv("SUPPORT_USERNAME", "") or "").strip().lstrip("@")


ETHERSCAN_API_KEY = (os.getenv("ETHERSCAN_API_KEY", "") or "").strip()

# CRYPTO_TESTNET=1 switches the bot to TESTNET_CHAINS (Sepolia / Base Sepolia)
# for end-to-end deposit testing with free funds. Mainnet unchanged when off.
CRYPTO_TESTNET = (os.getenv("CRYPTO_TESTNET", "0") or "0").strip().lower() in (
    "1", "true", "yes", "on")

# P3.19: set WATCHER_STANDALONE=1 when the blockchain observer runs as its
# own process (nova-shop-watcher.service). The in-process watcher is then
# disabled to avoid double-scanning.
WATCHER_STANDALONE = (os.getenv("WATCHER_STANDALONE", "0") or "0").strip().lower() in (
    "1", "true", "yes", "on")

# Fresh TESTNET xpub (tpub) used only when CRYPTO_TESTNET is on.
# NEVER reuse a mainnet xpub here.
TESTNET_XPUB_ETH = (os.getenv("TESTNET_XPUB_ETH", "") or "").strip()
