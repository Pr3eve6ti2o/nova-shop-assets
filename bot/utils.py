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
    if cents <= 0 or stars_per_usd <= 0:
        return 0
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
    data = ":".join(str(p) for p in parts)
    if len(data.encode("utf-8")) > 64:
        raise ValueError("callback_data exceeds 64 bytes")
    return data


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def h(s) -> str:
    """HTML-escape a DB/user string for parse_mode="HTML" messages.

    Prevents stored-HTML phishing via product names/descriptions edited
    in the Payload CMS (security audit #6).
    """
    return html.escape("" if s is None else str(s), quote=True)
