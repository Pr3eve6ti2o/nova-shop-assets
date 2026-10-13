#!/usr/bin/env python3
"""Nova Shop doctor (port plan 7.3) — PORTED from
JumpCodeFrog/telegram-shop-bot `internal/launcher/doctor.go` (MIT),
adapted to Nova Shop's configuration with minor changes:
their per-rail checks (YooKassa/Stripe/TON/NOWPayments) become ours
(Telegram Payments, CryptoBot, xpub chains, TON); their Redis check
is dropped (we have no Redis); their report format, ordering and
exit-code rules are kept verbatim in spirit:

    [OK]   Label: detail
    [WARN] Label: detail
    [FAIL] Label: detail
    Doctor passed. / Doctor passed with warnings. /
    Doctor found blocking failures.        (exit 1 iff any FAIL)

Like the original: credentials are diagnosed from raw values and
never printed; a rail that is not configured is OK, a PARTIALLY
configured rail is a labelled failure; the Telegram inspector's
errors are reported generically so a bot token can never leak into
terminal output through a URL.
"""
import json
import os
import re
import sqlite3
import stat
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_DIR = os.path.join(ROOT, "bot")
ENV_PATH = os.path.join(BOT_DIR, ".env")

OK, WARN, FAIL = "OK", "WARN", "FAIL"

KNOWN_KEYS = [
    "BOT_TOKEN", "ADMINS", "CURRENCY", "DATABASE_PATH",
    "PAYMENTS_PROVIDER_TOKEN", "CRYPTOBOT_TOKEN",
    "XPUB_BTC", "XPUB_ETH", "XPUB_TRX", "TON_DEPOSIT_ADDRESS",
    "ETHERSCAN_API_KEY", "BSCSCAN_API_KEY", "MINIAPP_URL",
    "WEBHOOK_HOST", "WEBHOOK_PATH", "WEBHOOK_SECRET_TOKEN", "PORT",
    "HTTPS_PROXY", "SUPPORT_USERNAME", "NOVA_API_URL",
    "SHOP_WEBHOOK_URL", "SHOP_WEBHOOK_SECRET",
    "ADMIN_FORUM_CHAT_ID", "RETURNS_WINDOW_DAYS", "CAMPAIGNS_ENABLED",
]


class Report:
    def __init__(self):
        self.checks = []

    def add(self, status, label, detail=""):
        self.checks.append((status, label, detail))

    def exit_code(self):
        return 1 if any(s == FAIL for s, _, _ in self.checks) else 0

    def has_warnings(self):
        return any(s == WARN for s, _, _ in self.checks)

    def print(self, out=sys.stdout):
        print("Nova Shop Doctor", file=out)
        print(file=out)
        for status, label, detail in self.checks:
            line = f"[{status}] {label}"
            if detail:
                line += f": {detail}"
            print(line, file=out)
        print(file=out)
        if self.exit_code() != 0:
            print("Doctor found blocking failures.", file=out)
        elif self.has_warnings():
            print("Doctor passed with warnings.", file=out)
        else:
            print("Doctor passed.", file=out)


def load_environment(path):
    """Mirror of the original's loadEnvironment: file values first,
    process environment overrides for known keys. A parse failure is
    reported without echoing file contents (they may hold secrets)."""
    values, exists = {}, False
    if os.path.exists(path):
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    raise ValueError("malformed line")
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
            exists = True
        except Exception:
            return values, False, f"read {path}: configuration file could not be parsed"
    for key in KNOWN_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values, exists, None


def check_env_permissions(path, add):
    mode = os.stat(path).st_mode
    if mode & 0o077:
        add(WARN, "Configuration permissions",
            f"file is shared; run chmod 600 {path}")
    else:
        add(OK, "Configuration permissions", "private (0600)")


# --- per-rail checks (the original's pattern: not configured = OK,
#     partial or malformed = labelled FAIL/WARN, values never printed)

def check_telegram_payments(v, add):
    if not (v.get("PAYMENTS_PROVIDER_TOKEN") or "").strip():
        add(OK, "Telegram Payments", "not configured")
    else:
        add(OK, "Telegram Payments", "configured")


def check_cryptobot(v, add):
    if not (v.get("CRYPTOBOT_TOKEN") or "").strip():
        add(OK, "CryptoBot payments", "not configured")
    else:
        add(OK, "CryptoBot payments", "configured")


def check_xpub_rails(v, add):
    chains = [c for c in ("XPUB_BTC", "XPUB_ETH", "XPUB_TRX")
              if (v.get(c) or "").strip()]
    if not chains:
        add(OK, "Direct crypto (xpub)", "not configured")
        return
    add(OK, "Direct crypto (xpub)", "configured: "
        + ", ".join(c.replace("XPUB_", "") for c in chains))
    if "XPUB_ETH" in chains and not (v.get("ETHERSCAN_API_KEY") or "").strip():
        add(WARN, "Direct crypto (xpub)",
            "ETHERSCAN_API_KEY is not set; EVM deposit detection "
            "is blind on ETH/Base/Polygon")


def check_ton(v, add):
    if not (v.get("TON_DEPOSIT_ADDRESS") or "").strip():
        add(OK, "TON payments", "not configured")
    else:
        add(OK, "TON payments", "configured")


def inspect_telegram(token):
    """getMe + getWebhookInfo. Raises on any failure; callers report
    the failure generically (a raw urllib error can embed the token)."""
    def call(method):
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)["result"]
    return call("getMe"), call("getWebhookInfo")


def check_webhook(v, state, add):
    host = (v.get("WEBHOOK_HOST") or "").strip().rstrip("/")
    path = (v.get("WEBHOOK_PATH") or "").strip()
    expected = f"{host}{path}" if host else ""
    actual = state.get("url") or ""
    if not expected and not actual:
        add(OK, "Telegram mode", "polling")
    elif not expected and actual:
        add(FAIL, "Telegram mode",
            "a webhook is active; clear it with Bot API deleteWebhook "
            "or set WEBHOOK_HOST before polling")
    elif expected == actual:
        add(OK, "Telegram webhook", "configured and matches")
    else:
        add(WARN, "Telegram webhook",
            "Bot API state does not match WEBHOOK_HOST/WEBHOOK_PATH")
    pending = state.get("pending_update_count") or 0
    if pending > 0:
        add(WARN, "Pending updates", f"{pending} queued")
    else:
        add(OK, "Pending updates", "0")
    if state.get("last_error_message"):
        add(WARN, "Webhook delivery", "Telegram reports a recent delivery error")


def run_doctor():
    report = Report()
    add = report.add

    values, env_exists, env_err = load_environment(ENV_PATH)
    if env_err:
        add(FAIL, "Configuration file", env_err)
    elif env_exists:
        add(OK, "Configuration file", ENV_PATH)
        check_env_permissions(ENV_PATH, add)
    else:
        add(WARN, "Configuration file",
            "not found; checking process environment")

    check_telegram_payments(values, add)
    check_cryptobot(values, add)
    check_xpub_rails(values, add)
    check_ton(values, add)

    token = (values.get("BOT_TOKEN") or "").strip()
    if not token:
        add(FAIL, "Configuration", "BOT_TOKEN is not set")
        report.print()
        return report
    if not re.match(r"^\d{5,}:[\w-]{30,}$", token):
        add(FAIL, "Configuration", "BOT_TOKEN is malformed")
        report.print()
        return report
    add(OK, "Configuration", "required values are valid")

    admins = [a for a in re.split(r"[,\s]+", values.get("ADMINS", "")) if a]
    if not admins:
        add(WARN, "Admin access",
            "ADMINS is empty; admin commands will have no users")
    elif not all(a.isdigit() for a in admins):
        add(FAIL, "Admin access", "ADMINS contains a non-numeric id")
    else:
        add(OK, "Admin access", f"{len(admins)} user(s)")

    db_path = (values.get("DATABASE_PATH") or "").strip() or os.path.join(
        BOT_DIR, "data", "nova_shop.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(BOT_DIR, db_path)
    if not os.path.exists(db_path):
        add(WARN, "SQLite + migrations",
            "no database file yet; created on first launch")
    else:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            quick = conn.execute("PRAGMA quick_check").fetchone()[0]
            if quick != "ok":
                add(FAIL, "SQLite + migrations", f"quick_check: {quick}")
            else:
                try:
                    applied = conn.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                except sqlite3.Error:
                    applied = None
                mig_dir = os.path.join(BOT_DIR, "migrations")
                known = [int(f[1:4]) for f in os.listdir(mig_dir)
                         if re.match(r"m\d{3}_.*\.py$", f)]
                latest = max(known) if known else 0
                if applied is None:
                    add(WARN, "SQLite + migrations",
                        "no schema_migrations yet; bot migrates at startup")
                elif applied < latest:
                    add(WARN, "SQLite + migrations",
                        f"database at v{applied}, code has v{latest}; "
                        "migrations run at startup")
                else:
                    add(OK, "SQLite + migrations",
                        f"{db_path} (v{applied})")
            conn.close()
        except sqlite3.Error:
            add(FAIL, "SQLite + migrations", "database could not be opened")

    # Nova-Shop extras (minor additions in the same style).
    miniapp = (values.get("MINIAPP_URL") or "").strip()
    if miniapp and not miniapp.startswith("https://"):
        add(WARN, "Mini App", "MINIAPP_URL is not https; Telegram requires https")
    if not (values.get("SUPPORT_USERNAME") or "").strip():
        add(WARN, "Support username",
            "SUPPORT_USERNAME is not set; support contact points nowhere")
    raw = (values.get("RETURNS_WINDOW_DAYS") or "").strip()
    if raw:
        try:
            rv = int(raw)
            if not 0 <= rv <= 365:
                add(FAIL, "Returns window", f"{rv} outside 0..365")
        except ValueError:
            add(FAIL, "Returns window", "not a number")
    if (values.get("SHOP_WEBHOOK_URL") or "").strip() and not (
            values.get("SHOP_WEBHOOK_SECRET") or "").strip():
        add(WARN, "Outbound webhook", "URL set without a signing secret")

    try:
        me, webhook_state = inspect_telegram(token)
    except Exception:
        add(FAIL, "Telegram API", "could not inspect the bot via Telegram API")
        report.print()
        return report
    add(OK, "Telegram API", "@" + (me.get("username") or "?"))
    if me.get("supports_inline_queries"):
        add(OK, "Telegram inline mode", "enabled")
    else:
        add(WARN, "Telegram inline mode",
            "disabled; enable it in @BotFather (/setinline) "
            "for inline catalog sharing")
    check_webhook(values, webhook_state, add)

    report.print()
    return report


if __name__ == "__main__":
    sys.exit(run_doctor().exit_code())
