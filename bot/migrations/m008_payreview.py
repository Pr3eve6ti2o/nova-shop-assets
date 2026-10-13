"""Payment anomalies, resolutions, refunds ledger (port plan Part 6).

- payment_anomalies: the payreview quarantine (JumpCodeFrog pattern).
  Money that arrived but could not be attached to an order lands here
  with a SHA-256 fingerprint; the UNIQUE fingerprint makes recording
  idempotent, so sweeps can report the same problem forever and it is
  stored exactly once.
- payment_resolutions: append-only admin decisions on anomalies.
- refunds: one ledger for every refund, whatever path created it.
  The fail-closed rule (sum of refunds for an order may never exceed
  the order total) is enforced in db.record_refund.
"""

VERSION = 8
DESCRIPTION = "Add payment_anomalies, payment_resolutions, refunds"


async def up(db):
    async with db._db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS payment_anomalies("
            " id INTEGER PRIMARY KEY,"
            " provider TEXT NOT NULL,"
            " fingerprint TEXT NOT NULL UNIQUE,"
            " external_id TEXT,"
            " user_id INTEGER,"
            " amount_text TEXT,"
            " amount_cents INTEGER,"
            " currency TEXT,"
            " reason TEXT NOT NULL,"
            " raw TEXT,"
            " status TEXT NOT NULL DEFAULT 'open'"
            "   CHECK (status IN ('open','settled','dismissed')),"
            " created_at TEXT NOT NULL,"
            " resolved_at TEXT)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_anomalies_status"
            " ON payment_anomalies(status, created_at)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS payment_resolutions("
            " id INTEGER PRIMARY KEY,"
            " anomaly_id INTEGER NOT NULL"
            "   REFERENCES payment_anomalies(id),"
            " action TEXT NOT NULL,"
            " admin_id INTEGER,"
            " note TEXT,"
            " amount_cents INTEGER,"
            " created_at TEXT NOT NULL)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS refunds("
            " id INTEGER PRIMARY KEY,"
            " order_id INTEGER NOT NULL REFERENCES orders(id),"
            " user_id INTEGER NOT NULL,"
            " amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),"
            " method TEXT NOT NULL,"
            " admin_id INTEGER,"
            " note TEXT,"
            " created_at TEXT NOT NULL)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refunds_order"
            " ON refunds(order_id)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS payment_resolutions")
        await conn.execute("DROP TABLE IF EXISTS payment_anomalies")
        await conn.execute("DROP TABLE IF EXISTS refunds")
        await conn.commit()
