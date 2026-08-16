import unittest
import sqlite3
import os
import shutil
import tempfile
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripts')))

import multi_user


class TestMultiUserDatabase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, 'test_user_info.db')

        # Override multi_user DB connection
        self.orig_conn = multi_user.conn
        self.orig_cursor = multi_user.cursor

        multi_user.conn = sqlite3.connect(self.db_path)
        multi_user.cursor = multi_user.conn.cursor()
        multi_user.table_create()

    def tearDown(self):
        multi_user.conn.close()
        multi_user.conn = self.orig_conn
        multi_user.cursor = self.orig_cursor
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_user_insertion_and_search(self):
        success = multi_user.insert_data(user="alice", token="tok_123", discord_id=1001)
        self.assertTrue(success)

        # Duplicate insert should return False
        dup_success = multi_user.insert_data(user="alice", token="tok_123", discord_id=1001)
        self.assertFalse(dup_success)

        # Search by discord ID
        results = multi_user.search_user_db(discord_id=1001)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("tok_123", "alice"))

        # Search by token
        user_res = multi_user.search_user_db(token="tok_123")
        self.assertEqual(user_res, ("alice",))

        # Search by username
        tok_res = multi_user.search_user_db(user="alice")
        self.assertEqual(tok_res, ("tok_123",))

    def test_user_deletion(self):
        multi_user.insert_data(user="bob", token="tok_456", discord_id=1002)
        del_success = multi_user.remove_user_db(user="bob")
        self.assertTrue(del_success)

        # Search after deletion
        results = multi_user.search_user_db(discord_id=1002)
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
