"""SaaS tenant management - multi-tenant bot platform.

Pricing: $4.99/month, $49.99/year
Architecture: Shared DB with tenant_id, encrypted bot tokens
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

# Pricing
PLAN_MONTHLY = "monthly"
PLAN_YEARLY = "yearly"
PRICES = {
    PLAN_MONTHLY: 499,   # $4.99 in cents
    PLAN_YEARLY: 4999,   # $49.99 in cents
}

# Tenant statuses
STATUS_PENDING = "pending"      # Signed up, no payment yet
STATUS_TRIAL = "trial"          # In trial period
STATUS_ACTIVE = "active"        # Paid and running
STATUS_PAST_DUE = "past_due"    # Payment failed, in grace period
STATUS_SUSPENDED = "suspended"  # Suspended for non-payment
STATUS_CANCELLED = "cancelled"  # Cancelled by customer

GRACE_PERIOD_DAYS = 3

# Feature flags (toggleable by customers)
FEATURES = {
    "crypto_payments": {"name": "Crypto Payments", "default": True},
    "fiat_payments": {"name": "Card Payments", "default": True},
    "telegram_stars": {"name": "Telegram Stars", "default": True},
    "reviews": {"name": "Product Reviews", "default": False},
    "promos": {"name": "Promo Codes", "default": True},
    "referrals": {"name": "Referral Program", "default": True},
    "balance_system": {"name": "Wallet Balance", "default": True},
    "broadcast": {"name": "Broadcast Messages", "default": True},
    "analytics": {"name": "Analytics Dashboard", "default": True},
}


def generate_webhook_secret() -> str:
    """Generate a secure webhook secret for Telegram."""
    return secrets.token_urlsafe(32)


def hash_webhook_secret(secret: str) -> str:
    """Hash webhook secret for storage (never store plaintext)."""
    return hashlib.sha256(secret.encode()).hexdigest()


def _normalize_dt(dt: datetime) -> datetime | None:
    """Normalize datetime for comparison: strip tzinfo, handle strings.
    SQLite returns naive datetimes; API may give aware ones or ISO strings."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        # Convert to UTC first: stripping tzinfo without converting shifts
        # the wall clock (e.g. +02:00 would grant 2 extra hours of service).
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt if isinstance(dt, datetime) else None


def calculate_period_end(plan: str, start: datetime = None) -> datetime:
    """Calculate subscription period end date. Plan must be a known constant."""
    if plan not in (PLAN_MONTHLY, PLAN_YEARLY):
        raise ValueError(f"Unknown plan: {plan!r}")
    start = _normalize_dt(start) or datetime.utcnow()
    if plan == PLAN_MONTHLY:
        return start + timedelta(days=30)
    return start + timedelta(days=365)


def is_tenant_active(status: str, period_end: datetime = None) -> bool:
    """Check if tenant should be serving traffic.

    Fail closed: paid/trial/past-due tenants must have a valid period_end.
    An expired subscription means no service, even if status says active.
    period_end must come from server-side billing data, never tenant input.
    """
    now = datetime.utcnow()
    period_end = _normalize_dt(period_end)
    if status in (STATUS_ACTIVE, STATUS_TRIAL):
        return period_end is not None and now < period_end
    if status == STATUS_PAST_DUE:
        if period_end is None:
            return False
        grace_end = period_end + timedelta(days=GRACE_PERIOD_DAYS)
        return now < grace_end
    return False


# SQL schema for SaaS tables
SAAS_SCHEMA = """
-- SaaS tenants table
CREATE TABLE IF NOT EXISTS saas_tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    plan TEXT,
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT UNIQUE,
    current_period_end TIMESTAMP,
    bot_token_encrypted BLOB,
    bot_token_fingerprint TEXT,
    bot_username TEXT,
    webhook_secret_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON saas_tenants(status);
CREATE INDEX IF NOT EXISTS idx_tenants_stripe ON saas_tenants(stripe_customer_id);

-- Per-tenant feature flags
CREATE TABLE IF NOT EXISTS saas_tenant_features (
    tenant_id INTEGER NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    config TEXT,
    PRIMARY KEY (tenant_id, feature_key)
);

-- Audit log for sensitive operations.
-- NOTE: no ON DELETE CASCADE here on purpose: deleting a tenant must NOT
-- erase its audit trail. tenant_id is nulled instead.
CREATE TABLE IF NOT EXISTS saas_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER REFERENCES saas_tenants(id) ON DELETE SET NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON saas_audit_log(tenant_id, created_at);
"""
