"""Support thread tests (port plan Part 3): ticket threads, reopen rules,
owner-only close, inbox previews.

Run: BOT_TOKEN=<well-formed dummy> PYTHONPATH=. python tests/test_support_threads.py
"""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault(
    "BOT_TOKEN", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

from database import Database  # noqa: E402


async def _fixture():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    await db.create_tables()
    u = await db.create_user(777, "Thread Tester")
    return db, u["id"]


class SupportThreads(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_thread_lifecycle(self):
        async def go():
            db, uid = await _fixture()
            tid = await db.ticket_create(uid, "My key doesn't work, help!")
            t = await db.ticket_get(tid)
            self.assertEqual(t["status"], "open")
            self.assertEqual(t["subject"], "My key doesn't work, help!")
            await db.ticket_add_message(tid, "admin", "Sorry — new key sent.")
            await db.ticket_add_message(tid, "user", "Works now, thanks!")
            msgs = await db.ticket_messages(tid)
            self.assertEqual([m["sender"] for m in msgs],
                             ["user", "admin", "user"])
            self.assertEqual(msgs[0]["body"], "My key doesn't work, help!")
        self.run_async(go())

    def test_close_and_reopen_rules(self):
        async def go():
            db, uid = await _fixture()
            tid = await db.ticket_create(uid, "Question")
            # Another user cannot close it
            self.assertFalse(await db.ticket_close(tid, user_id=uid + 99))
            self.assertTrue(await db.ticket_close(tid, user_id=uid))
            # Admin cannot post to a closed ticket
            with self.assertRaises(ValueError):
                await db.ticket_add_message(tid, "admin", "late reply")
            # A customer follow-up reopens the conversation
            await db.ticket_add_message(tid, "user", "One more thing…")
            self.assertEqual((await db.ticket_get(tid))["status"], "open")
            # Admin close (no owner restriction)
            self.assertTrue(await db.ticket_close(tid))
            self.assertFalse(await db.ticket_close(tid))  # already closed
        self.run_async(go())

    def test_inbox_preview_and_order(self):
        async def go():
            db, uid = await _fixture()
            t1 = await db.ticket_create(uid, "First ticket")
            t2 = await db.ticket_create(uid, "Second ticket", order_id=42)
            await db.ticket_add_message(t1, "admin", "Answer to first")
            rows = await db.tickets_inbox()
            self.assertEqual(len(rows), 2)
            # Most recent activity first: t1 was just answered
            self.assertEqual(rows[0]["id"], t1)
            self.assertEqual(rows[0]["last_sender"], "admin")
            self.assertEqual(rows[0]["last_body"], "Answer to first")
            self.assertEqual(rows[1]["order_id"], 42)
            # Closed tickets leave the inbox
            await db.ticket_close(t1)
            rows = await db.tickets_inbox()
            self.assertEqual([r["id"] for r in rows], [t2])
        self.run_async(go())

    def test_thread_cap_keeps_most_recent(self):
        async def go():
            db, uid = await _fixture()
            tid = await db.ticket_create(uid, "m0")
            for i in range(1, 8):
                await db.ticket_add_message(tid, "user", f"m{i}")
            msgs = await db.ticket_messages(tid, limit=3)
            self.assertEqual([m["body"] for m in msgs], ["m5", "m6", "m7"])
        self.run_async(go())


if __name__ == "__main__":
    unittest.main()
