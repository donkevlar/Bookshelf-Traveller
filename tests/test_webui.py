import unittest
import os
import shutil
import tempfile
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripts')))

from webui import SQLiteSettingsDB, app


class TestWebUIDatabaseAndEndpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, 'test_settings.db')
        self.db = SQLiteSettingsDB(self.db_path)
        await self.db.connect()

    async def asyncTearDown(self):
        await self.db.close()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_settings_db_crud(self):
        # Set setting
        ok = await self.db.set_setting("THEME", "dark")
        self.assertTrue(ok)

        # Get setting
        val = await self.db.get_setting("THEME")
        self.assertEqual(val, "dark")

        # Get all settings
        all_s = await self.db.get_all_settings()
        self.assertIn("THEME", all_s)
        self.assertEqual(all_s["THEME"], "dark")

    def test_fastapi_endpoints(self):
        with TestClient(app) as client:
            # Main dashboard HTML
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.headers["content-type"])

            # Status API
            res_status = client.get("/api/status")
            self.assertEqual(res_status.status_code, 200)
            data_status = res_status.json()
            self.assertEqual(data_status["status"], "running")

            # Config API
            res_config = client.get("/api/config")
            self.assertEqual(res_config.status_code, 200)
            data_config = res_config.json()
            self.assertIn("server", data_config)
            self.assertIn("database", data_config)
            self.assertEqual(data_config["database"]["DB_TYPE"], "sqlite")

            # Update Server Config API
            res_post = client.post("/api/config/server", json={
                "bookshelfURL": "http://localhost:13378",
                "bookshelfToken": "test_token_123"
            })
            self.assertEqual(res_post.status_code, 200)
            self.assertTrue(res_post.json()["success"])


if __name__ == "__main__":
    unittest.main()
