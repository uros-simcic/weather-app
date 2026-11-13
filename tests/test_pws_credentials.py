import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import fetch_obs
import requests


class VipolzeTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.http = patch.object(fetch_obs.requests, "get").start()
        patch.dict(fetch_obs.os.environ, {"WU_PWS_API_KEY": "test-only-key"}).start()
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_missing_key_skips_only_vipolze_without_request(self):
        with patch.dict(fetch_obs.os.environ, {"WU_PWS_API_KEY": " "}):
            self.assertEqual(fetch_obs.fetch_vipolze(), {})
        self.http.assert_not_called()
        self.assertIn("not configured", self.stderr.getvalue())

    def test_http_failure_does_not_log_credential_bearing_url(self):
        response = Mock(status_code=401)
        self.http.side_effect = requests.HTTPError(
            "401 https://example.test/?apiKey=test-only-key", response=response)
        self.assertEqual(fetch_obs.fetch_vipolze(), {})
        self.assertIn("HTTP 401", self.stderr.getvalue())
        self.assertNotIn("test-only-key", self.stderr.getvalue())
        self.assertNotIn("https://", self.stderr.getvalue())

    def test_timeout_does_not_log_credential_bearing_url(self):
        self.http.side_effect = requests.Timeout("https://example.test/?apiKey=test-only-key")
        self.assertEqual(fetch_obs.fetch_vipolze(), {})
        self.assertIn("Timeout", self.stderr.getvalue())
        self.assertNotIn("test-only-key", self.stderr.getvalue())

    def test_authorized_observation_is_parsed_with_ljubljana_time(self):
        epoch = datetime.fromisoformat("2026-11-12T13:00:00+00:00").timestamp()
        observation = {"epoch": epoch, "qcStatus": 0, "humidity": 90,
                       "metric": {"temp": 14, "precipRate": 0, "precipTotal": 2}}
        self.http.return_value.json.return_value = {"observations": [observation]}
        result = fetch_obs.fetch_vipolze()["VIPOLZE"]
        self.assertEqual(result["obs_time"], datetime(2026, 11, 12, 14))
        self.assertEqual(result["temperature_2m"], 14)
        self.assertEqual(self.http.call_args.kwargs["params"]["apiKey"], "test-only-key")
        observation["qcStatus"] = -1
        self.assertEqual(fetch_obs.fetch_vipolze(), {})


if __name__ == "__main__":
    unittest.main()
