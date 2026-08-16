import unittest
import asyncio
import os
import shutil
import tempfile
import sys

# Ensure Scripts directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripts')))

from wishlist import SQLiteDatabase, create_database


class TestWishlistDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, 'test_wishlist.db')
        self.db = SQLiteDatabase(self.db_path)
        await self.db.connect()
        await self.db.create_wishlist_table()

    async def asyncTearDown(self):
        await self.db.close()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_create_table_and_insert(self):
        result = await self.db.insert_wishlist_data(
            title="The Hobbit",
            author="J.R.R. Tolkien",
            description="Fantasy audiobook",
            cover="http://example.com/cover.jpg",
            provider="audible",
            provider_id="12345",
            discord_id=999888777,
            data="{}"
        )
        self.assertTrue(result)

        # Query inserted book
        rows = await self.db.search_wishlist_db(discord_id=999888777)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "The Hobbit")
        self.assertEqual(rows[0][1], "J.R.R. Tolkien")

    async def test_update_downloaded(self):
        await self.db.insert_wishlist_data(
            title="Dune",
            author="Frank Herbert",
            description="Sci-Fi audiobook",
            cover="http://example.com/dune.jpg",
            provider="audible",
            provider_id="54321",
            discord_id=111222333,
            data="{}"
        )

        # Initial check
        rows_before = await self.db.search_wishlist_db(discord_id=111222333)
        self.assertEqual(len(rows_before), 1)

        # Mark as downloaded
        await self.db.update_wishlist_db(discord_id=111222333, downloaded=1, title="Dune")

        # Check pending wishlist (should be empty now)
        rows_after = await self.db.search_wishlist_db(discord_id=111222333)
        self.assertEqual(len(rows_after), 0)

        # Search all wishlists (should include downloaded item)
        all_rows = await self.db.search_all_wishlists()
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(all_rows[0][8], 1)


if __name__ == "__main__":
    unittest.main()
