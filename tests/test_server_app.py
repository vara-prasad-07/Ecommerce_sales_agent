import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class CallTriggerEndpointTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {"CALL_TRIGGER_PASSWORD": "letmein", "MIN_SECONDS_BETWEEN_CALLS": "0"},
        )
        self.env_patch.start()

        import server.app as app_module

        self.app_module = app_module
        app_module._last_trigger_at = 0.0
        self.client = TestClient(app_module.app)

    def tearDown(self):
        self.env_patch.stop()

    def test_index_serves_the_form(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Call now", response.text)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            "/api/call", json={"phone_number": "+919876543210", "password": "nope"}
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_phone_number_is_rejected(self):
        response = self.client.post(
            "/api/call", json={"phone_number": "12", "password": "letmein"}
        )
        self.assertEqual(response.status_code, 422)

    @patch("server.app.dispatch_call", new_callable=AsyncMock)
    @patch("server.app.storage.record_call_trigger", new_callable=AsyncMock)
    def test_correct_password_dispatches_the_call(self, mock_record, mock_dispatch):
        mock_dispatch.return_value = {"room_name": "call-abc123", "participant_identity": "caller-x"}

        response = self.client.post(
            "/api/call",
            json={"phone_number": "+91 98765 43210", "password": "letmein"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "dialing")
        self.assertEqual(body["phone_number"], "+919876543210")
        mock_dispatch.assert_awaited_once_with("+919876543210", wait_until_answered=False)
        mock_record.assert_awaited_once()

    @patch("server.app.dispatch_call", new_callable=AsyncMock)
    @patch("server.app.storage.record_call_trigger", new_callable=AsyncMock)
    def test_cooldown_blocks_rapid_second_call(self, mock_record, mock_dispatch):
        mock_dispatch.return_value = {"room_name": "call-abc123", "participant_identity": "caller-x"}

        with patch.dict(os.environ, {"MIN_SECONDS_BETWEEN_CALLS": "60"}):
            first = self.client.post(
                "/api/call", json={"phone_number": "+919876543210", "password": "letmein"}
            )
            self.assertEqual(first.status_code, 200)

            second = self.client.post(
                "/api/call", json={"phone_number": "+919876543211", "password": "letmein"}
            )
            self.assertEqual(second.status_code, 429)

    def test_missing_server_password_config_returns_500(self):
        with patch.dict(os.environ, {"CALL_TRIGGER_PASSWORD": ""}):
            response = self.client.post(
                "/api/call", json={"phone_number": "+919876543210", "password": "letmein"}
            )
            self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
