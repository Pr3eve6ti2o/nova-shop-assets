"""Order lifecycle: complete the status vocabulary (post-purchase plan,
2026-10-14).

'preparing' (and 'completed') entered the status vocabulary in
texts.STATUS_LABEL, the customer roadmap and the admin transition map,
but the orders table CHECK constraint from the original schema was
never updated. Any attempt to move an order into 'preparing' failed
with sqlite3.IntegrityError inside db.set_order_status — and since
'preparing' is the only forward step the admin console offers from
'confirmed', orders were stuck at 'confirmed' forever (found live:
order #19 on the test bot, 2026-10-14).

SQLite cannot alter a CHECK constraint, so this migration rebuilds the
orders table with the full vocabulary: every row, column and index is
preserved (the column list is read from the live schema, so columns
added by earlier migrations survive). It inspects the live DDL first
and skips when the vocabulary is already complete (fresh databases
created with the fixed base schema take that path).
"""

import re

VERSION = 15
DESCRIPTION = "Orders: full status vocabulary incl. 'preparing' (table rebuild)"

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
        if "'preparing'" in ddl:
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

        new_ddl, n = re.subn(r"CHECK \(status IN \([^)]*\)\)",
                             _FULL_CHECK, ddl, count=1)
        if n != 1:
            raise RuntimeError(
                "m015: could not locate the orders status CHECK to widen")
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
