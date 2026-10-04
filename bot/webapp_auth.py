"""Telegram WebApp initData validation (HMAC-SHA256).

Algorithm (per Telegram docs):
  1. Parse the query string into pairs; drop `hash`.
  2. Sort keys alphabetically; join as "k=v\\n".
  3. secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
  4. expected = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()
  5. compare_digest(expected, received hash).

Used by the future backend-API upgrade path (see miniapp/README.md).
"""
import hashlib
import hmac
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str,
                       max_age_seconds: int = 86400) -> dict | None:
    """Validate Telegram WebApp initData. Returns the parsed dict or None."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received = pairs.pop("hash", None)
    if not received:
        return None
    check_str = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received.lower()):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age_seconds:
            return None
    except (TypeError, ValueError):
        return None
    return pairs


def make_test_vector(bot_token: str) -> str:
    """Build a VALID initData string for tests (not for production use)."""
    import urllib.parse
    pairs = {
        "query_id": "AAETEST",
        "user": '{"id":123,"first_name":"Test"}',
        "auth_date": str(int(time.time())),
    }
    check_str = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = sig
    return urllib.parse.urlencode(pairs)
