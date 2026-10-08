"""Async SQLite storage for Nova Shop Bot (aiosqlite, per-operation connections).

Money is always integer cents. Rows are dict-like (aiosqlite.Row).
"""
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import aiosqlite

import config
from utils import utcnow_iso, new_ref_code

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, tg_id INTEGER UNIQUE NOT NULL, name TEXT,
  phone TEXT, address TEXT, is_blocked INTEGER DEFAULT 0,
  ref_code TEXT UNIQUE, referred_by INTEGER REFERENCES users(id),
  role_mask INTEGER DEFAULT 0, balance_cents INTEGER NOT NULL DEFAULT 0,
  has_rental INTEGER NOT NULL DEFAULT 0,
  has_rental_history INTEGER NOT NULL DEFAULT 0,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, emoji TEXT DEFAULT '\U0001f4e6',
  sort INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, category_id INTEGER REFERENCES categories(id),
  name TEXT NOT NULL, description TEXT DEFAULT '', photo_file_id TEXT,
  price_cents INTEGER NOT NULL, old_price_cents INTEGER,
  kind TEXT NOT NULL DEFAULT 'physical',
  stock INTEGER NOT NULL DEFAULT -1,
  rating_sum INTEGER DEFAULT 0, rating_count INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1,
  is_unlimited INTEGER DEFAULT 0,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS product_values(
  id INTEGER PRIMARY KEY, product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  value TEXT NOT NULL, is_used INTEGER DEFAULT 0, used_in_order INTEGER,
  UNIQUE(product_id, value));
CREATE TABLE IF NOT EXISTS cart_items(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  qty INTEGER NOT NULL, UNIQUE(user_id, product_id));
CREATE TABLE IF NOT EXISTS wishlist(
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE(user_id, product_id));
CREATE TABLE IF NOT EXISTS promos(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
  value INTEGER NOT NULL,
  max_uses INTEGER DEFAULT 0, used_count INTEGER DEFAULT 0,
  min_subtotal_cents INTEGER DEFAULT 0,
  expires_at TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS promo_usages(promo_id INTEGER, user_id INTEGER,
  used_at TEXT, UNIQUE(promo_id, user_id));
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',
  subtotal_cents INTEGER, discount_cents INTEGER DEFAULT 0, total_cents INTEGER,
  payment_method TEXT,
  delivery_kind TEXT,
  address TEXT, phone TEXT, promo_code TEXT,
  created_at TEXT, updated_at TEXT,
  claimed_at TEXT);
CREATE TABLE IF NOT EXISTS order_items(
  order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER, name TEXT, qty INTEGER, price_cents INTEGER,
  delivered_value TEXT);
CREATE TABLE IF NOT EXISTS tonconnect_intent_claims(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  intent_id TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL UNIQUE,
  expected_nano INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  used_at TEXT);
CREATE TABLE IF NOT EXISTS payment_observations(
  id INTEGER PRIMARY KEY,
  chain TEXT NOT NULL,
  chain_id INTEGER NOT NULL DEFAULT 0,
  asset TEXT NOT NULL,
  token_contract TEXT NOT NULL DEFAULT 'native',
  tx_hash TEXT NOT NULL,
  log_index INTEGER NOT NULL DEFAULT 0,
  block_height INTEGER,
  block_hash TEXT,
  amount_atomic TEXT NOT NULL,
  recipient TEXT NOT NULL,
  memo TEXT,
  observed_at TEXT NOT NULL,
  finalized_at TEXT,
  state TEXT NOT NULL DEFAULT 'observed',
  UNIQUE(chain_id, token_contract, tx_hash, log_index));
CREATE INDEX IF NOT EXISTS ix_observations_chain_recipient
  ON payment_observations(chain, recipient, state);
CREATE TABLE IF NOT EXISTS reconciliation_cursors(
  chain TEXT PRIMARY KEY,
  last_block_height INTEGER,
  last_observed_at TEXT,
  updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox_events(
  id INTEGER PRIMARY KEY,
  event_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  last_error TEXT,
  processed_at TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
  external_id TEXT NOT NULL, user_id INTEGER, order_id INTEGER,
  amount_cents INTEGER, currency TEXT, status TEXT DEFAULT 'pending',
  created_at TEXT, UNIQUE(provider, external_id));
CREATE TABLE IF NOT EXISTS reviews(
  user_id INTEGER, product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  rating INTEGER CHECK(rating BETWEEN 1 AND 5), text TEXT, created_at TEXT,
  UNIQUE(user_id, product_id));
CREATE TABLE IF NOT EXISTS referral_earnings(
  id INTEGER PRIMARY KEY, referrer_id INTEGER, referee_id INTEGER,
  order_id INTEGER UNIQUE, amount_cents INTEGER, created_at TEXT);
-- One-time first-paid-order credit claim per referee (race guard).
CREATE TABLE IF NOT EXISTS referral_claims(
  referee_id INTEGER PRIMARY KEY, claimed_at TEXT);
CREATE TABLE IF NOT EXISTS stock_alerts(
  user_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, product_id));
CREATE TABLE IF NOT EXISTS tonconnect_pending(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, sender TEXT NOT NULL,
  amount_nano INTEGER NOT NULL, items_json TEXT NOT NULL, promo_code TEXT,
  claim_code TEXT,
  created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS tonconnect_claims(
  user_id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL,
  created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, ts TEXT, actor_tg_id INTEGER, action TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS balance_transactions(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  type TEXT NOT NULL, amount_cents INTEGER NOT NULL,
  balance_after_cents INTEGER NOT NULL, order_id INTEGER REFERENCES orders(id),
  created_at TEXT DEFAULT (datetime('now')));
-- Crypto payments (SPEC2): never alter v1 tables above.
CREATE TABLE IF NOT EXISTS crypto_deposits(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  chain TEXT NOT NULL, address TEXT NOT NULL, derivation_index INTEGER,
  memo TEXT, expected_crypto TEXT NOT NULL, expected_usd_cents INTEGER NOT NULL,
  status TEXT DEFAULT 'pending',
  txid TEXT, confirmations INTEGER DEFAULT 0, seen_amount_crypto TEXT,
  created_at TEXT, expires_at TEXT, purpose TEXT DEFAULT 'order',
  topup_user_id INTEGER, UNIQUE(chain, txid));
CREATE TABLE IF NOT EXISTS cryptobot_invoices(
  id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  invoice_id INTEGER UNIQUE NOT NULL, asset TEXT, amount TEXT,
  status TEXT DEFAULT 'active', created_at TEXT, purpose TEXT DEFAULT 'order',
  topup_user_id INTEGER,
  fee_pct INTEGER);
-- Performance indexes (Step 1b)
CREATE INDEX IF NOT EXISTS idx_products_category_active ON products(category_id, is_active);
CREATE INDEX IF NOT EXISTS idx_categories_active ON categories(is_active);
CREATE INDEX IF NOT EXISTS idx_orders_user_status ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id);
CREATE INDEX IF NOT EXISTS idx_promos_code ON promos(code);
"""


def _dict_factory(cursor, row):
    """Row factory returning plain dicts instead of sqlite3.Row.
    Eliminates Row-vs-dict confusion (.get() works, JSON serializable)."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class Database:
    def __init__(self, path: str):
        self._memory = path == ":memory:"
        self._keepalive = None
        # Serializes conditional-write ("claim") operations. aiosqlite cursors
        # can report stale rowcounts when operations interleave across its
        # worker threads; holding this lock makes the write+check atomic at
        # the asyncio level (the SQL WHERE clause remains the DB-level guard).
        self._claim_lock = asyncio.Lock()
        if self._memory:
            self.path = f"file:nova_shop_{id(self)}?mode=memory&cache=shared"
        else:
            self.path = path
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)

    @asynccontextmanager
    async def _db(self):
        """Per-operation connection: dict row factory + FK pragmas, auto-closed."""
        if self._memory and self._keepalive is None:
            self._keepalive = await aiosqlite.connect(self.path, uri=True)
            self._keepalive.row_factory = _dict_factory
            await self._keepalive.execute("PRAGMA foreign_keys = ON")
        async with aiosqlite.connect(self.path, uri=self._memory) as db:
            db.row_factory = _dict_factory
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    async def create_tables(self):
        async with self._db() as db:
            # Migrations FIRST (before SCHEMA indexes reference new columns)
            # Migration: add is_active to categories if missing (for older DBs)
            try:
                await db.execute("ALTER TABLE categories ADD COLUMN is_active INTEGER DEFAULT 1")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add min_subtotal_cents to promos if missing
            try:
                await db.execute("ALTER TABLE promos ADD COLUMN min_subtotal_cents INTEGER DEFAULT 0")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add balance_cents to users if missing
            try:
                await db.execute("ALTER TABLE users ADD COLUMN balance_cents INTEGER NOT NULL DEFAULT 0")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add has_rental to users if missing (persistent "My Rental"
            # menu button once the user has ever subscribed, even one time).
            try:
                await db.execute("ALTER TABLE users ADD COLUMN has_rental INTEGER NOT NULL DEFAULT 0")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
            # Migration: rename has_rental -> has_rental_history (audit 12).
            # The field is UI convenience only, never an authorisation source.
            try:
                await db.execute("ALTER TABLE users ADD COLUMN has_rental_history INTEGER NOT NULL DEFAULT 0")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            try:
                await db.execute("UPDATE users SET has_rental_history = has_rental WHERE has_rental_history = 0")
            except aiosqlite.OperationalError:
                pass  # column may not exist on very old DBs; harmless

            # Migration: EVM transfer identity (audit 4.1). UNIQUE(chain, txid)
            # cannot distinguish two ERC-20 Transfer events in one transaction.
            # New identity: (chain_id, token_contract, txid, log_index).
            for _ddl in (
                "ALTER TABLE crypto_deposits ADD COLUMN chain_id INTEGER",
                "ALTER TABLE crypto_deposits ADD COLUMN token_contract TEXT NOT NULL DEFAULT 'native'",
                "ALTER TABLE crypto_deposits ADD COLUMN log_index INTEGER NOT NULL DEFAULT 0",
            ):
                try:
                    await db.execute(_ddl)
                except aiosqlite.OperationalError as e:
                    _m = str(e).lower()
                    if "duplicate column name" not in _m and "no such table" not in _m:
                        raise
            try:
                await db.execute(
                    "UPDATE crypto_deposits SET chain_id = CASE lower(chain) "
                    "WHEN 'eth' THEN 1 WHEN 'ethereum' THEN 1 "
                    "WHEN 'usdt_base' THEN 8453 WHEN 'usdc_base' THEN 8453 "
                    "WHEN 'usdt_op' THEN 10 WHEN 'usdc_op' THEN 10 "
                    "WHEN 'usdt_polygon' THEN 137 WHEN 'usdc_polygon' THEN 137 "
                    "ELSE 0 END WHERE chain_id IS NULL")
                await db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_crypto_deposits_transfer "
                    "ON crypto_deposits (chain_id, token_contract, txid, log_index) "
                    "WHERE txid IS NOT NULL")
            except aiosqlite.OperationalError as e:
                _m = str(e).lower()
                if "no such table" not in _m:
                    raise
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add purpose/topup_user_id to crypto_deposits if missing
            try:
                await db.execute("ALTER TABLE crypto_deposits ADD COLUMN purpose TEXT DEFAULT 'order'")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            try:
                await db.execute("ALTER TABLE crypto_deposits ADD COLUMN topup_user_id INTEGER")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add purpose/topup_user_id to cryptobot_invoices if missing
            try:
                await db.execute("ALTER TABLE cryptobot_invoices ADD COLUMN purpose TEXT DEFAULT 'order'")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            try:
                await db.execute("ALTER TABLE cryptobot_invoices ADD COLUMN topup_user_id INTEGER")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add fee_pct to cryptobot_invoices if missing
            try:
                await db.execute("ALTER TABLE cryptobot_invoices ADD COLUMN fee_pct INTEGER")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add is_unlimited to products if missing (for older DBs)
            try:
                await db.execute("ALTER TABLE products ADD COLUMN is_unlimited INTEGER DEFAULT 0")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add claim_code to tonconnect_pending if missing
            try:
                await db.execute("ALTER TABLE tonconnect_pending ADD COLUMN claim_code TEXT")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            # Migration: add claimed_at to orders if missing
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN claimed_at TEXT")
            except aiosqlite.OperationalError as e:
                msg = str(e).lower()
                # "duplicate column name": already migrated; "no such table":
                # fresh DB, SCHEMA creates the table below. Anything else is real.
                if "duplicate column name" not in msg and "no such table" not in msg:
                    raise
            await db.executescript(SCHEMA)
            await db.execute(
                "INSERT OR IGNORE INTO kv(key, value) VALUES ('maintenance_mode','0')")
            await db.execute(
                "INSERT OR IGNORE INTO kv(key, value) VALUES ('referral_percent', ?)",
                (str(config.REFERRAL_PERCENT),),
            )
            await db.commit()

    # ------------------------------------------------------------- kv ---
    async def kv_get(self, key: str, default=None):
        async with self._db() as db:
            async with db.execute("SELECT value FROM kv WHERE key=?", (key,)) as cur:
                row = await cur.fetchone()
                return row["value"] if row else default

    async def kv_set(self, key: str, value: str):
        async with self._db() as db:
            await db.execute(
                "INSERT INTO kv(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def maintenance_on(self) -> bool:
        return (await self.kv_get("maintenance_mode", "0")) == "1"

    async def referral_percent(self) -> int:
        try:
            return int(await self.kv_get("referral_percent",
                                         str(config.REFERRAL_PERCENT)))
        except (TypeError, ValueError):
            return config.REFERRAL_PERCENT

    # ---------------------------------------------------------- users ---
    async def get_user_by_tg(self, tg_id: int):
        async with self._db() as db:
            async with db.execute("SELECT * FROM users WHERE tg_id=?",
                                  (tg_id,)) as cur:
                return await cur.fetchone()

    async def get_user(self, user_id: int):
        async with self._db() as db:
            async with db.execute("SELECT * FROM users WHERE id=?",
                                  (user_id,)) as cur:
                return await cur.fetchone()

    async def set_has_rental_history(self, tg_id: int):
        """Mark that the user has had a rental (UI convenience, NOT authorisation)."""
        async with self._db() as db:
            await db.execute(
                "UPDATE users SET has_rental_history=1, has_rental=1 WHERE tg_id=?",
                (tg_id,),
            )
            await db.commit()

    async def set_has_rental(self, tg_id: int):
        """Deprecated: use set_has_rental_history."""
        await self.set_has_rental_history(tg_id)
        """Mark that this Telegram user has subscribed at least once.

        Drives the persistent "My Rental" main-menu button (a sort of
        invoice view). Set on every successful subscription; never cleared.
        """
        async with self._db() as db:
            await db.execute("UPDATE users SET has_rental=1 WHERE tg_id=?",
                             (tg_id,))
            await db.commit()

    async def get_user_by_ref_code(self, code: str):
        async with self._db() as db:
            async with db.execute("SELECT * FROM users WHERE ref_code=?",
                                  (code,)) as cur:
                return await cur.fetchone()

    async def create_user(self, tg_id: int, name: str, referred_by=None):
        for _ in range(5):
            code = new_ref_code()
            try:
                async with self._db() as db:
                    await db.execute(
                        "INSERT INTO users(tg_id, name, ref_code, referred_by, created_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (tg_id, name, code, referred_by, utcnow_iso()),
                    )
                    await db.commit()
                break
            except aiosqlite.IntegrityError as e:
                msg = str(e)
                if "UNIQUE constraint failed: users.ref_code" in msg:
                    continue
                if "UNIQUE constraint failed: users.tg_id" in msg:
                    break
                if "FOREIGN KEY constraint failed" in msg:
                    raise ValueError("invalid referred_by") from e
                raise
        return await self.get_user_by_tg(tg_id)

    async def update_user(self, user_id: int, **fields):
        # Profile fields only — role_mask/is_blocked require update_user_admin
        allowed = {"name", "phone", "address"}
        sets = [f"{k}=?" for k in fields if k in allowed]
        if not sets:
            return
        vals = [fields[k] for k in fields if k in allowed]
        async with self._db() as db:
            await db.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE id=?",
                (*vals, user_id),
            )
            await db.commit()

    async def update_user_admin(self, user_id: int, **fields):
        """Admin-only: can set role_mask, is_blocked. Callers must verify admin."""
        allowed = {"role_mask", "is_blocked", "name", "phone", "address"}
        sets = [f"{k}=?" for k in fields if k in allowed]
        if not sets:
            return
        vals = [fields[k] for k in fields if k in allowed]
        async with self._db() as db:
            await db.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE id=?",
                (*vals, user_id),
            )
            await db.commit()

    async def get_balance(self, user_id: int) -> int:
        """Get user's USDT balance in cents."""
        async with self._db() as db:
            async with db.execute(
                "SELECT balance_cents FROM users WHERE id=?", (user_id,)) as cur:
                row = await cur.fetchone()
                return row["balance_cents"] if row else 0

    async def add_balance(self, user_id: int, amount_cents: int,
                         tx_type: str = "topup", order_id: int = None) -> int:
        """Add to balance (topup/refund). Applies 5% bonus on topups. Returns new balance."""
        import config as cfg
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        # Apply deposit bonus on topups
        bonus = 0
        if tx_type == "topup":
            bonus = amount_cents * cfg.DEPOSIT_BONUS_PERCENT // 100
        total = amount_cents + bonus
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE users SET balance_cents = balance_cents + ? WHERE id=?",
                (total, user_id))
            if cur.rowcount == 0:
                raise ValueError("user not found")
            async with db.execute(
                "SELECT balance_cents FROM users WHERE id=?", (user_id,)) as cur:
                new_bal = (await cur.fetchone())["balance_cents"]
            await db.execute(
                "INSERT INTO balance_transactions"
                "(user_id, type, amount_cents, balance_after_cents, order_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, tx_type, total, new_bal, order_id))
            await db.commit()
            return new_bal

    async def deduct_balance(self, user_id: int, amount_cents: int,
                            order_id: int = None) -> int | None:
        """Deduct from balance for purchase. Returns new balance or None if insufficient.
        Uses atomic UPDATE to prevent double-spend race conditions."""
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        async with self._claim_lock:
            async with self._db() as db:
                # Atomic: only deduct if sufficient balance (prevents race)
                cur = await db.execute(
                    "UPDATE users SET balance_cents = balance_cents - ? "
                    "WHERE id=? AND balance_cents >= ?",
                    (amount_cents, user_id, amount_cents))
                if cur.rowcount == 0:
                    return None
                async with db.execute(
                    "SELECT balance_cents FROM users WHERE id=?", (user_id,)) as cur2:
                    new_bal = (await cur2.fetchone())["balance_cents"]
                await db.execute(
                    "INSERT INTO balance_transactions"
                    "(user_id, type, amount_cents, balance_after_cents, order_id)"
                    " VALUES (?, 'purchase', ?, ?, ?)",
                    (user_id, -amount_cents, new_bal, order_id))
                await db.commit()
                return new_bal

    async def count_users(self) -> int:
        async with self._db() as db:
            async with db.execute("SELECT COUNT(*) c FROM users") as cur:
                return (await cur.fetchone())["c"]

    async def count_new_users_24h(self) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM users WHERE datetime(created_at) >= "
                "datetime('now', '-1 day')") as cur:
                return (await cur.fetchone())["c"]

    async def count_blocked_users(self) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM users WHERE is_blocked=1") as cur:
                return (await cur.fetchone())["c"]

    async def all_active_tg_ids(self):
        async with self._db() as db:
            async with db.execute(
                "SELECT tg_id FROM users WHERE is_blocked=0") as cur:
                return [r["tg_id"] for r in await cur.fetchall()]

    # ----------------------------------------------------- categories ---
    async def list_categories(self):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM categories ORDER BY sort, name") as cur:
                return await cur.fetchall()

    async def get_category(self, cid: int):
        async with self._db() as db:
            async with db.execute("SELECT * FROM categories WHERE id=?",
                                  (cid,)) as cur:
                return await cur.fetchone()

    async def add_category(self, name: str, emoji: str = "\U0001f4e6") -> int:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO categories(name, emoji) VALUES (?, ?)", (name, emoji))
            await db.commit()
            return cur.lastrowid

    async def rename_category(self, cid: int, name: str):
        async with self._db() as db:
            await db.execute("UPDATE categories SET name=? WHERE id=?",
                             (name, cid))
            await db.commit()

    async def delete_category(self, cid: int):
        async with self._db() as db:
            await db.execute("DELETE FROM categories WHERE id=?", (cid,))
            await db.commit()

    # ------------------------------------------------------- products ---
    async def get_product(self, pid: int):
        async with self._db() as db:
            async with db.execute("SELECT * FROM products WHERE id=?",
                                  (pid,)) as cur:
                return await cur.fetchone()

    async def list_products(self, category_id: int, limit: int, offset: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM products WHERE category_id=? AND is_active=1"
                " ORDER BY id LIMIT ? OFFSET ?",
                (category_id, limit, offset)) as cur:
                return await cur.fetchall()

    async def list_all_active_products(self, limit: int = 50, offset: int = 0):
        """List all active products across categories (for /catalog)."""
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM products WHERE is_active=1"
                " ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset)) as cur:
                return await cur.fetchall()

    async def count_active_products(self, category_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM products WHERE category_id=? AND is_active=1",
                (category_id,)) as cur:
                return (await cur.fetchone())["c"]

    async def count_products_in_category(self, cid: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM products WHERE category_id=?",
                (cid,)) as cur:
                return (await cur.fetchone())["c"]

    async def search_products(self, q: str, limit: int, offset: int):
        like = f"%{q}%"
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM products WHERE is_active=1 AND name LIKE ?"
                " ORDER BY id LIMIT ? OFFSET ?",
                (like, limit, offset)) as cur:
                return await cur.fetchall()

    async def count_search(self, q: str) -> int:
        like = f"%{q}%"
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM products WHERE is_active=1 AND name LIKE ?",
                (like,)) as cur:
                return (await cur.fetchone())["c"]

    async def list_all_products_in_category(self, category_id: int, limit: int,
                                            offset: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM products WHERE category_id=?"
                " ORDER BY id DESC LIMIT ? OFFSET ?",
                (category_id, limit, offset)) as cur:
                return await cur.fetchall()

    async def list_all_products(self, limit: int, offset: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM products ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)) as cur:
                return await cur.fetchall()

    async def count_all_products(self) -> int:
        async with self._db() as db:
            async with db.execute("SELECT COUNT(*) c FROM products") as cur:
                return (await cur.fetchone())["c"]

    async def add_product(self, *, category_id, name, description="", photo_file_id=None,
                          price_cents, old_price_cents=None, kind="physical",
                          stock=-1, is_unlimited=0) -> int:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO products(category_id, name, description, photo_file_id,"
                " price_cents, old_price_cents, kind, stock, is_unlimited, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (category_id, name, description, photo_file_id, price_cents,
                 old_price_cents, kind, stock, is_unlimited, utcnow_iso()),
            )
            await db.commit()
            return cur.lastrowid

    async def update_product(self, pid: int, **fields):
        allowed = {"category_id", "name", "description", "photo_file_id",
                   "price_cents", "old_price_cents", "kind", "stock",
                   "is_active", "is_unlimited", "rating_sum", "rating_count"}
        sets = [f"{k}=?" for k in fields if k in allowed]
        if not sets:
            return
        vals = [fields[k] for k in fields if k in allowed]
        async with self._db() as db:
            await db.execute(
                f"UPDATE products SET {', '.join(sets)} WHERE id=?",
                (*vals, pid),
            )
            await db.commit()

    async def delete_product(self, pid: int):
        async with self._db() as db:
            await db.execute("DELETE FROM products WHERE id=?", (pid,))
            await db.commit()

    async def decrement_stock(self, product_id: int, qty: int) -> int:
        """Atomically decrement physical stock by qty.

        Single conditional statement: concurrent checkouts cannot oversell.
        Returns affected rows: 1 on success (or for unlimited stock),
        0 when stock is insufficient. stock = -1 (unlimited/digital) is
        matched but never modified.
        """
        if qty <= 0:
            raise ValueError("qty must be positive")
        async with self._claim_lock:
            async with self._db() as db:
                cur = await db.execute(
                    "UPDATE products SET stock = CASE WHEN stock = -1"
                    " THEN -1 ELSE stock - ? END"
                    " WHERE id=? AND (stock = -1 OR stock >= ?)",
                    (qty, product_id, qty),
                )
                # Capture rowcount before commit (see set_order_status note).
                n = cur.rowcount
                await db.commit()
                return n

    async def increment_stock(self, product_id: int, qty: int) -> int:
        """Atomically increment physical stock by qty.

        Used to restore stock when an order is cancelled after decrements.
        stock = -1 (unlimited/digital) is never modified.
        """
        if qty <= 0:
            raise ValueError("qty must be positive")
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE products SET stock = CASE WHEN stock = -1"
                " THEN -1 ELSE stock + ? END"
                " WHERE id=?",
                (qty, product_id),
            )
            n = cur.rowcount
            await db.commit()
            return n

    async def top_products(self, limit: int = 5):
        async with self._db() as db:
            async with db.execute(
                "SELECT oi.name, SUM(oi.qty) qty, SUM(oi.qty * oi.price_cents) revenue"
                " FROM order_items oi"
                " JOIN orders o ON o.id = oi.order_id"
                " WHERE o.status IN ('confirmed','preparing','shipped','delivered')"
                " GROUP BY oi.product_id, oi.name ORDER BY qty DESC LIMIT ?",
                (limit,)) as cur:
                return await cur.fetchall()

    # ------------------------------------------------- product values ---
    async def add_product_values(self, product_id: int, values):
        async with self._db() as db:
            await db.executemany(
                "INSERT OR IGNORE INTO product_values(product_id, value) VALUES (?, ?)",
                [(product_id, v) for v in values if v],
            )
            await db.commit()

    async def unused_values_count(self, product_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM product_values"
                " WHERE product_id=? AND is_used=0",
                (product_id,)) as cur:
                return (await cur.fetchone())["c"]


    async def fulfill_order_atomic(self, order_id: int) -> tuple:
        """Fulfill an order in ONE transaction (audit 3.2).

        Claims digital values, decrements physical stock, writes delivered
        values, and marks the order fulfilled — all under a single
        BEGIN IMMEDIATE. Any failure rolls back the whole thing atomically,
        so partial fulfillment can never persist and no compensation
        rollback is needed.

        Returns (True, "") on success, or (False, reason) where reason is
        one of 'not_found', 'already_fulfilled', 'product_unavailable',
        'out_of_keys', 'out_of_stock'. Nothing is persisted on failure.
        """
        now = utcnow_iso()
        async with self._claim_lock:
            async with self._db() as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    async with db.execute(
                            "SELECT * FROM orders WHERE id=?", (order_id,)) as cur:
                        order = await cur.fetchone()
                    if not order:
                        await db.execute("ROLLBACK")
                        return False, "not_found"
                    if order["status"] == "fulfilled":
                        await db.execute("ROLLBACK")
                        return False, "already_fulfilled"

                    async with db.execute(
                            "SELECT * FROM order_items WHERE order_id=?",
                            (order_id,)) as cur:
                        items = await cur.fetchall()

                    for it in items:
                        async with db.execute(
                                "SELECT * FROM products WHERE id=?",
                                (it["product_id"],)) as cur:
                            p = await cur.fetchone()
                        if not p or not p["is_active"]:
                            await db.execute("ROLLBACK")
                            return False, f"product {it['name']} unavailable"
                        if p["kind"] == "digital":
                            if not p["is_unlimited"]:
                                async with db.execute(
                                        "SELECT id, value FROM product_values"
                                        " WHERE product_id=? AND is_used=0"
                                        " ORDER BY id LIMIT ?",
                                        (p["id"], it["qty"])) as cur:
                                    rows = await cur.fetchall()
                                if len(rows) < it["qty"]:
                                    await db.execute("ROLLBACK")
                                    return False, f"out of keys: {p['name']}"
                                ids = [r["id"] for r in rows]
                                await db.execute(
                                    "UPDATE product_values SET is_used=1,"
                                    " used_in_order=? WHERE id IN (%s)"
                                    % ",".join("?" * len(ids)),
                                    (order_id, *ids),
                                )
                                vals = "\n".join(r["value"] for r in rows)
                                await db.execute(
                                    "UPDATE order_items SET delivered_value=?"
                                    " WHERE rowid=(SELECT rowid FROM order_items"
                                    " WHERE order_id=? AND product_id=?"
                                    " ORDER BY rowid LIMIT 1)",
                                    (vals, order_id, p["id"]),
                                )
                        else:
                            if p["stock"] != -1:
                                cur = await db.execute(
                                    "UPDATE products SET stock = stock - ?"
                                    " WHERE id=? AND stock >= ?",
                                    (it["qty"], p["id"], it["qty"]),
                                )
                                if cur.rowcount == 0:
                                    await db.execute("ROLLBACK")
                                    return False, f"out of stock: {p['name']}"

                    await db.execute(
                        "UPDATE orders SET status='fulfilled', updated_at=?"
                        " WHERE id=?", (now, order_id),
                    )
                    await db.execute("COMMIT")
                    return True, ""
                except Exception:
                    await db.execute("ROLLBACK")
                    raise

    async def pop_product_values(self, product_id: int, qty: int, order_id: int):
        """Atomically claim `qty` unused values. Returns list or None if short."""
        if qty <= 0:
            raise ValueError("qty must be positive")
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT id, value FROM product_values"
                    " WHERE product_id=? AND is_used=0 ORDER BY id LIMIT ?",
                    (product_id, qty)) as cur:
                    rows = await cur.fetchall()
                if len(rows) < qty:
                    await db.execute("ROLLBACK")
                    return None
                ids = [r["id"] for r in rows]
                await db.execute(
                    f"UPDATE product_values SET is_used=1, used_in_order=?"
                    f" WHERE id IN ({','.join('?' * len(ids))})",
                    (order_id, *ids),
                )
                await db.execute("COMMIT")
                return [r["value"] for r in rows]
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def restore_product_values(self, product_id: int, values: list,
                                     order_id: int):
        """Return previously-popped values to the unused pool (H16 rollback)."""
        if not values:
            return
        async with self._db() as db:
            await db.execute(
                "UPDATE product_values SET is_used=0, used_in_order=NULL"
                f" WHERE product_id=? AND used_in_order=? AND value IN ({','.join('?' * len(values))})",
                (product_id, order_id, *values))
            await db.commit()

    async def clear_order_item_values(self, order_id: int):
        """Clear delivered values (H16 fulfillment rollback)."""
        async with self._db() as db:
            await db.execute(
                "UPDATE order_items SET delivered_value=NULL WHERE order_id=?",
                (order_id,))
            await db.commit()

    # ----------------------------------------------------------- cart ---
    async def cart_add(self, user_id: int, product_id: int, qty: int = 1):
        if qty <= 0:
            await self.cart_set_qty(user_id, product_id, qty)
            return
        async with self._db() as db:
            await db.execute(
                "INSERT INTO cart_items(user_id, product_id, qty) VALUES (?, ?, ?)"
                " ON CONFLICT(user_id, product_id) DO UPDATE SET qty=qty+excluded.qty",
                (user_id, product_id, qty),
            )
            await db.commit()

    async def cart_adjust(self, user_id: int, product_id: int, delta: int,
                         min_qty: int = 0, max_qty: int = 99) -> int:
        """Atomically adjust cart qty by delta. Returns new qty (0 if removed).
        Prevents read-modify-write race on rapid taps."""
        async with self._db() as db:
            await db.execute(
                "INSERT INTO cart_items(user_id, product_id, qty) VALUES (?, ?, ?)"
                " ON CONFLICT(user_id, product_id) DO UPDATE SET"
                " qty = max(?, min(?, qty + ?))",
                (user_id, product_id, max(min_qty, min(delta, max_qty)),
                 min_qty, max_qty, delta),
            )
            async with db.execute(
                "SELECT qty FROM cart_items WHERE user_id=? AND product_id=?",
                (user_id, product_id)) as cur:
                row = await cur.fetchone()
                new_qty = row["qty"] if row else 0
            if new_qty <= 0:
                await db.execute(
                    "DELETE FROM cart_items WHERE user_id=? AND product_id=?",
                    (user_id, product_id))
                new_qty = 0
            await db.commit()
            return new_qty

    async def cart_set_qty(self, user_id: int, product_id: int, qty: int):
        async with self._db() as db:
            if qty <= 0:
                await db.execute(
                    "DELETE FROM cart_items WHERE user_id=? AND product_id=?",
                    (user_id, product_id),
                )
            else:
                await db.execute(
                    "INSERT INTO cart_items(user_id, product_id, qty) VALUES (?, ?, ?)"
                    " ON CONFLICT(user_id, product_id) DO UPDATE SET qty=excluded.qty",
                    (user_id, product_id, qty),
                )
            await db.commit()

    async def cart_remove(self, user_id: int, product_id: int):
        await self.cart_set_qty(user_id, product_id, 0)

    async def cart_clear(self, user_id: int):
        async with self._db() as db:
            await db.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))
            await db.commit()

    async def stock_alert_add(self, user_id: int, product_id: int):
        async with self._db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO stock_alerts(user_id, product_id) VALUES(?, ?)",
                (user_id, product_id))
            await db.commit()

    async def stock_alert_remove(self, user_id: int, product_id: int):
        async with self._db() as db:
            await db.execute(
                "DELETE FROM stock_alerts WHERE user_id=? AND product_id=?",
                (user_id, product_id))
            await db.commit()

    async def stock_alerts_for_product(self, product_id: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT user_id FROM stock_alerts WHERE product_id=?", (product_id,)) as cur:
                return [r["user_id"] async for r in cur]

    async def stock_alerts_clear_product(self, product_id: int):
        async with self._db() as db:
            await db.execute("DELETE FROM stock_alerts WHERE product_id=?", (product_id,))
            await db.commit()

    async def tonconnect_pending_add(self, user_id: int, sender: str,
                                     amount_nano: int, items: list,
                                     promo_code: str = None,
                                     claim_code: str = None):
        import json
        async with self._db() as db:
            await db.execute(
                "INSERT INTO tonconnect_pending(user_id, sender, amount_nano, items_json, promo_code, claim_code)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, sender, amount_nano, json.dumps(items), promo_code, claim_code))
            await db.commit()

    async def tonconnect_pending_list(self):
        import json
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM tonconnect_pending ORDER BY created_at") as cur:
                rows = [dict(r) async for r in cur]
        for r in rows:
            try:
                r["items"] = json.loads(r["items_json"] or "[]")
            except Exception:
                logger.warning("tonconnect pending %s has corrupt items_json",
                               r.get("id"))
                r["items"] = []
                r["items_corrupt"] = True
        return rows

    async def tonconnect_pending_remove(self, pid: int):
        async with self._db() as db:
            await db.execute("DELETE FROM tonconnect_pending WHERE id=?", (pid,))
            await db.commit()

    async def tonconnect_intent_claim_code(self, user_id: int, intent_id: str,
                                             expected_nano: int) -> str:
        """Per-intent TON claim code (audit 16).

        Unlike the per-user tonconnect_claim_code, this binds a specific
        on-chain transaction to a specific payment intent. The code is
        single-use: once a tx matches it, it is marked used and cannot
        match another intent.
        """
        import secrets
        code = "TC-" + secrets.token_hex(8).upper()
        async with self._db() as db:
            await db.execute(
                "INSERT INTO tonconnect_intent_claims(user_id, intent_id, code,"
                " expected_nano, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, intent_id, code, expected_nano, utcnow_iso()),
            )
            await db.commit()
        return code

    async def mark_tonconnect_intent_used(self, code: str, txid: str):
        """Mark a per-intent claim code as used (single-use enforcement)."""
        async with self._db() as db:
            await db.execute(
                "UPDATE tonconnect_intent_claims SET used_at=? WHERE code=?",
                (utcnow_iso(), code),
            )
            await db.commit()

    async def tonconnect_claim_code(self, user_id: int) -> str:
        """Per-user TON Connect claim code (audit C3 memo binding).

        Issued once per user; the Mini App embeds it in the TON transfer
        comment, and the matcher requires an exact memo match. Fail closed.
        """
        import secrets
        async with self._db() as db:
            async with db.execute(
                "SELECT code FROM tonconnect_claims WHERE user_id=?",
                (user_id,)) as cur:
                row = await cur.fetchone()
            if row:
                return row["code"]
            code = secrets.token_urlsafe(12)
            await db.execute(
                "INSERT OR IGNORE INTO tonconnect_claims(user_id, code)"
                " VALUES (?, ?)", (user_id, code))
            await db.commit()
            async with db.execute(
                "SELECT code FROM tonconnect_claims WHERE user_id=?",
                (user_id,)) as cur:
                row = await cur.fetchone()
            return row["code"]

    async def cart_items(self, user_id: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT ci.product_id, ci.qty, p.name, p.price_cents, p.stock,"
                " p.kind, p.is_active, p.photo_file_id"
                " FROM cart_items ci JOIN products p ON p.id = ci.product_id"
                " WHERE ci.user_id=? ORDER BY ci.rowid",
                (user_id,)) as cur:
                return await cur.fetchall()

    async def cart_count(self, user_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(qty),0) s FROM cart_items WHERE user_id=?",
                (user_id,)) as cur:
                return (await cur.fetchone())["s"]

    # ------------------------------------------------------- wishlist ---
    async def wishlist_toggle(self, user_id: int, product_id: int) -> bool:
        """Returns True if now in wishlist."""
        async with self._db() as db:
            async with db.execute(
                "SELECT 1 FROM wishlist WHERE user_id=? AND product_id=?",
                (user_id, product_id)) as cur:
                exists = await cur.fetchone()
            if exists:
                await db.execute(
                    "DELETE FROM wishlist WHERE user_id=? AND product_id=?",
                    (user_id, product_id))
                await db.commit()
                return False
            await db.execute(
                "INSERT OR IGNORE INTO wishlist(user_id, product_id) VALUES (?, ?)",
                (user_id, product_id))
            await db.commit()
            return True

    async def wishlist_has(self, user_id: int, product_id: int) -> bool:
        async with self._db() as db:
            async with db.execute(
                "SELECT 1 FROM wishlist WHERE user_id=? AND product_id=?",
                (user_id, product_id)) as cur:
                return await cur.fetchone() is not None

    async def wishlist_list(self, user_id: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT p.* FROM wishlist w JOIN products p ON p.id=w.product_id"
                " WHERE w.user_id=? AND p.is_active=1 ORDER BY w.rowid DESC",
                (user_id,)) as cur:
                return await cur.fetchall()

    # --------------------------------------------------------- promos ---
    async def get_promo(self, code: str):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM promos WHERE code=? COLLATE NOCASE",
                (code.strip(),)) as cur:
                return await cur.fetchone()

    async def validate_promo(self, code: str, user_id: int, subtotal_cents: int):
        """Returns (ok, message, discount_cents, promo_row)."""
        promo = await self.get_promo(code)
        if not promo or not promo["is_active"]:
            return False, "invalid", 0, None
        expires = promo["expires_at"]
        if expires is not None:
            if not expires.strip():
                return False, "invalid", 0, None
            try:
                exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    return False, "invalid", 0, None
            except ValueError:
                return False, "invalid", 0, None
        if promo["max_uses"] and promo["used_count"] >= promo["max_uses"]:
            return False, "invalid", 0, None
        if promo["min_subtotal_cents"] and subtotal_cents < promo["min_subtotal_cents"]:
            return False, "min", 0, None
        async with self._db() as db:
            async with db.execute(
                "SELECT 1 FROM promo_usages WHERE promo_id=? AND user_id=?",
                (promo["id"], user_id)) as cur:
                if await cur.fetchone():
                    return False, "used", 0, None
        if promo["kind"] == "percent":
            if promo["value"] <= 0 or promo["value"] > 100:
                return False, "invalid", 0, None
            discount = subtotal_cents * promo["value"] // 100
        elif promo["kind"] == "fixed":
            if promo["value"] <= 0:
                return False, "invalid", 0, None
            discount = promo["value"]
        else:
            return False, "invalid", 0, None
        discount = min(discount, subtotal_cents)
        return True, "ok", discount, promo

    async def record_promo_usage(self, promo_id: int, user_id: int) -> bool:
        """Atomically consume one promo use for a user.

        Returns True when the use was recorded. Returns False when the user
        already used it (INSERT OR IGNORE hit) or the promo hit max_uses in
        a race (the usage row is rolled back). Callers should treat False as
        "do not apply the discount".
        """
        async with self._claim_lock:
            async with self._db() as db:
                cur = await db.execute(
                    "INSERT OR IGNORE INTO promo_usages(promo_id, user_id, used_at)"
                    " VALUES (?, ?, ?)",
                    (promo_id, user_id, utcnow_iso()),
                )
                if cur.rowcount == 0:
                    return False  # this user already consumed it
                cur = await db.execute(
                    "UPDATE promos SET used_count = used_count + 1"
                    " WHERE id=? AND (max_uses = 0 OR used_count < max_uses)",
                    (promo_id,),
                )
                if cur.rowcount == 0:
                    # Lost the race for the last slot: roll back our usage row.
                    await db.execute(
                        "DELETE FROM promo_usages WHERE promo_id=? AND user_id=?",
                        (promo_id, user_id),
                    )
                    await db.commit()
                    return False
                await db.commit()
                return True

    async def release_promo_usage(self, promo_id: int, user_id: int,
                                  order_id: int = None) -> bool:
        """Release a promo claim (e.g. order cancelled before payment).

        Audit M2: promo usages were never released on cancellation, so users
        lost single-use promos on unpaid orders. Audit HIGH: do not release
        if another active order for the same user still uses this promo.
        Returns True if a claim was released.
        """
        async with self._claim_lock:
            async with self._db() as db:
                q = ("SELECT 1 FROM orders o JOIN promos p ON p.code = o.promo_code COLLATE NOCASE"
                     " WHERE p.id=? AND o.user_id=? AND o.status != 'cancelled'")
                args = [promo_id, user_id]
                if order_id is not None:
                    q += " AND o.id != ?"
                    args.append(order_id)
                async with db.execute(q, args) as cur:
                    if await cur.fetchone():
                        return False
                cur = await db.execute(
                    "DELETE FROM promo_usages WHERE promo_id=? AND user_id=?",
                    (promo_id, user_id),
                )
                released = cur.rowcount > 0
                if released:
                    await db.execute(
                        "UPDATE promos SET used_count = MAX(0, used_count - 1)"
                        " WHERE id=?",
                        (promo_id,),
                    )
                await db.commit()
                return released

    async def release_order_promo(self, order_id: int) -> bool:
        """Release the promo claimed for an order, if any."""
        order = await self.get_order(order_id)
        if not order or not order["promo_code"]:
            return False
        promo = await self.get_promo(order["promo_code"])
        if not promo:
            return False
        return await self.release_promo_usage(promo["id"], order["user_id"],
                                              order["id"])

    async def list_promos(self):
        async with self._db() as db:
            async with db.execute("SELECT * FROM promos ORDER BY id DESC") as cur:
                return await cur.fetchall()

    async def add_promo(self, *, code, kind, value, max_uses=0, expires_at=None) -> int:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO promos(code, kind, value, max_uses, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (code.strip().upper(), kind, value, max_uses, expires_at),
            )
            await db.commit()
            return cur.lastrowid

    async def set_promo_active(self, promo_id: int, active: bool):
        async with self._db() as db:
            await db.execute("UPDATE promos SET is_active=? WHERE id=?",
                             (1 if active else 0, promo_id))
            await db.commit()

    async def delete_promo(self, promo_id: int):
        async with self._db() as db:
            await db.execute("DELETE FROM promos WHERE id=?", (promo_id,))
            await db.commit()

    # --------------------------------------------------------- orders ---
    async def create_order(self, *, user_id, subtotal_cents, discount_cents,
                           total_cents, payment_method, delivery_kind,
                           address, phone, promo_code=None) -> int:
        now = utcnow_iso()
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO orders(user_id, status, subtotal_cents, discount_cents,"
                " total_cents, payment_method, delivery_kind, address, phone,"
                " promo_code, created_at, updated_at)"
                " VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, subtotal_cents, discount_cents, total_cents,
                 payment_method, delivery_kind, address, phone, promo_code,
                 now, now),
            )
            await db.commit()
            return cur.lastrowid

    async def create_order_atomic(self, *, user_id, subtotal_cents,
                                  discount_cents, total_cents, payment_method,
                                  delivery_kind, address, phone, promo_code=None,
                                  promo_id=None, items=()) -> tuple:
        """Create an order and ALL of its side effects in one transaction.

        The order row, every order_item, each stock decrement and the promo
        claim (when `promo_id` is given) are committed together under
        BEGIN IMMEDIATE, so a crash or a failed stock/promo check can never
        leave an empty order, orphan order items, drifted stock or a consumed
        promo slot.

        `items` is an iterable of (product_id, name, qty, price_cents).

        Returns (order_id, None) on success, or (None, reason) where reason is
        one of 'out_of_stock', 'promo_used', 'promo_exhausted' — nothing is
        persisted in that case.
        """
        items = tuple(items)
        for product_id, name, qty, price_cents in items:
            if qty <= 0 or price_cents < 0:
                return None, "invalid_item"
        now = utcnow_iso()
        async with self._claim_lock:
            async with self._db() as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    cur = await db.execute(
                        "INSERT INTO orders(user_id, status, subtotal_cents,"
                        " discount_cents, total_cents, payment_method, delivery_kind,"
                        " address, phone, promo_code, created_at, updated_at)"
                        " VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (user_id, subtotal_cents, discount_cents, total_cents,
                         payment_method, delivery_kind, address, phone, promo_code,
                         now, now),
                    )
                    order_id = cur.lastrowid

                    for product_id, name, qty, price_cents in items:
                        await db.execute(
                            "INSERT INTO order_items(order_id, product_id, name, qty,"
                            " price_cents) VALUES (?, ?, ?, ?, ?)",
                            (order_id, product_id, name, qty, price_cents),
                        )
                        cur = await db.execute(
                            "UPDATE products SET stock = CASE WHEN stock = -1"
                            " THEN -1 ELSE stock - ? END"
                            " WHERE id=? AND (stock = -1 OR stock >= ?)",
                            (qty, product_id, qty),
                        )
                        if cur.rowcount == 0:
                            await db.execute("ROLLBACK")
                            return None, "out_of_stock"

                    if promo_id is not None:
                        async with db.execute(
                                "SELECT 1 FROM promos WHERE id=?",
                                (promo_id,)) as sel:
                            if await sel.fetchone() is None:
                                await db.execute("ROLLBACK")
                                return None, "promo_used"
                        cur = await db.execute(
                            "INSERT INTO promo_usages(promo_id, user_id,"
                            " used_at) VALUES (?, ?, ?)"
                            " ON CONFLICT(promo_id, user_id) DO NOTHING",
                            (promo_id, user_id, now),
                        )
                        if cur.rowcount == 0:
                            await db.execute("ROLLBACK")
                            return None, "promo_used"
                        cur = await db.execute(
                            "UPDATE promos SET used_count = used_count + 1"
                            " WHERE id=? AND (max_uses = 0 OR used_count < max_uses)",
                            (promo_id,),
                        )
                        if cur.rowcount == 0:
                            await db.execute("ROLLBACK")
                            return None, "promo_exhausted"

                    await db.execute("COMMIT")
                    return order_id, None
                except Exception:
                    await db.execute("ROLLBACK")
                    raise


    async def create_checkout_atomic(self, *, user_id, subtotal_cents,
                                     discount_cents, total_cents, payment_method,
                                     delivery_kind, address, phone, promo_code=None,
                                     promo_id=None, items=()) -> tuple:
        """Create order + items + promo claim + cart clear in one transaction.

        Unlike create_order_atomic, this does NOT decrement stock — stock
        decrements at fulfillment time (handlers/common.py::fulfill_order)
        after payment, per the existing design.

        items: iterable of (product_id, name, qty, price_cents).
        Returns (order_id, None) on success, or (None, reason) on failure
        where reason is 'promo_used' or 'promo_exhausted'. Nothing is
        persisted on failure.
        """
        items = tuple(items)
        for product_id, name, qty, price_cents in items:
            if qty <= 0 or price_cents < 0:
                return None, "invalid_item"
        now = utcnow_iso()
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cur = await db.execute(
                    "INSERT INTO orders(user_id, status, subtotal_cents,"
                    " discount_cents, total_cents, payment_method, delivery_kind,"
                    " address, phone, promo_code, created_at, updated_at)"
                    " VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, subtotal_cents, discount_cents, total_cents,
                     payment_method, delivery_kind, address, phone, promo_code,
                     now, now),
                )
                order_id = cur.lastrowid

                for product_id, name, qty, price_cents in items:
                    await db.execute(
                        "INSERT INTO order_items(order_id, product_id, name, qty,"
                        " price_cents) VALUES (?, ?, ?, ?, ?)",
                        (order_id, product_id, name, qty, price_cents),
                    )

                if promo_id is not None:
                    cur = await db.execute(
                        "INSERT INTO promo_usages(promo_id, user_id,"
                        " used_at) VALUES (?, ?, ?)"
                        " ON CONFLICT(promo_id, user_id) DO NOTHING",
                        (promo_id, user_id, now),
                    )
                    if cur.rowcount == 0:
                        await db.execute("ROLLBACK")
                        return None, "promo_used"
                    cur = await db.execute(
                        "UPDATE promos SET used_count = used_count + 1"
                        " WHERE id=? AND (max_uses = 0 OR used_count < max_uses)",
                        (promo_id,),
                    )
                    if cur.rowcount == 0:
                        await db.execute("ROLLBACK")
                        return None, "promo_exhausted"

                await db.execute("DELETE FROM cart_items WHERE user_id = ?",
                                 (user_id,))

                # Outbox: Payload push event in the same transaction (audit 21).
                import json as _json
                await db.execute(
                    "INSERT INTO outbox_events(event_type, aggregate_id,"
                    " payload, created_at) VALUES (?, ?, ?, ?)",
                    ("order.created", f"order:{order_id}",
                     _json.dumps({"order_id": order_id, "user_id": user_id,
                                  "total_cents": total_cents,
                                  "payment_method": payment_method}),
                     now),
                )

                await db.execute("COMMIT")
                return order_id, None
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def record_observation(self, *, chain: str, chain_id: int = 0,
                               asset: str, token_contract: str = "native",
                               tx_hash: str, log_index: int = 0,
                               block_height: int = None, block_hash: str = None,
                               amount_atomic: str, recipient: str,
                               memo: str = None) -> int | None:
        """Record a raw payment observation (audit 4.2).

        Idempotent: the UNIQUE(chain_id, token_contract, tx_hash, log_index)
        constraint dedups. Returns the observation id, or None if this
        exact transfer was already observed.
        """
        async with self._db() as db:
            try:
                cur = await db.execute(
                    "INSERT INTO payment_observations(chain, chain_id, asset,"
                    " token_contract, tx_hash, log_index, block_height,"
                    " block_hash, amount_atomic, recipient, memo, observed_at,"
                    " state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                    " 'observed')",
                    (chain, chain_id, asset, token_contract.lower(), tx_hash.lower(),
                     log_index, block_height, block_hash, str(amount_atomic),
                     recipient.lower(), memo, utcnow_iso()),
                )
                await db.commit()
                return cur.lastrowid
            except aiosqlite.IntegrityError as e:
                if "UNIQUE" in str(e).upper():
                    return None  # already observed — dedup
                raise

    async def get_reconciliation_cursor(self, chain: str) -> dict | None:
        async with self._db() as db:
            async with db.execute(
                    "SELECT * FROM reconciliation_cursors WHERE chain=?",
                    (chain,)) as cur:
                return await cur.fetchone()

    async def update_reconciliation_cursor(self, chain: str,
                                           block_height: int = None):
        """Advance the cursor after a successful observation sweep."""
        async with self._db() as db:
            await db.execute(
                "INSERT INTO reconciliation_cursors(chain, last_block_height,"
                " last_observed_at, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(chain) DO UPDATE SET"
                " last_block_height=COALESCE(?, last_block_height),"
                " last_observed_at=?, updated_at=?",
                (chain, block_height, utcnow_iso(), utcnow_iso(),
                 block_height, utcnow_iso(), utcnow_iso()),
            )
            await db.commit()

    async def outbox_emit(self, event_type: str, aggregate_id: str,
                          payload: dict) -> int:
        """Write an outbox event (call within a transaction for atomicity)."""
        import json
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO outbox_events(event_type, aggregate_id, payload,"
                " created_at) VALUES (?, ?, ?, ?)",
                (event_type, str(aggregate_id), json.dumps(payload),
                 utcnow_iso()),
            )
            await db.commit()
            return cur.lastrowid

    async def outbox_claim_pending(self, limit: int = 10) -> list:
        """Claim pending outbox events for delivery (single worker)."""
        now = utcnow_iso()
        async with self._db() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT * FROM outbox_events"
                    " WHERE processed_at IS NULL"
                    " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
                    " ORDER BY id LIMIT ?",
                    (now, limit)) as cur:
                    rows = await cur.fetchall()
                ids = [r["id"] for r in rows]
                if ids:
                    await db.execute(
                        f"UPDATE outbox_events SET attempts = attempts + 1,"
                        f" next_attempt_at = datetime('now', '+5 minutes')"
                        f" WHERE id IN ({','.join('?' * len(ids))})",
                        tuple(ids))
                await db.execute("COMMIT")
                return rows
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def outbox_mark_processed(self, event_id: int):
        async with self._db() as db:
            await db.execute(
                "UPDATE outbox_events SET processed_at=? WHERE id=?",
                (utcnow_iso(), event_id))
            await db.commit()

    async def outbox_mark_failed(self, event_id: int, error: str):
        async with self._db() as db:
            await db.execute(
                "UPDATE outbox_events SET last_error=? WHERE id=?",
                (error[:500], event_id))
            await db.commit()

    async def add_order_item(self, order_id: int, product_id: int, name: str,
                             qty: int, price_cents: int):
        async with self._db() as db:
            await db.execute(
                "INSERT INTO order_items(order_id, product_id, name, qty, price_cents)"
                " VALUES (?, ?, ?, ?, ?)",
                (order_id, product_id, name, qty, price_cents),
            )
            await db.commit()

    async def set_order_item_value(self, order_id: int, product_id: int, value: str):
        async with self._db() as db:
            await db.execute(
                "UPDATE order_items SET delivered_value=? WHERE rowid=("
                " SELECT rowid FROM order_items WHERE order_id=? AND product_id=?"
                " ORDER BY rowid LIMIT 1)",
                (value, order_id, product_id),
            )
            await db.commit()

    async def get_order(self, order_id: int):
        async with self._db() as db:
            async with db.execute("SELECT * FROM orders WHERE id=?",
                                  (order_id,)) as cur:
                return await cur.fetchone()

    async def get_order_items(self, order_id: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM order_items WHERE order_id=?", (order_id,)) as cur:
                return await cur.fetchall()

    async def list_user_orders(self, user_id: int, limit: int, offset: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM orders WHERE user_id=? AND status IN ('confirmed', 'preparing', 'processing', 'delivered', 'shipped') ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset)) as cur:
                return await cur.fetchall()

    async def count_user_orders(self, user_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM orders WHERE user_id=? AND status IN ('confirmed', 'preparing', 'processing', 'delivered', 'shipped')",
                (user_id,)) as cur:
                return (await cur.fetchone())["c"]

    async def user_spent(self, user_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(total_cents),0) s FROM orders"
                " WHERE user_id=? AND status IN ('confirmed','preparing','shipped','delivered')",
                (user_id,)) as cur:
                return (await cur.fetchone())["s"]

    async def user_paid_orders_count(self, user_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM orders WHERE user_id=?"
                " AND status IN ('confirmed','preparing','shipped','delivered')",
                (user_id,)) as cur:
                return (await cur.fetchone())["c"]

    async def list_orders_by_status(self, status: str, limit: int, offset: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT o.*, u.name AS user_name, u.tg_id AS user_tg_id FROM orders o"
                " JOIN users u ON u.id=o.user_id"
                " WHERE o.status=? ORDER BY o.id DESC LIMIT ? OFFSET ?",
                (status, limit, offset)) as cur:
                return await cur.fetchall()

    async def count_orders_by_status(self, status: str) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM orders WHERE status=?", (status,)) as cur:
                return (await cur.fetchone())["c"]

    async def orders_by_status_counts(self) -> dict:
        async with self._db() as db:
            async with db.execute(
                "SELECT status, COUNT(*) c FROM orders GROUP BY status") as cur:
                return {r["status"]: r["c"] for r in await cur.fetchall()}

    async def set_order_status(self, order_id: int, status: str,
                               only_if_status: str = None) -> bool:
        """Set order status. With only_if_status, the update is conditional
        (atomic compare-and-set); returns True if a row was updated."""
        async with self._claim_lock:
            async with self._db() as db:
                if only_if_status is None:
                    cur = await db.execute(
                        "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                        (status, utcnow_iso(), order_id),
                    )
                else:
                    cur = await db.execute(
                        "UPDATE orders SET status=?, updated_at=?"
                        " WHERE id=? AND status=?",
                        (status, utcnow_iso(), order_id, only_if_status),
                    )
                # Capture rowcount BEFORE commit: reading cur.rowcount after an
                # await (e.g. commit) can return a stale/wrong value under
                # concurrent load (aiosqlite cursor proxy), which would break
                # the atomic-claim guarantee and allow double fulfillment.
                # The _claim_lock above serializes claims so the read is safe.
                won = cur.rowcount > 0
                await db.commit()
                return won

    async def claim_order_processing(self, order_id: int) -> bool:
        """Atomically claim pending->processing with a claim timestamp."""
        async with self._claim_lock:
            async with self._db() as db:
                cur = await db.execute(
                    "UPDATE orders SET status='processing', claimed_at=?, updated_at=?"
                    " WHERE id=? AND status='pending'",
                    (utcnow_iso(), utcnow_iso(), order_id))
                won = cur.rowcount > 0
                await db.commit()
                return won

    async def order_claim_stale(self, order_id: int, minutes: int = 5) -> bool:
        """True if the processing claim is older than `minutes` (or missing)."""
        async with self._db() as db:
            async with db.execute(
                "SELECT claimed_at FROM orders WHERE id=?", (order_id,)) as cur:
                row = await cur.fetchone()
        if not row or not row["claimed_at"]:
            return True
        try:
            claimed = datetime.fromisoformat(
                str(row["claimed_at"]).replace("Z", "+00:00"))
            if claimed.tzinfo is None:
                claimed = claimed.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - claimed > timedelta(minutes=minutes)

    async def steal_stale_order_claim(self, order_id: int, minutes: int = 5) -> bool:
        """Atomically steal a stale processing claim before fulfilling.

        Only one worker can win the steal; the loser must not fulfill.
        """
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(minutes=minutes)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE orders SET claimed_at=?, updated_at=?"
                " WHERE id=? AND status='processing'"
                " AND (claimed_at IS NULL OR claimed_at < ?)",
                (now, now, order_id, cutoff),
            )
            n = cur.rowcount
            await db.commit()
            return n > 0

    async def revenue(self, days: int = None) -> tuple:
        """Returns (revenue_cents, order_count) for paid orders."""
        q = ("SELECT COALESCE(SUM(total_cents),0) s, COUNT(*) c FROM orders"
             " WHERE status IN ('confirmed','preparing','shipped','delivered')")
        args: tuple = ()
        if days:
            q += " AND created_at >= datetime('now', ?)"
            args = (f"-{days} days",)
        async with self._db() as db:
            async with db.execute(q, args) as cur:
                row = await cur.fetchone()
                return row["s"], row["c"]

    async def avg_check(self) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COALESCE(AVG(total_cents),0) a FROM orders"
                " WHERE status IN ('confirmed','preparing','shipped','delivered')") as cur:
                return int((await cur.fetchone())["a"] or 0)

    # ------------------------------------------------------- payments ---
    async def get_payment_by_external_id(self, provider: str, external_id: str):
        """Return the payment row for (provider, external_id), or None."""
        async with self._db() as db:
            async with db.execute(
                "SELECT provider, external_id, user_id, order_id, amount_cents,"
                " currency, status, created_at FROM payments"
                " WHERE provider = ? AND external_id = ?",
                (provider, external_id),
            ) as cur:
                row = await cur.fetchone()
        return row

    async def record_payment(self, *, provider, external_id, user_id, order_id,
                             amount_cents, currency, status="paid") -> bool:
        """Idempotent insert. Returns True if this is a NEW payment."""
        try:
            async with self._db() as db:
                await db.execute(
                    "INSERT INTO payments(provider, external_id, user_id, order_id,"
                    " amount_cents, currency, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (provider, external_id, user_id, order_id, amount_cents,
                     currency, status, utcnow_iso()),
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            # Distinguish a genuine duplicate from other constraint failures:
            # only report "already exists" if the row is really there.
            existing = await self.get_payment_by_external_id(provider, external_id)
            if existing:
                return False
            raise

    async def get_payments_by_order(self, order_id: int) -> list:
        """All payment rows for an order (order-level idempotency check)."""
        async with self._db() as db:
            async with db.execute(
                "SELECT * FROM payments WHERE order_id=? ORDER BY id",
                (order_id,)) as cur:
                return await cur.fetchall()

    async def update_payment_status(self, provider: str, external_id: str,
                                    status: str) -> bool:
        """Update payment status. Returns True if a row was updated."""
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE payments SET status=? WHERE provider=? AND external_id=?",
                (status, provider, external_id),
            )
            won = cur.rowcount > 0
            await db.commit()
            return won

    # -------------------------------------------------------- reviews ---
    async def has_purchased(self, user_id: int, product_id: int) -> bool:
        async with self._db() as db:
            async with db.execute(
                "SELECT 1 FROM order_items oi JOIN orders o ON o.id=oi.order_id"
                " WHERE o.user_id=? AND oi.product_id=?"
                " AND o.status IN ('confirmed','preparing','shipped','delivered')",
                (user_id, product_id)) as cur:
                return await cur.fetchone() is not None

    async def add_review(self, user_id: int, product_id: int, rating: int, text: str = ""):
        async with self._db() as db:
            await db.execute(
                "INSERT INTO reviews(user_id, product_id, rating, text, created_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id, product_id) DO UPDATE"
                " SET rating=excluded.rating, text=excluded.text,"
                " created_at=excluded.created_at",
                (user_id, product_id, rating, text, utcnow_iso()),
            )
            await db.execute(
                "UPDATE products SET rating_sum=(SELECT COALESCE(SUM(rating),0)"
                " FROM reviews WHERE product_id=?),"
                " rating_count=(SELECT COUNT(*) FROM reviews WHERE product_id=?)"
                " WHERE id=?",
                (product_id, product_id, product_id),
            )
            await db.commit()

    async def list_reviews(self, product_id: int, limit: int = 10):
        async with self._db() as db:
            async with db.execute(
                "SELECT r.*, u.name AS user_name FROM reviews r"
                " JOIN users u ON u.id=r.user_id"
                " WHERE r.product_id=? ORDER BY r.created_at DESC LIMIT ?",
                (product_id, limit)) as cur:
                return await cur.fetchall()

    async def user_purchased_products(self, user_id: int):
        async with self._db() as db:
            async with db.execute(
                "SELECT DISTINCT p.* FROM order_items oi"
                " JOIN orders o ON o.id=oi.order_id"
                " JOIN products p ON p.id=oi.product_id"
                " WHERE o.user_id=?"
                " AND o.status IN ('confirmed','preparing','shipped','delivered')",
                (user_id,)) as cur:
                return await cur.fetchall()

    # ------------------------------------------------------ referrals ---
    async def record_referral_earning(self, referrer_id: int, referee_id: int,
                                      order_id: int, amount_cents: int):
        async with self._db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO referral_earnings"
                "(referrer_id, referee_id, order_id, amount_cents, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (referrer_id, referee_id, order_id, amount_cents, utcnow_iso()),
            )
            await db.commit()

    async def claim_and_record_referral_credit(self, referee_id: int, referrer_id: int,
                                               order_id: int, amount_cents: int) -> bool:
        async with self._claim_lock:
            async with self._db() as db:
                cur = await db.execute(
                    "INSERT OR IGNORE INTO referral_claims(referee_id, claimed_at)"
                    " VALUES (?, ?)",
                    (referee_id, utcnow_iso()),
                )
                won = cur.rowcount > 0
                if won:
                    await db.execute(
                        "INSERT OR IGNORE INTO referral_earnings"
                        "(referrer_id, referee_id, order_id, amount_cents, created_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (referrer_id, referee_id, order_id, amount_cents, utcnow_iso()),
                    )
                await db.commit()
                return won

    async def referral_earnings_total(self, user_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) s FROM referral_earnings"
                " WHERE referrer_id=?",
                (user_id,)) as cur:
                return (await cur.fetchone())["s"]

    async def referral_count(self, user_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM users WHERE referred_by=?",
                (user_id,)) as cur:
                return (await cur.fetchone())["c"]

    async def admin_tg_ids(self):
        async with self._db() as db:
            async with db.execute(
                "SELECT tg_id, role_mask FROM users WHERE role_mask != 0") as cur:
                return [(r["tg_id"], r["role_mask"]) for r in await cur.fetchall()]

    async def values_total_count(self, product_id: int) -> int:
        async with self._db() as db:
            async with db.execute(
                "SELECT COUNT(*) c FROM product_values WHERE product_id=?",
                (product_id,)) as cur:
                return (await cur.fetchone())["c"]

    # ---------------------------------------------------------- audit ---
    async def audit(self, actor_tg_id: int, action: str, details: str = ""):
        async with self._db() as db:
            await db.execute(
                "INSERT INTO audit_log(ts, actor_tg_id, action, details)"
                " VALUES (?, ?, ?, ?)",
                (utcnow_iso(), actor_tg_id, action, details),
            )
            await db.commit()

    # ---------------------------------------------------------- crypto ---
    async def next_xpub_index(self, chain: str) -> int:
        """Atomically fetch-and-increment the per-chain derivation index.

        Index 0 is reserved; counting starts at 1. Single-statement
        UPSERT...RETURNING so concurrent checkouts can't get the same index
        (which would reuse a deposit address across two orders).
        """
        key = f"xpub_index_{chain}"
        async with self._db() as db:
            async with db.execute(
                # M1: validate the stored value is digits-only; a corrupted
                # non-numeric value must fail closed instead of resetting to 1.
                "INSERT INTO kv(key, value) VALUES (?, '1') "
                "ON CONFLICT(key) DO UPDATE "
                "SET value = CAST(kv.value AS INTEGER) + 1 "
                "WHERE kv.value GLOB '[0-9]*' "
                "AND kv.value NOT GLOB '*[^0-9]*' "
                "RETURNING value",
                (key,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise ValueError(f"corrupt xpub index for chain {chain!r}")
            await db.commit()
            return int(row["value"])

    async def crypto_chain_enabled(self, chain: str) -> bool:
        return (await self.kv_get(f"crypto_{chain}_enabled", "1")) == "1"

    async def set_crypto_chain_enabled(self, chain: str, enabled: bool):
        await self.kv_set(f"crypto_{chain}_enabled", "1" if enabled else "0")

    async def create_crypto_deposit(self, *, order_id: int, chain: str,
                                    address: str, derivation_index=None,
                                    memo=None, expected_crypto: str,
                                    expected_usd_cents: int,
                                    expires_at: str,
                                    purpose: str = "order",
                                    topup_user_id: int = None) -> int:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO crypto_deposits(order_id, chain, address,"
                " derivation_index, memo, expected_crypto, expected_usd_cents,"
                " status, created_at, expires_at, purpose, topup_user_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                (order_id, chain, address, derivation_index, memo,
                 expected_crypto, expected_usd_cents, utcnow_iso(), expires_at,
                 purpose, topup_user_id),
            )
            await db.commit()
            return cur.lastrowid

    async def get_crypto_deposit(self, deposit_id: int):
        async with self._db() as db:
            async with db.execute("SELECT * FROM crypto_deposits WHERE id=?",
                                  (deposit_id,)) as cur:
                return await cur.fetchone()

    async def get_deposit_by_order(self, order_id: int, chain: str = None):
        q = "SELECT * FROM crypto_deposits WHERE order_id=? ORDER BY id DESC LIMIT 1"
        args = (order_id,)
        if chain:
            q = ("SELECT * FROM crypto_deposits WHERE order_id=? AND chain=?"
                 " ORDER BY id DESC LIMIT 1")
            args = (order_id, chain)
        async with self._db() as db:
            async with db.execute(q, args) as cur:
                return await cur.fetchone()

    async def pending_crypto_deposits(self):
        async with self._db() as db:
            async with db.execute(
                    "SELECT * FROM crypto_deposits WHERE status IN ('pending','underpaid','late')") as cur:
                return await cur.fetchall()

    async def update_crypto_deposit(self, deposit_id: int, **fields):
        if not fields:
            return
        allowed = {"order_id", "chain", "address", "derivation_index", "memo",
                   "expected_crypto", "expected_usd_cents", "status", "txid",
                   "confirmations", "seen_amount_crypto", "created_at",
                   "expires_at", "purpose", "topup_user_id"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(
                f"invalid crypto_deposits column(s): {sorted(invalid)}")
        cols = ", ".join(f"{k}=?" for k in fields)
        async with self._db() as db:
            await db.execute(f"UPDATE crypto_deposits SET {cols} WHERE id=?",
                             (*fields.values(), deposit_id))
            await db.commit()

    async def claim_crypto_deposit(self, deposit_id: int, txid: str,
                                   seen_amount_crypto: str,
                                   confirmations: int, *,
                                   chain_id: int = 0,
                                   token_contract: str = "native",
                                   log_index: int = 0) -> bool:
        """Atomically claim a deposit for finalization. Returns True only for
        the winner of the race.

        The guard is STATUS-based (pending/underpaid/late) and the UPDATE flips
        status to 'claimed' in the same statement, so a concurrent second claim
        sees status='claimed' and gets rowcount 0. It is deliberately NOT
        txid-IS-NULL: the first underpaid detection already writes a txid, and
        a top-up that brings the total over tolerance must still claim.
        UNIQUE(chain_id, token_contract, txid, log_index) violations also
        return False (two Transfer events in one tx are distinct).
        """
        try:
            async with self._claim_lock:
                async with self._db() as db:
                    cur = await db.execute(
                        "UPDATE crypto_deposits SET txid=?, seen_amount_crypto=?,"
                        " confirmations=?, status='claimed',"
                        " chain_id=?, token_contract=?, log_index=?"
                        " WHERE id=? AND status IN ('pending','underpaid','late')",
                        (txid, seen_amount_crypto, confirmations,
                         chain_id, token_contract.lower(), log_index,
                         deposit_id),
                    )
                    won = cur.rowcount > 0
                    await db.commit()
                    return won
        except aiosqlite.IntegrityError as e:
            # UNIQUE(chain, txid) means another worker won the race; any other
            # constraint failure is real and must surface.
            if "UNIQUE" in str(e).upper():
                return False
            raise

    async def list_crypto_deposits(self, status: str = None, limit: int = 50):
        q = "SELECT * FROM crypto_deposits"
        args = ()
        if status:
            q += " WHERE status=?"
            args = (status,)
        q += " ORDER BY id DESC LIMIT ?"
        async with self._db() as db:
            async with db.execute(q, (*args, limit)) as cur:
                return await cur.fetchall()

    async def create_cryptobot_invoice(self, *, order_id: int = None,
                                       invoice_id: int,
                                       asset: str, amount: str,
                                       purpose: str = "order",
                                       topup_user_id: int = None,
                                       fee_pct: int = None) -> int:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO cryptobot_invoices(order_id, invoice_id, asset,"
                " amount, status, created_at, purpose, topup_user_id, fee_pct)"
                " VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)",
                (order_id, invoice_id, asset, amount, utcnow_iso(),
                 purpose, topup_user_id, fee_pct),
            )
            await db.commit()
            return cur.lastrowid

    async def get_cryptobot_invoice(self, invoice_id: int):
        async with self._db() as db:
            async with db.execute(
                    "SELECT * FROM cryptobot_invoices WHERE invoice_id=?",
                    (invoice_id,)) as cur:
                return await cur.fetchone()

    async def active_cryptobot_invoices(self):
        async with self._db() as db:
            async with db.execute(
                    "SELECT * FROM cryptobot_invoices WHERE status='active'"
            ) as cur:
                return await cur.fetchall()

    async def sweepable_cryptobot_invoices(self):
        """Invoices the recovery sweep should poll: active + paid-but-unfinalized."""
        async with self._db() as db:
            async with db.execute(
                    "SELECT * FROM cryptobot_invoices"
                    " WHERE status IN ('active','paid_unfinalized')"
            ) as cur:
                return await cur.fetchall()

    async def expire_stale_cryptobot_invoices(self, ttl_minutes: int = 45) -> int:
        """Expire invoices past their TTL server-side.

        Audit M5: invoices stayed 'active' forever (expiry lived only on
        CryptoBot's side), so the 60s poller scanned an unbounded list and
        stale invoices could finalize per C7. Returns count expired.
        """
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(minutes=ttl_minutes)).isoformat()
        async with self._db() as db:
            cur = await db.execute(
                "UPDATE cryptobot_invoices SET status='expired'"
                " WHERE status='active' AND created_at < ?",
                (cutoff,))
            n = cur.rowcount
            await db.commit()
            return n

    async def set_cryptobot_status(self, invoice_id: int, status: str):
        async with self._db() as db:
            await db.execute("UPDATE cryptobot_invoices SET status=? WHERE invoice_id=?",
                             (status, invoice_id))
            await db.commit()

    async def finalize_topup_payment(self, *, provider: str, external_id: str,
                                     user_id: int, amount_cents: int,
                                     currency: str) -> tuple:
        """Idempotent balance credit for top-ups. Returns (ok, new_balance_cents, bonus_cents).

        Atomic: the payment row and the balance credit commit in ONE transaction,
        so a crash can never leave payment-paid-but-uncredited. Retries are safe:
        a duplicate call either finds the credit already present or heals a row
        left broken by the old non-atomic code.
        """
        import config as cfg
        bonus = int(amount_cents) * cfg.DEPOSIT_BONUS_PERCENT // 100
        total = int(amount_cents) + bonus
        ext = str(external_id)
        async with self._claim_lock:
            async with self._db() as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    try:
                        await db.execute(
                            "INSERT INTO payments(provider, external_id, user_id, order_id,"
                            " amount_cents, currency, status, created_at)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (provider, ext, user_id, None, amount_cents,
                             currency, "paid", utcnow_iso()))
                        inserted = True
                    except aiosqlite.IntegrityError:
                        inserted = False
                    need_credit = inserted
                    if not need_credit:
                        # Retry path: heal rows broken by the old non-atomic code
                        # (payment recorded, credit never happened).
                        # datetime() normalizes the two created_at formats in play:
                        # utcnow_iso() ("...+00:00") vs datetime('now') (" " sep).
                        async with db.execute(
                            "SELECT id FROM balance_transactions"
                            " WHERE user_id=? AND type='topup' AND amount_cents=?"
                            " AND datetime(created_at) >= datetime((SELECT created_at"
                            " FROM payments WHERE provider=? AND external_id=?))",
                            (user_id, total, provider, ext)) as cur:
                            need_credit = (await cur.fetchone()) is None
                    if need_credit:
                        await db.execute(
                            "UPDATE users SET balance_cents = balance_cents + ? WHERE id=?",
                            (total, user_id))
                        async with db.execute(
                            "SELECT balance_cents FROM users WHERE id=?",
                            (user_id,)) as cur:
                            new_bal = (await cur.fetchone())["balance_cents"]
                        await db.execute(
                            "INSERT INTO balance_transactions"
                            "(user_id, type, amount_cents, balance_after_cents, order_id, created_at)"
                            " VALUES (?, ?, ?, ?, ?, ?)",
                            (user_id, "topup", total, new_bal, None, utcnow_iso()))
                    else:
                        async with db.execute(
                            "SELECT balance_cents FROM users WHERE id=?",
                            (user_id,)) as cur:
                            new_bal = (await cur.fetchone())["balance_cents"]
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        return (True, new_bal, bonus)
