"""Order lifecycle: complete the status vocabulary (post-purchase plan,
2026-10-14).

'preparing' (and 'completed') entered the status vocabulary in
texts.STATUS_LABEL, the customer roadmap and the admin transition map,
but the base schema's orders CHECK constraint was never updated — on
any database created from that schema, moving an order into
'preparing' fails with sqlite3.IntegrityError inside
db.set_order_status. Since 'preparing' is the only forward step the
admin console offers from 'confirmed', such orders stick at
'confirmed' forever (reproduced with a full stack trace on a fresh
database, 2026-10-14).

Historical databases come in three shapes, all handled:
- the status CHECK already lists 'preparing'  -> nothing to do;
- a status CHECK exists without it (column- or table-level)
  -> rebuild the table with the full vocabulary, preserving every
     row, column and index (the column list is read from the live
     schema, so columns added by earlier migrations survive);
- no status CHECK at all (the oldest tables, e.g. the long-lived
  test database) -> nothing enforces the vocabulary at the DB
  level; nothing to do.

SQLite cannot alter a CHECK constraint, hence the rebuild where one
is needed.
"""

import re

VERSION = 15
DESCRIPTION = "Orders: full status vocabulary incl. 'preparing' (rebuild if CHECK lags)"

_CHECK_RE = re.compile(r"CHECK\s*\(\s*status\s+IN\s*\([^)]*\)\s*\)")
_FULL_CHECK = (
    "CHECK (status IN ('pending','awaiting_payment','confirmed',"
    "'processing','preparing','shipped','delivered','cancelled',"
    "'refunded','completed'))")


async def up(db):
    async with db._db() as conn:
        async with conn.execute(
                "SELECT sql FROM sqlite_master"
                " WHERE type='table' AND name='orders'") as cur:
            row = await cur.fetchone()
        if not row or not row["sql"]:
            return
        ddl = row["sql"]
        m = _CHECK_RE.search(ddl)
        if m is None:
            return  # oldest shape: no status CHECK to widen
        if "'preparing'" in m.group(0):
            return  # vocabulary already complete

        # Dependent indexes/triggers are dropped with the old table;
        # capture their SQL to replay after the rename.
        async with conn.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name='orders'"
                " AND type IN ('index','trigger') AND sql IS NOT NULL"
                ) as cur:
            dependents = [r["sql"] for r in await cur.fetchall()]

        async with conn.execute("PRAGMA table_info(orders)") as cur:
            cols = [r["name"] for r in await cur.fetchall()]
        col_list = ", ".join(f'"{c}"' for c in cols)

        new_ddl = ddl[:m.start()] + _FULL_CHECK + ddl[m.end():]
        new_ddl = re.sub(r"CREATE TABLE (IF NOT EXISTS )?[\"']?orders[\"']?",
                         "CREATE TABLE orders_new", new_ddl, count=1)

        # The rebuild renames a table other tables reference; FK
        # enforcement must be off on this connection or DROP TABLE
        # would cascade into order_items/payments.
        await conn.execute("PRAGMA foreign_keys=OFF")
        await conn.execute(new_ddl)
        await conn.execute(
            f"INSERT INTO orders_new ({col_list})"
            f" SELECT {col_list} FROM orders")
        await conn.execute("DROP TABLE orders")
        await conn.execute("ALTER TABLE orders_new RENAME TO orders")
        for sql in dependents:
            await conn.execute(sql)
        await conn.commit()

        async with conn.execute("PRAGMA foreign_key_check") as cur:
            violations = await cur.fetchall()
        if violations:
            raise RuntimeError(
                f"m015: foreign_key_check failed after rebuild:"
                f" {len(violations)} violation(s)")
