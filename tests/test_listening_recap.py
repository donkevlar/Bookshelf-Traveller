import unittest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripts')))

import bookshelfAPI as c
from webui import app, _parse_date_to_ms


class TestListeningRecapLogic(unittest.IsolatedAsyncioTestCase):

    def test_extract_session_timestamp_ms(self):
        # 1. Millisecond integer
        s1 = {"createdAt": 1700000000000}
        self.assertEqual(c._extract_session_timestamp_ms(s1), 1700000000000)

        # 2. Second timestamp (< 10000000000)
        s2 = {"startTime": 1700000000}
        self.assertEqual(c._extract_session_timestamp_ms(s2), 1700000000000)

        # 3. ISO Date String
        s3 = {"updatedAt": "2025-01-15T12:00:00Z"}
        ts3 = c._extract_session_timestamp_ms(s3)
        self.assertIsInstance(ts3, int)
        self.assertGreater(ts3, 0)

    def test_calculate_streak(self):
        # Empty
        self.assertEqual(c._calculate_streak([]), 0)

        # Single date
        d1 = datetime(2025, 1, 1).date()
        self.assertEqual(c._calculate_streak([d1]), 1)

        # Consecutive 3 days
        d2 = datetime(2025, 1, 2).date()
        d3 = datetime(2025, 1, 3).date()
        self.assertEqual(c._calculate_streak([d1, d2, d3]), 3)

        # Broken streak (1, 2, 5, 6) -> max streak = 2
        d5 = datetime(2025, 1, 5).date()
        d6 = datetime(2025, 1, 6).date()
        self.assertEqual(c._calculate_streak([d1, d2, d5, d6]), 2)

    def test_parse_date_to_ms(self):
        # YYYY-MM-DD start
        ms_start = _parse_date_to_ms("2025-01-01", is_end=False)
        self.assertIsNotNone(ms_start)

        # YYYY-MM-DD end
        ms_end = _parse_date_to_ms("2025-01-01", is_end=True)
        self.assertIsNotNone(ms_end)
        self.assertGreater(ms_end, ms_start)

        # None / invalid
        self.assertIsNone(_parse_date_to_ms(None))
        self.assertIsNone(_parse_date_to_ms("invalid-date-format"))

    @patch("bookshelfAPI.bookshelf_conn")
    async def test_get_custom_listening_stats_aggregation(self, mock_conn):
        # Mock sessions data from Audiobookshelf
        base_time = int(datetime(2025, 1, 10, 10, 0, 0).timestamp() * 1000)
        day2_time = int(datetime(2025, 1, 11, 10, 0, 0).timestamp() * 1000)

        mock_sessions_response = MagicMock()
        mock_sessions_response.status_code = 200
        mock_sessions_response.json.return_value = {
            "total": 3,
            "numPages": 1,
            "page": 0,
            "sessions": [
                {
                    "id": "session-1",
                    "libraryItemId": "book-1",
                    "displayTitle": "The Way of Kings",
                    "displayAuthor": "Brandon Sanderson",
                    "timeListening": 3600.0,
                    "createdAt": base_time,
                    "mediaMetadata": {
                        "genres": ["Fantasy", "Epic"],
                        "authors": ["Brandon Sanderson"]
                    }
                },
                {
                    "id": "session-2",
                    "libraryItemId": "book-1",
                    "displayTitle": "The Way of Kings",
                    "displayAuthor": "Brandon Sanderson",
                    "timeListening": 1800.0,
                    "createdAt": base_time + 5000,
                    "mediaMetadata": {
                        "genres": ["Fantasy"],
                        "authors": ["Brandon Sanderson"]
                    }
                },
                {
                    "id": "session-3",
                    "libraryItemId": "book-2",
                    "displayTitle": "Project Hail Mary",
                    "displayAuthor": "Andy Weir",
                    "timeListening": 7200.0,
                    "createdAt": day2_time,
                    "mediaMetadata": {
                        "genres": ["Sci-Fi"],
                        "authors": ["Andy Weir"]
                    }
                }
            ]
        }
        mock_conn.return_value = mock_sessions_response

        # Request stats between Jan 9 and Jan 12, 2025
        start_ms = int(datetime(2025, 1, 9).timestamp() * 1000)
        end_ms = int(datetime(2025, 1, 12).timestamp() * 1000)

        stats = await c.get_custom_listening_stats(start_time_ms=start_ms, end_time_ms=end_ms)

        # Assert total listening time (3600 + 1800 + 7200 = 12600 seconds = 3.5 hours)
        self.assertEqual(stats["totalListeningTime"], 12600)
        self.assertEqual(stats["totalSessions"], 3)
        self.assertEqual(stats["uniqueBooksCount"], 2)

        # Top book should be Project Hail Mary (7200s > 5400s)
        self.assertEqual(len(stats["topBooks"]), 2)
        self.assertEqual(stats["topBooks"][0]["id"], "book-2")
        self.assertEqual(stats["topBooks"][0]["duration"], 7200.0)

        # Top authors
        self.assertEqual(len(stats["topAuthors"]), 2)
        top_author_names = [a["name"] for a in stats["topAuthors"]]
        self.assertIn("Andy Weir", top_author_names)
        self.assertIn("Brandon Sanderson", top_author_names)

        # Streak & Days
        self.assertEqual(stats["daysListened"], 2)
        self.assertEqual(stats["streak"], 2)

        # Top day should be 2025-01-11 with 7200 seconds
        self.assertEqual(stats["topDay"]["date"], "2025-01-11")
        self.assertEqual(stats["topDay"]["duration"], 7200)

    @patch("bookshelfAPI.bookshelf_conn")
    async def test_get_custom_listening_stats_empty(self, mock_conn):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"total": 0, "numPages": 0, "sessions": []}
        mock_conn.return_value = mock_resp

        stats = await c.get_custom_listening_stats(start_time_ms=10000, end_time_ms=20000)
        self.assertEqual(stats["totalListeningTime"], 0)
        self.assertEqual(stats["totalSessions"], 0)
        self.assertEqual(stats["topBooks"], [])
        self.assertEqual(stats["topAuthors"], [])
        self.assertEqual(stats["streak"], 0)


class TestWebUIRecapEndpoints(unittest.TestCase):

    def test_dashboard_contains_recap_tab_and_canvas(self):
        with TestClient(app) as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            html = response.text
            self.assertIn("Dynamic Listening Recap", html)
            self.assertIn('id="recap-canvas"', html)
            self.assertIn('id="recap-start"', html)
            self.assertIn('id="recap-end"', html)
            self.assertIn('id="recap-format"', html)
            self.assertIn("downloadRecapPNG", html)

    @patch("bookshelfAPI.get_custom_listening_stats", new_callable=AsyncMock)
    def test_api_recap_endpoint(self, mock_get_stats):
        mock_get_stats.return_value = {
            "totalListeningTime": 3600,
            "timeFormatted": {"days": 0, "hours": 1, "minutes": 0, "seconds": 0, "display": "1h 0m"},
            "totalSessions": 1,
            "uniqueBooksCount": 1,
            "topBooks": [{"id": "b1", "title": "Test Book", "duration": 3600}],
            "topAuthors": [{"name": "Author", "duration": 3600}],
            "topGenres": [{"name": "Genre", "duration": 3600}],
            "streak": 1,
            "daysListened": 1,
            "topDay": {"date": "2025-01-01", "duration": 3600}
        }

        with TestClient(app) as client:
            res = client.get("/api/recap?start_date=2025-01-01&end_date=2025-01-31")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["totalListeningTime"], 3600)
            self.assertEqual(data["timeFormatted"]["display"], "1h 0m")
            self.assertEqual(data["streak"], 1)

    @patch("httpx.AsyncClient.get")
    def test_cover_proxy_endpoint(self, mock_http_get):
        os.environ["bookshelfURL"] = "http://localhost:13378"
        os.environ["bookshelfToken"] = "mock_token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/jpeg"}
        mock_resp.content = b"fake-jpeg-binary-data"

        mock_http_get.return_value = mock_resp

        with TestClient(app) as client:
            res = client.get("/api/cover-proxy?item_id=test-item-123")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.headers["content-type"], "image/jpeg")
            self.assertEqual(res.content, b"fake-jpeg-binary-data")


if __name__ == "__main__":
    unittest.main()
