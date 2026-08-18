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
        # 1. startedAt in milliseconds (standard Audiobookshelf session timestamp)
        s1 = {"startedAt": 1700000000000}
        self.assertEqual(c._extract_session_timestamp_ms(s1), 1700000000000)

        # 2. startedAt in seconds (< 10000000000)
        s2 = {"startedAt": 1700000000}
        self.assertEqual(c._extract_session_timestamp_ms(s2), 1700000000000)

        # 3. createdAt in milliseconds
        s3 = {"createdAt": 1700000000000}
        self.assertEqual(c._extract_session_timestamp_ms(s3), 1700000000000)

        # 4. Critical: startTime is audio track offset (e.g. 0.0 or 150.5), MUST NOT be used as timestamp
        s4 = {"startTime": 0.0, "startedAt": 1716500000000}
        self.assertEqual(c._extract_session_timestamp_ms(s4), 1716500000000)

        # 5. ISO Date String
        s5 = {"updatedAt": "2025-01-15T12:00:00Z"}
        ts5 = c._extract_session_timestamp_ms(s5)
        self.assertIsInstance(ts5, int)
        self.assertGreater(ts5, 0)

        # 6. YYYY-MM-DD Date String
        s6 = {"date": "2024-05-20"}
        ts6 = c._extract_session_timestamp_ms(s6)
        self.assertIsInstance(ts6, int)
        self.assertGreater(ts6, 0)

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
                    "startedAt": base_time,
                    "startTime": 0.0,
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
                    "startedAt": base_time + 5000,
                    "startTime": 3600.0,
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
                    "startedAt": day2_time,
                    "startTime": 0.0,
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
    async def test_get_custom_listening_stats_fallback_to_days_map(self, mock_conn):
        # Simulate /listening-sessions returning 404, but /listening-stats returning days map
        def side_effect(endpoint, *args, **kwargs):
            resp = MagicMock()
            if "listening-sessions" in endpoint:
                resp.status_code = 404
            elif "listening-stats" in endpoint:
                resp.status_code = 200
                resp.json.return_value = {
                    "totalTime": 14400,
                    "days": {
                        "2024-05-10": 3600,
                        "2024-05-11": 7200,
                        "2024-05-12": 3600,
                        "2023-01-01": 5000  # Outside range
                    },
                    "items": {
                        "book-xyz": {
                            "timeListening": 14400,
                            "metadata": {
                                "title": "Dune",
                                "author": "Frank Herbert",
                                "genres": ["Sci-Fi"]
                            }
                        }
                    },
                    "recentSessions": []
                }
            elif endpoint == "/me":
                resp.status_code = 200
                resp.json.return_value = {"id": "user-123", "username": "testuser"}
            else:
                resp.status_code = 404
            return resp

        mock_conn.side_effect = side_effect

        start_ms = int(datetime(2024, 5, 1).timestamp() * 1000)
        end_ms = int(datetime(2024, 5, 31).timestamp() * 1000)

        stats = await c.get_custom_listening_stats(start_time_ms=start_ms, end_time_ms=end_ms)
        self.assertEqual(stats["totalListeningTime"], 14400)
        self.assertEqual(stats["daysListened"], 3)
        self.assertEqual(stats["streak"], 3)
        self.assertEqual(len(stats["topBooks"]), 1)
        self.assertEqual(stats["topBooks"][0]["title"], "Dune")
        self.assertEqual(stats["topAuthors"][0]["name"], "Frank Herbert")

    @patch("bookshelfAPI.bookshelf_conn")
    async def test_get_custom_listening_stats_with_dict_metadata(self, mock_conn):
        # Audiobookshelf often provides authors and genres as lists of objects/dicts
        base_time = int(datetime(2025, 2, 1, 12, 0, 0).timestamp() * 1000)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "total": 1,
            "numPages": 1,
            "page": 0,
            "sessions": [
                {
                    "id": "session-nested-1",
                    "libraryItemId": {"id": "book-dict-1"},
                    "displayTitle": "Words of Radiance",
                    "timeListening": 5400.0,
                    "startedAt": base_time,
                    "mediaMetadata": {
                        "title": {"title": "Words of Radiance"},
                        "authors": [
                            {"id": "auth-1", "name": "Brandon Sanderson"},
                            {"name": "Michael Whelan"}
                        ],
                        "genres": [
                            {"id": "genre-1", "name": "Fantasy"},
                            {"name": "High Fantasy"}
                        ]
                    }
                }
            ]
        }
        mock_conn.return_value = mock_resp

        start_ms = int(datetime(2025, 2, 1).timestamp() * 1000)
        end_ms = int(datetime(2025, 2, 28).timestamp() * 1000)

        stats = await c.get_custom_listening_stats(start_time_ms=start_ms, end_time_ms=end_ms)
        self.assertEqual(stats["totalListeningTime"], 5400)
        self.assertEqual(stats["uniqueBooksCount"], 1)
        self.assertEqual(stats["topBooks"][0]["title"], "Words of Radiance")
        author_names = [a["name"] for a in stats["topAuthors"]]
        self.assertIn("Brandon Sanderson", author_names)
        self.assertIn("Michael Whelan", author_names)
        genre_names = [g["name"] for g in stats["topGenres"]]
        self.assertIn("Fantasy", genre_names)
        self.assertIn("High Fantasy", genre_names)

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
            self.assertIn('id="btn-send-owner"', html)
            self.assertIn('id="btn-send-user"', html)
            self.assertIn('id="btn-send-channel"', html)
            self.assertIn('id="send-user-modal"', html)
            self.assertIn('id="send-channel-modal"', html)
            self.assertIn("sendRecapToOwner", html)
            self.assertIn("openSendToUserModal", html)
            self.assertIn("openSendToChannelModal", html)

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

    @patch("interactions.api.http.http_client.HTTPClient.get_current_bot_information", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.login", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.close", new_callable=AsyncMock)
    def test_get_discord_recipients_endpoint(self, mock_close, mock_login, mock_bot_info):
        os.environ["DISCORD_TOKEN"] = "test_discord_token"
        mock_bot_info.return_value = {
            "id": "1111111111",
            "owner": {
                "id": "999888777",
                "username": "BotOwnerGuy",
                "global_name": "Bot Owner"
            }
        }

        with TestClient(app) as client:
            res = client.get("/api/discord/recipients")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["bot_configured"])
            self.assertIsNotNone(data["owner"])
            self.assertEqual(data["owner"]["id"], "999888777")
            self.assertEqual(data["owner"]["username"], "BotOwnerGuy")
            self.assertIsInstance(data["enrolled_users"], list)
            self.assertIsInstance(data["channels"], list)

    @patch("interactions.api.http.http_client.HTTPClient.create_message", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.create_dm", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.get_current_bot_information", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.login", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.close", new_callable=AsyncMock)
    def test_send_recap_to_owner(self, mock_close, mock_login, mock_bot_info, mock_create_dm, mock_create_msg):
        os.environ["DISCORD_TOKEN"] = "test_discord_token"
        mock_bot_info.return_value = {
            "id": "1111111111",
            "owner": {
                "id": "123456789",
                "username": "SuperOwner"
            }
        }
        mock_create_dm.return_value = {"id": "dm_channel_555"}
        mock_create_msg.return_value = {"id": "sent_msg_999"}

        payload = {
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "target_type": "owner",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "stats_summary": {
                "total_time": "12h 30m",
                "streak": "5 days",
                "top_day": "2025-01-15 (3h 0m)",
                "top_book": "Oathbringer",
                "top_author": "Brandon Sanderson"
            },
            "message": "Custom test note"
        }

        with TestClient(app) as client:
            res = client.post("/api/send-recap", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["recipient_id"], "123456789")
            self.assertEqual(data["message_id"], "sent_msg_999")

            # Verify mock calls
            mock_create_dm.assert_called_once_with(recipient_id="123456789")
            mock_create_msg.assert_called_once()
            call_kwargs = mock_create_msg.call_args.kwargs
            self.assertEqual(call_kwargs["channel_id"], "dm_channel_555")
            self.assertIn("embeds", call_kwargs["payload"])
            embed_dict = call_kwargs["payload"]["embeds"][0]
            self.assertEqual(embed_dict["title"], "📊 Dynamic Listening Recap")
            self.assertEqual(embed_dict["image"]["url"], "attachment://listening-recap.png")
            self.assertEqual(len(call_kwargs["files"]), 1)
            self.assertEqual(call_kwargs["files"][0].file_name, "listening-recap.png")

    @patch("interactions.api.http.http_client.HTTPClient.create_message", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.create_dm", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.login", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.close", new_callable=AsyncMock)
    def test_send_recap_to_user(self, mock_close, mock_login, mock_create_dm, mock_create_msg):
        os.environ["DISCORD_TOKEN"] = "test_discord_token"
        mock_create_dm.return_value = {"id": "dm_channel_777"}
        mock_create_msg.return_value = {"id": "sent_msg_888"}

        payload = {
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "target_type": "user",
            "target_id": "987654321098765432",
            "message": "Enjoy your listening recap!"
        }

        with TestClient(app) as client:
            res = client.post("/api/send-recap", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["recipient_id"], "987654321098765432")
            mock_create_dm.assert_called_once_with(recipient_id="987654321098765432")

    @patch("interactions.api.http.http_client.HTTPClient.create_message", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.create_dm", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.login", new_callable=AsyncMock)
    @patch("interactions.api.http.http_client.HTTPClient.close", new_callable=AsyncMock)
    def test_send_recap_to_channel(self, mock_close, mock_login, mock_create_dm, mock_create_msg):
        os.environ["DISCORD_TOKEN"] = "test_discord_token"
        mock_create_msg.return_value = {"id": "channel_msg_123"}

        payload = {
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "target_type": "channel",
            "target_id": "112233445566778899",
            "message": "Here is the channel recap!"
        }

        with TestClient(app) as client:
            res = client.post("/api/send-recap", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["recipient_id"], "112233445566778899")
            # Channel sending does NOT create a DM
            mock_create_dm.assert_not_called()
            mock_create_msg.assert_called_once()
            call_kwargs = mock_create_msg.call_args.kwargs
            self.assertEqual(call_kwargs["channel_id"], "112233445566778899")

    def test_send_recap_missing_token_or_invalid_payload(self):
        # Missing token
        if "DISCORD_TOKEN" in os.environ:
            del os.environ["DISCORD_TOKEN"]

        with TestClient(app) as client:
            res = client.post("/api/send-recap", json={"image_base64": "fake", "target_type": "owner"})
            self.assertEqual(res.status_code, 400)
            self.assertIn("DISCORD_TOKEN", res.json()["detail"])

        os.environ["DISCORD_TOKEN"] = "fake_token"
        with TestClient(app) as client:
            # Invalid base64
            res = client.post("/api/send-recap", json={"image_base64": "!!!not-valid-base64@@@", "target_type": "owner"})
            self.assertEqual(res.status_code, 400)


class TestDefaultCommandsListeningRecap(unittest.IsolatedAsyncioTestCase):

    @patch("bookshelfAPI.bookshelf_cover_image", new_callable=AsyncMock)
    @patch("bookshelfAPI.get_custom_listening_stats", new_callable=AsyncMock)
    async def test_listening_recap_command(self, mock_get_stats, mock_cover):
        from default_commands import PrimaryCommands

        mock_get_stats.return_value = {
            "timeframe": {"startDate": "2025-01-01", "endDate": "2025-01-31"},
            "totalListeningTime": 7200,
            "timeFormatted": {"days": 0, "hours": 2, "minutes": 0, "seconds": 0, "display": "2h 0m"},
            "daysListened": 5,
            "streak": 3,
            "topDay": {"date": "2025-01-15", "formattedTime": "1h 30m"},
            "topBooks": [{"id": "b-123", "title": "The Way of Kings", "author": "Brandon Sanderson", "formattedTime": "2h 0m"}],
            "topAuthors": [{"name": "Brandon Sanderson", "formattedTime": "2h 0m"}],
            "topGenres": [{"name": "Fantasy", "formattedTime": "2h 0m"}]
        }
        mock_cover.return_value = "https://example.com/cover.jpg"

        mock_bot = MagicMock()
        extension = PrimaryCommands(mock_bot)

        mock_ctx = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.accent_color = None

        await extension.listening_recap(mock_ctx, days=30)

        mock_ctx.defer.assert_called_once()
        mock_ctx.send.assert_called_once()
        sent_embed = mock_ctx.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(sent_embed)
        self.assertEqual(sent_embed.title, "📊 Listening Recap")
        self.assertIn("2025-01-01 to 2025-01-31", sent_embed.description)


if __name__ == "__main__":
    unittest.main()
