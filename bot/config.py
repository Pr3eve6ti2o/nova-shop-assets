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
    DEPOSIT_BONUS_PERCENT - % bonus on every top-up (default 5).
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
import hashlib
import ipaddress
import logging
import os
import re
import time

from dotenv import load_dotenv

# Opus P0-20: load_dotenv with explicit path — cwd-dependent loading silently
# drops optional vars (no admins, no crypto) when systemd uses another cwd.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BASE_DIR, ".env"))

# Opus: enforce UTC for subscription expiry math — local time causes
# off-by-hours renewal / double-charge bugs.
os.environ.setdefault("TZ", "UTC")
try:
    time.tzset()
except Exception:
    pass

_log = logging.getLogger(__name__)


def _int_env(name: str, default: int, min_val: int = None,
             max_val: int = None) -> int:
    """Parse an integer env var with a clear error message.

    Opus: bare int() throws unhelpful tracebacks. This names the variable
    and shows the bad value. Whitespace-only values are treated as unset.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        val = default
    else:
        try:
            val = int(raw.strip())
        except ValueError:
            raise RuntimeError(
                f"{name} must be an integer, got {raw!r}") from None
    if min_val is not None and val < min_val:
        raise RuntimeError(f"{name} must be >= {min_val}, got {val}")
    if max_val is not None and val > max_val:
        raise RuntimeError(f"{name} must be <= {max_val}, got {val}")
    return val


def _flag(name: str, default: str = "0") -> bool:
    """Parse a boolean env flag.

    Opus: previously returned False silently on typos ("flase", "yes please").
    Now raises on unrecognised values so testnet/mainnet cannot be set wrong
    by accident.
    """
    raw = (os.getenv(name, default) or default).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off", ""):
        return False
    raise RuntimeError(
        f"{name} has unrecognised boolean value {raw!r} — "
        f'use one of 1/0, true/false, yes/no, on/off')


BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Copy .env.example to .env and set BOT_TOKEN "
        "(get one from @BotFather)."
    )
# Opus P2-19: catch truncated / whitespace-padded tokens at startup with a
# clear error instead of a confusing 401 later.
if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", BOT_TOKEN):
    raise RuntimeError(
        "BOT_TOKEN looks malformed (expected <digits>:<35+ chars>). "
        "Check for truncation or copy-paste errors.")


def _parse_id_list(raw: str) -> list:
    """Parse a comma-separated id list; empty/missing -> []."""
    ids = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = int(part)
        except ValueError:
            raise RuntimeError(
                f"Invalid Telegram user id in ADMINS: {part!r}") from None
        if val <= 0:
            raise RuntimeError(
                f"Invalid Telegram user id in ADMINS: {part!r} "
                f"(must be a positive integer)")
        ids.append(val)
    return ids


# Opus: frozenset for O(1) membership; _parse_id_list fails fast on garbage.
ADMINS: frozenset = frozenset(_parse_id_list(os.getenv("ADMINS", "")))
# Opus: empty ADMINS leaves the bot with no administrators — warn loudly.
if not ADMINS:
    _log.warning(
        "ADMINS is empty — no Telegram user has admin rights. "
        "Set ADMINS to at least one user id.")

PAYMENTS_PROVIDER_TOKEN = (os.getenv("PAYMENTS_PROVIDER_TOKEN") or "").strip() or None

# Opus: upper bounds — a fat-fingered value overcharges by orders of magnitude.
STARS_PER_USD: int = _int_env("STARS_PER_USD", 60, min_val=1, max_val=10000)

# Top-up bounds (stress-audit Part G): these used to be hardcoded in
# handlers/crypto.py and handlers/balance.py. They are policy, not
# safety limits — invoice creation and balance math are safe at any
# positive amount (CryptoBot's own minimum is ~0.01 USDT) — so they
# live here, tunable via env. Keep the user-facing texts in sync if
# you change the defaults (texts.MSG_BALANCE_CUSTOM_*).
MIN_TOPUP_CENTS: int = _int_env("MIN_TOPUP_CENTS", 50, min_val=1, max_val=100_000_000)
MAX_TOPUP_CENTS: int = _int_env("MAX_TOPUP_CENTS", 250_000, min_val=1, max_val=100_000_000)

# Store credit internal API (Medusa borrow, Phase 3): a localhost-only
# aiohttp server in the bot process that lets the Payload admin perform
# credit/debit, gift-card and manual-order operations WITHOUT touching
# the bot database directly — the bot's DB layer stays the single
# writer of money. Disabled unless a port is set; refuses to start
# without a >= 32 char secret (INTERNAL_API_SECRET).
INTERNAL_API_PORT: int = _int_env("INTERNAL_API_PORT", 0, min_val=0, max_val=65535)
INTERNAL_API_SECRET: str = (os.getenv("INTERNAL_API_SECRET", "") or "").strip()

# Opus: validate ISO 4217 shape; Telegram uses currency-specific exponents
# (JPY=0, KWD=3) so callers must use CURRENCY_EXPONENT, not assume 2.
CURRENCY: str = (os.getenv("CURRENCY", "USD") or "USD").strip().upper()
if not re.fullmatch(r"[A-Z]{3}", CURRENCY):
    raise RuntimeError(
        f"CURRENCY must be a 3-letter ISO 4217 code, got {CURRENCY!r}")

# Telegram Payments currency exponents (minor units per major unit).
_CURRENCY_EXPONENTS = {
    "JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "PYG": 0, "RWF": 0, "UGX": 0,
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
}
CURRENCY_EXPONENT: int = _CURRENCY_EXPONENTS.get(CURRENCY, 2)

# Opus P1: STARS_PER_USD assumes USD pricing; a non-USD CURRENCY silently
# misprices by the FX gap. Require USD or an explicit FX layer.
if CURRENCY != "USD":
    _log.warning(
        f"CURRENCY={CURRENCY} but STARS_PER_USD assumes USD pricing — "
        f"invoice amounts may be mispriced. Set CURRENCY=USD or add FX.")

REFERRAL_PERCENT: int = _int_env("REFERRAL_PERCENT", 5, min_val=0, max_val=50)
DELIVERY_FEE_CENTS: int = _int_env("DELIVERY_FEE_CENTS", 0,
                                   min_val=0, max_val=10_000_00)

# Opus: DEPOSIT_BONUS_PERCENT was hardcoded + undocumented + unvalidated.
DEPOSIT_BONUS_PERCENT: int = _int_env("DEPOSIT_BONUS_PERCENT", 5,
                                      min_val=0, max_val=50)

# Returns window (port plan 1.1): days after purchase/delivery during which
# a customer may request a return. 0 disables returns entirely.
RETURNS_WINDOW_DAYS: int = _int_env("RETURNS_WINDOW_DAYS", 14,
                                    min_val=0, max_val=365)

# Campaign engine (port plan Part 2): customer-lifecycle messages.
CAMPAIGNS_ENABLED: bool = _flag("CAMPAIGNS_ENABLED", "1")
CAMPAIGN_INTERVAL_SECONDS: int = _int_env("CAMPAIGN_INTERVAL_SECONDS", 300,
                                          min_val=30, max_val=86400)
ABANDONED_CART_DELAY_MINUTES: int = _int_env(
    "ABANDONED_CART_DELAY_MINUTES", 60, min_val=5, max_val=10080)
POST_PURCHASE_DELAY_HOURS: int = _int_env(
    "POST_PURCHASE_DELAY_HOURS", 24, min_val=1, max_val=720)
ONBOARDING_NUDGE_HOURS: int = _int_env(
    "ONBOARDING_NUDGE_HOURS", 24, min_val=1, max_val=720)

# Buyer-info collection (port plan 1.3, DoktorShift model): what the
# checkout asks before payment — none (default; checkout unchanged),
# email (buyer email), address (email + full name; the delivery
# address itself is collected for physical orders as before).
BUYER_INFO_MODE: str = (os.getenv("BUYER_INFO_MODE") or "none").strip().lower()
if BUYER_INFO_MODE not in ("none", "email", "address"):
    raise RuntimeError(
        f"BUYER_INFO_MODE must be none|email|address, got {BUYER_INFO_MODE!r}")

# Outbound shop webhooks (port plan 6.4): signed event POSTs via outbox.
SHOP_WEBHOOK_URL = (os.getenv("SHOP_WEBHOOK_URL") or "").strip() or None
SHOP_WEBHOOK_SECRET = (os.getenv("SHOP_WEBHOOK_SECRET") or "").strip() or None

# Admin forum routing (port plan 6.5): mirror admin notifications into a
# forum supergroup, optionally per-topic. 0/unset disables each.
ADMIN_FORUM_CHAT_ID: int = _int_env("ADMIN_FORUM_CHAT_ID", 0)
ADMIN_TOPIC_ORDERS: int = _int_env("ADMIN_TOPIC_ORDERS", 0)
ADMIN_TOPIC_SUPPORT: int = _int_env("ADMIN_TOPIC_SUPPORT", 0)
ADMIN_TOPIC_PAYMENTS: int = _int_env("ADMIN_TOPIC_PAYMENTS", 0)

# Opus P0 money-sanity: referral + bonus must never exceed 100%.
if REFERRAL_PERCENT + DEPOSIT_BONUS_PERCENT > 100:
    raise RuntimeError(
        f"REFERRAL_PERCENT ({REFERRAL_PERCENT}) + DEPOSIT_BONUS_PERCENT "
        f"({DEPOSIT_BONUS_PERCENT}) must not exceed 100")

WEBHOOK_HOST = (os.getenv("WEBHOOK_HOST") or "").strip() or None
WEBHOOK_PATH = (os.getenv("WEBHOOK_PATH") or "").strip() or None
WEBHOOK_SECRET_TOKEN = (os.getenv("WEBHOOK_SECRET_TOKEN") or "").strip() or None
if WEBHOOK_HOST and WEBHOOK_PATH:
    WEBHOOK_URL = f"{WEBHOOK_HOST.rstrip('/')}/{WEBHOOK_PATH.lstrip('/')}"
    if not WEBHOOK_URL.startswith("https://"):
        raise RuntimeError("WEBHOOK_URL must use https://")
    if not WEBHOOK_SECRET_TOKEN or len(WEBHOOK_SECRET_TOKEN) < 16:
        # Opus: previous message literally read "[REDACTED]" — convey the
        # actual problem without echoing the secret.
        raise RuntimeError(
            "WEBHOOK_SECRET_TOKEN must be set to a strong value "
            "(at least 16 characters) when webhook mode is enabled")
else:
    WEBHOOK_URL = None
# Opus: silent fallback to polling when webhook was half-configured risks
# double-processing — fail fast instead of warning.
if bool(WEBHOOK_HOST) != bool(WEBHOOK_PATH):
    raise RuntimeError(
        "WEBHOOK_HOST and WEBHOOK_PATH must both be set for webhook mode "
        "(or both unset for polling). Half-configured webhook refused.")

# --- Crypto payments (all optional) ---
CRYPTOBOT_TOKEN = (os.getenv("CRYPTOBOT_TOKEN") or "").strip() or None

CRYPTOBOT_TESTNET = _flag("CRYPTOBOT_TESTNET", "0")
CRYPTOBOT_FEE_PERCENT: int = _int_env("CRYPTOBOT_FEE_PERCENT", 3,
                                      min_val=0, max_val=100)

XPUB_BTC = (os.getenv("XPUB_BTC") or "").strip() or None
XPUB_ETH = (os.getenv("XPUB_ETH") or "").strip() or None
XPUB_TRX = (os.getenv("XPUB_TRX") or "").strip() or None
TON_DEPOSIT_ADDRESS = (os.getenv("TON_DEPOSIT_ADDRESS") or "").strip() or None

# Opus: validate TON address shape — a typo sends funds nowhere.
# Friendly addresses are 48 chars total (2-char prefix + 46). The
# original {44} pattern demanded 46 chars and rejected EVERY real
# address, crashing startup whenever one was configured (found
# 2026-10-13 when the test bot refused to boot with its real address;
# the test fixture had been shaped to the buggy pattern, so the suite
# stayed green).
if TON_DEPOSIT_ADDRESS and not re.fullmatch(
        r"[UEk]Q[A-Za-z0-9_-]{46}", TON_DEPOSIT_ADDRESS):
    raise RuntimeError(
        f"TON_DEPOSIT_ADDRESS looks malformed: {TON_DEPOSIT_ADDRESS[:12]!r}...")


def _b58check_decode(s: str) -> bytes:
    """Decode base58check; raises on bad checksum. Opus P0: prefix-only
    xpub checks let truncated keys derive uncontrolled addresses."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for ch in s:
        n = n * 58 + alphabet.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    # restore leading zero bytes
    pad = len(s) - len(s.lstrip("1"))
    raw = b"\x00" * pad + raw
    if len(raw) < 4:
        raise ValueError("too short")
    payload, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        raise ValueError("bad base58 checksum")
    return payload


def _validate_xpubs():
    expected = {
        "XPUB_BTC": ("zpub", "xpub", "ypub"),
        "XPUB_ETH": ("xpub",),
        "XPUB_TRX": ("xpub",),
    }
    # Opus: avoid fragile globals().get() — direct mapping fails loudly.
    values = {"XPUB_BTC": XPUB_BTC, "XPUB_ETH": XPUB_ETH, "XPUB_TRX": XPUB_TRX}
    for env_key, prefixes in expected.items():
        val = values[env_key]
        if not val:
            continue
        v = val.strip()
        if not v.startswith(prefixes):
            raise RuntimeError(
                f"Misconfigured {env_key}: expected prefix {prefixes}, "
                f"got {v[:8]!r}... — fix .env.")
        try:
            _b58check_decode(v)
        except Exception as e:
            raise RuntimeError(
                f"Misconfigured {env_key}: base58 checksum invalid "
                f"({e}) — truncated key would derive uncontrolled addresses."
            ) from None


_validate_xpubs()

CRYPTO_TTL_MINUTES: int = _int_env("CRYPTO_TTL_MINUTES", 45,
                                   min_val=5, max_val=24 * 60)

# --- Mini App (optional) ---
MINIAPP_URL = (os.getenv("MINIAPP_URL") or "").strip() or None
if MINIAPP_URL:
    if not MINIAPP_URL.startswith("https://"):
        raise RuntimeError("MINIAPP_URL must use https://")
    # Opus P2: empty host like "https://" alone must not pass.
    host = MINIAPP_URL[8:].split("/")[0]
    if not host:
        raise RuntimeError("MINIAPP_URL must include a host")

# Permission bits (bitmask RBAC)
PERM_STATS = 1
PERM_CATALOG = 2
PERM_ORDERS = 4
PERM_USERS = 8
PERM_BROADCAST = 16
PERM_PROMOS = 32
PERM_MAINTENANCE = 64
PERM_SWAP_APPROVE = 128  # P2.13: dedicated token-swap approval permission

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

# Opus: derive PERM_ALL programmatically — hardcoded 255 silently broke when
# bit 128 was added. Assertion catches future overflow.
PERM_ALL = 0
for _bit in PERM_NAMES:
    PERM_ALL |= _bit
assert PERM_ALL < 256, "permission bits overflow a single byte"

# --- Nova control plane (rent flow) ---
NOVA_API_URL = (os.getenv("NOVA_API_URL", "http://localhost:3002")
                or "http://localhost:3002").strip().rstrip("/")


def _redact_url(url: str) -> str:
    """Strip userinfo credentials so they never reach logs. Opus: the
    NOVA_API_URL error message embedded user:pass@host."""
    return re.sub(r"(https?://)[^/@]+@", r"\1***@", url)


def _is_loopback_host(host: str) -> bool:
    """Opus: use ipaddress.is_loopback + name allowlist; naive string splits
    mangle IPv6 [::1] and miss 127.1 / 0.0.0.0 forms."""
    h = host.strip().lower().strip("[]")
    if h in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _nova_host() -> str:
    m = re.match(r"^(https?)://([^/]+)", NOVA_API_URL, re.IGNORECASE)
    if not m:
        raise RuntimeError(
            f"NOVA_API_URL must be an http(s) URL, got {_redact_url(NOVA_API_URL)!r}")
    scheme, netloc = m.group(1).lower(), m.group(2)
    if scheme not in ("http", "https"):
        raise RuntimeError(
            f"NOVA_API_URL scheme must be http/https, got {scheme!r}")
    # strip userinfo / port for the loopback test
    host = netloc.split("@")[-1].split(":")[0]
    return scheme, host


_nova_scheme, _nova_host_only = _nova_host()
# Security (audit 12.2): control-plane traffic must use HTTPS unless loopback.
if _nova_scheme == "http" and not _is_loopback_host(_nova_host_only):
    raise RuntimeError(
        f"NOVA_API_URL must use https:// for non-localhost hosts "
        f"(got {_redact_url(NOVA_API_URL)!r}). The API key is sent on every request.")

NOVA_API_KEY = (os.getenv("NOVA_API_KEY") or "").strip() or None
if not NOVA_API_KEY and not _is_loopback_host(_nova_host_only):
    raise RuntimeError(
        "NOVA_API_KEY is required for non-localhost NOVA_API_URL.")
RENTAL_TOKEN_ONBOARDING = _flag("RENTAL_TOKEN_ONBOARDING", "1")

# --- Managed bots (Telegram Bot API 9.6) express setup — pilot-gated ---
MANAGED_ONBOARDING_ENABLED = _flag("MANAGED_ONBOARDING_ENABLED", "0")
MANAGER_BOT_USERNAME = (os.getenv("MANAGER_BOT_USERNAME", "") or "").strip().lstrip("@")
# Opus: button appears with an empty deep link when the username is unset.
if MANAGED_ONBOARDING_ENABLED and not MANAGER_BOT_USERNAME:
    raise RuntimeError(
        "MANAGED_ONBOARDING_ENABLED=1 requires MANAGER_BOT_USERNAME to be set")

# --- Rental support contact ---
SUPPORT_USERNAME = (os.getenv("SUPPORT_USERNAME", "") or "").strip()
SUPPORT_USERNAME = SUPPORT_USERNAME.lstrip("@")
# Opus: strip URL prefixes / illegal chars; unescaped value breaks HTML msgs.
SUPPORT_USERNAME = re.sub(r"^https?://t\.me/", "", SUPPORT_USERNAME)
if SUPPORT_USERNAME and not re.fullmatch(r"[A-Za-z0-9_]{5,32}", SUPPORT_USERNAME):
    raise RuntimeError(
        f"SUPPORT_USERNAME looks invalid: {SUPPORT_USERNAME!r}")

ETHERSCAN_API_KEY = (os.getenv("ETHERSCAN_API_KEY") or "").strip() or None

# CRYPTO_TESTNET=1 switches the bot to TESTNET_CHAINS (Sepolia / Base Sepolia)
# for end-to-end deposit testing with free funds. Mainnet unchanged when off.
CRYPTO_TESTNET = _flag("CRYPTO_TESTNET", "0")

# Opus P0 money risk: two independent testnet flags can disagree — testnet
# chains with mainnet CryptoBot invoices (or vice versa).
if CRYPTO_TESTNET != CRYPTOBOT_TESTNET:
    raise RuntimeError(
        f"CRYPTO_TESTNET ({int(CRYPTO_TESTNET)}) and CRYPTOBOT_TESTNET "
        f"({int(CRYPTOBOT_TESTNET)}) disagree — set both to the same value")

# P3.19: set WATCHER_STANDALONE=1 when the blockchain observer runs as its
# own process (nova-shop-watcher.service). The in-process watcher is then
# disabled to avoid double-scanning.
WATCHER_STANDALONE = _flag("WATCHER_STANDALONE", "0")

# Fresh TESTNET xpub (tpub) used only when CRYPTO_TESTNET is on.
# NEVER reuse a mainnet xpub here.
TESTNET_XPUB_ETH = (os.getenv("TESTNET_XPUB_ETH", "") or "").strip() or None

# Opus P0: this check used to run before TESTNET_XPUB_ETH was defined, so it
# never executed. Now placed AFTER the definition — ordering fixed.
if TESTNET_XPUB_ETH:
    if not TESTNET_XPUB_ETH.startswith(("tpub", "vpub")):
        raise RuntimeError(
            "TESTNET_XPUB_ETH must be a testnet-format key (tpub/vpub)")
    if XPUB_ETH and TESTNET_XPUB_ETH.strip() == XPUB_ETH.strip():
        raise RuntimeError(
            "Misconfigured TESTNET_XPUB_ETH: must differ from XPUB_ETH. "
            "NEVER reuse a mainnet xpub for testnet.")

# Opus: ETH chains without an Etherscan key silently miss deposits.
if XPUB_ETH and not ETHERSCAN_API_KEY:
    _log.warning(
        "XPUB_ETH is set but ETHERSCAN_API_KEY is missing — "
        "ETH/Base deposit scanning will silently fail.")

# Opus: warn when no payment rail is enabled at all — checkout is dead.
if not any([PAYMENTS_PROVIDER_TOKEN, CRYPTOBOT_TOKEN, XPUB_BTC,
            XPUB_ETH, XPUB_TRX, TON_DEPOSIT_ADDRESS]):
    _log.warning(
        "No payment rail enabled (no provider token, no xpubs, no TON "
        "address) — checkout cannot accept payments.")
