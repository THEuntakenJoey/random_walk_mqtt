"""
Unit tests for the Container Fleet REST API client.
Compatible with omni.kit.test.AsyncTestCase.
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

ext_root = Path(__file__).resolve().parent.parent
if str(ext_root) not in sys.path:
    sys.path.insert(0, str(ext_root))

try:
    import omni.kit.test
    BaseTestCase = omni.kit.test.AsyncTestCase
except ImportError:
    import unittest
    BaseTestCase = unittest.TestCase

from impl.container_client import FleetApiClient


class TestFleetApiClient(BaseTestCase):

    async def setUp(self):
        self.client = FleetApiClient(base_url="http://localhost:8000")

    async def tearDown(self):
        self.client.shutdown()

    @patch("urllib.request.urlopen")
    async def test_get_status(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "online",
            "active_devices_count": 2,
            "mqtt_connected": True
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        status = self.client.get_status()
        self.assertEqual(status["status"], "online")
        self.assertEqual(status["active_devices_count"], 2)
        self.assertTrue(status["mqtt_connected"])

    @patch("urllib.request.urlopen")
    async def test_spawn_container(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "spawned",
            "device_id": "dev-999",
            "device_name": "Walker #999"
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.spawn_container(
            device_name="Walker #999",
            model_type="target_waypoints",
            write_hz=30.0,
            color="#38bdf8"
        )
        self.assertEqual(res["status"], "spawned")
        self.assertEqual(res["device_id"], "dev-999")

    @patch("urllib.request.urlopen")
    async def test_kill_container(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "killed",
            "device_id": "dev-999",
            "removed_from_docker": True
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.client.kill_container("dev-999")
        self.assertEqual(res["status"], "killed")
        self.assertEqual(res["device_id"], "dev-999")

    @patch("urllib.request.urlopen")
    async def test_dispatch_async(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "online"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        results = []

        def on_success(res):
            results.append(res)

        self.client.dispatch_async(self.client.get_status, on_success=on_success)
        time.sleep(0.3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "online")


if __name__ == "__main__":
    import unittest
    unittest.main()
