import unittest
import asyncio
import os
import shutil
import tempfile
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripts')))

from subscription_task import SQLiteTaskDatabase


class TestSubscriptionTaskDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, 'test_tasks.db')
        self.db = SQLiteTaskDatabase(self.db_path)
        await self.db.connect()
        await self.db.create_tasks_table()
        await self.db.create_version_table()
        await self.db.create_task_locks_table()
        await self.db.create_message_tracking_table()

    async def asyncTearDown(self):
        await self.db.close()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_task_operations(self):
        # Insert task
        success = await self.db.insert_data(
            discord_id=123456789,
            channel_id=987654321,
            task="new-book-check",
            server_name="Test Server",
            token="test-token"
        )
        self.assertTrue(success)

        # Search by channel ID
        rows = await self.db.search_task_db(channel_id=987654321)
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 123456789)
        self.assertEqual(rows[0][1], "new-book-check")

        # Delete task
        deleted = await self.db.remove_task_db(task="new-book-check", discord_id=123456789)
        self.assertTrue(deleted)

    async def test_distributed_locks(self):
        # Acquire lock
        lock1 = await self.db.acquire_lock(task_name="sync_task", lock_duration_seconds=60)
        self.assertTrue(lock1)

        # Confirm ownership
        owner = await self.db.check_lock_owner(task_name="sync_task")
        self.assertTrue(owner)

        # Release lock
        await self.db.release_lock(task_name="sync_task")
        owner_after = await self.db.check_lock_owner(task_name="sync_task")
        self.assertFalse(owner_after)

    async def test_message_tracking(self):
        # Initial check
        sent = await self.db.has_message_been_sent(channel_id=111, book_id="book_abc", message_type="new_book")
        self.assertFalse(sent)

        # Mark sent
        await self.db.mark_message_as_sent(channel_id=111, book_id="book_abc", message_type="new_book")

        # Check after marking
        sent_after = await self.db.has_message_been_sent(channel_id=111, book_id="book_abc", message_type="new_book")
        self.assertTrue(sent_after)


if __name__ == "__main__":
    unittest.main()
