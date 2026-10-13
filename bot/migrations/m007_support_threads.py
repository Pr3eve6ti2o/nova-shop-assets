"""Threaded support messages (port plan Part 3).

Until now a support ticket stored only a subject line; the customer's
message and the admin's reply travelled as one-off notifications and
were never saved, so neither side could see the conversation.

- support_messages: the thread — one row per message, sender side kept.
- support_tickets gains order_id (a thread may attach to an order,
  DoktorShift-style) and updated_at (last activity, for inbox sorting).

support_tickets itself is created lazily by handlers/support.py, so
this migration creates it if missing before altering it.
"""

VERSION = 7
DESCRIPTION = "Add support_messages thread + ticket order_id/updated_at"

_TICKETS_DDL = (
    "CREATE TABLE IF NOT EXISTS support_tickets("
    " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
    " subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',"
    " created_at TEXT NOT NULL)")


async def up(db):
    async with db._db() as conn:
        await conn.execute(_TICKETS_DDL)
        for col, ddl in (
            ("order_id", "ALTER TABLE support_tickets"
                         " ADD COLUMN order_id INTEGER"),
            ("updated_at", "ALTER TABLE support_tickets"
                           " ADD COLUMN updated_at TEXT"),
        ):
            try:
                await conn.execute(ddl)
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        await conn.execute(
            "UPDATE support_tickets SET updated_at = created_at"
            " WHERE updated_at IS NULL")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS support_messages("
            " id INTEGER PRIMARY KEY,"
            " ticket_id INTEGER NOT NULL REFERENCES support_tickets(id),"
            " sender TEXT NOT NULL CHECK (sender IN ('user','admin')),"
            " body TEXT NOT NULL,"
            " created_at TEXT NOT NULL)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_support_messages_ticket"
            " ON support_messages(ticket_id, id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_support_tickets_inbox"
            " ON support_tickets(status, updated_at)")
        await conn.commit()


async def down(db):
    async with db._db() as conn:
        await conn.execute("DROP TABLE IF EXISTS support_messages")
        await conn.commit()
