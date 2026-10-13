"""Shared helpers: money formatting, pagination, ids, time."""
import html
import secrets
import string
from datetime import datetime, timezone

CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "RUB": "\u20bd",
    "UAH": "\u20b4", "KZT": "\u20b8", "BYN": "Br", "PLN": "z\u0142",
}


def fmt_money(cents: int, currency: str = "USD") -> str:
    """Format integer cents as a money string, e.g. 1299 -> '$12.99'."""
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    amount = f"{cents // 100}.{cents % 100:02d}"
    symbol = CURRENCY_SYMBOLS.get((currency or "USD").upper())
    if symbol:
        return f"{sign}{symbol}{amount}"
    return f"{sign}{amount} {(currency or 'USD').upper()}"


def stars_for_cents(cents: int, stars_per_usd: int, currency: str = "USD") -> int:
    """Convert fiat cents to whole Telegram Stars (XTR smallest unit = 1 star)."""
    if (currency or "USD").upper() != "USD":
        raise ValueError("stars_for_cents requires USD; convert order total to USD first")
    # Opus P0/P1: was silently returning 0 for non-positive cents or
    # misconfigured rate — a 0-star invoice means free goods (money loss).
    # Raise explicitly so misconfiguration fails loudly.
    if not isinstance(cents, int) or isinstance(cents, bool):
        raise ValueError(f"cents must be int, got {type(cents).__name__}")
    if cents <= 0:
        raise ValueError(f"cents must be positive, got {cents}")
    if not isinstance(stars_per_usd, int) or isinstance(stars_per_usd, bool):
        raise ValueError(f"stars_per_usd must be int, got {type(stars_per_usd).__name__}")
    if stars_per_usd <= 0:
        raise ValueError(f"stars_per_usd must be positive, got {stars_per_usd}")
    # ceil(cents / 100 * stars_per_usd)
    return max(1, -(-cents * stars_per_usd // 100))


def paginate(total: int, page: int, per_page: int):
    """Clamp page into range; return (page, total_pages)."""
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    total_pages = max(1, -(-max(0, total) // per_page))
    page = max(0, min(page, total_pages - 1))
    return page, total_pages


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_ref_code(length: int = 8) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def cb(*parts) -> str:
    """Build short callback data from integer ids. Never put names/prices here."""
    # Opus P1: validate parts contain only safe characters. Colons are
    # allowed in hardcoded namespace prefixes (e.g. "ad:ord") but the
    # character whitelist prevents injection of malicious content.
    # '+' is allowed for the quantity steppers' "+1" delta (keyboards
    # product_kb/cart_kb) — found by the usability smoke: without it,
    # opening a product card raised ValueError in this validator.
    # User-controlled values must still be validated by callers before
    # being passed here.
    import re
    cleaned = []
    for p in parts:
        s = str(p)
        if not s:
            raise ValueError(f"callback part must be non-empty: {s!r}")
        if not re.fullmatch(r"[A-Za-z0-9_:\-+]+", s):
            raise ValueError(f"callback part has unsafe characters: {s!r}")
        cleaned.append(s)
    data = ":".join(cleaned)
    if len(data.encode("utf-8")) > 64:
        raise ValueError("callback_data exceeds 64 bytes")
    return data


def truncate(text: str, limit: int) -> str:
    # Opus P1: guard limit <= 0 (was: negative slice gave nonsense).
    # Note: callers must truncate BEFORE HTML-escaping — cutting mid-entity
    # like "&amp;" produces invalid markup that breaks message delivery.
    if limit <= 0:
        return ""
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def h(s) -> str:
    """HTML-escape a DB/user string for parse_mode="HTML" messages.

    Prevents stored-HTML phishing via product names/descriptions edited
    in the Payload CMS (security audit #6).
    """
    return html.escape("" if s is None else str(s), quote=True)
