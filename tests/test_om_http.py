import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import om_http
import requests


class ForecastSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "forecast.json")
        self.url = "https://example.test/forecast"
        self.params = {"models": "one,two", "forecast_days": 10}
        self.payload = {"hourly": {"time": ["2026-11-12T14:00"], "temperature": [14]}}
        self.response = Mock(status_code=200)
        self.response.json.return_value = self.payload
        self.addCleanup(patch.stopall)
        self.http = patch.object(om_http.requests, "get", return_value=self.response).start()
        self.sleep = patch.object(om_http.time, "sleep").start()
        self.stderr = contextlib.redirect_stderr(io.StringIO())
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def fetch(self, **kwargs):
        return om_http.get_json(self.url, self.params, snapshot_path=self.path, **kwargs)

    def test_collection_then_blend_needs_only_one_http_request(self):
        self.assertEqual(self.fetch(), self.payload)
        self.http.side_effect = requests.Timeout("second request would fail")
        self.assertEqual(self.fetch(), self.payload)
        self.assertEqual(self.http.call_count, 1)

    def test_invalid_snapshots_fall_back_to_http(self):
        saved = {"url": self.url, "params": self.params,
                 "fetched_at": time.time(), "data": self.payload}
        cases = ["broken JSON", "null", "[]", "{}",
                 json.dumps({**saved, "data": []}),
                 json.dumps({**saved, "url": "https://example.test/other"}),
                 json.dumps({**saved, "params": {"models": "other"}}),
                 json.dumps({**saved, "fetched_at": time.time() - 901}),
                 json.dumps({**saved, "fetched_at": time.time() + 60})]
        for content in cases:
            with self.subTest(content=content):
                Path(self.path).write_text(content)
                self.http.reset_mock()
                self.assertEqual(self.fetch(), self.payload)
                self.http.assert_called_once()

    def test_missing_snapshot_downloads_and_saves(self):
        self.assertEqual(self.fetch(), self.payload)
        self.assertEqual(json.loads(Path(self.path).read_text())["data"], self.payload)

    def test_snapshot_write_failure_does_not_lose_successful_download(self):
        with patch.object(om_http, "write_json", side_effect=OSError("disk full")):
            self.assertEqual(self.fetch(), self.payload)

    def test_rate_limit_retries_and_failure_creates_no_snapshot(self):
        self.response.status_code = 429
        self.response.headers = {"Retry-After": "3"}
        self.response.url = self.url
        with self.assertRaises(requests.HTTPError):
            self.fetch(timeouts=(1, 1, 1))
        self.assertEqual(self.http.call_count, 3)
        self.assertEqual(self.sleep.call_count, 3)
        self.assertFalse(Path(self.path).exists())

    def test_timeout_then_success_is_saved(self):
        self.http.side_effect = [requests.Timeout("temporary"), self.response]
        self.assertEqual(self.fetch(timeouts=(1, 2)), self.payload)
        self.assertEqual(self.fetch(), self.payload)
        self.assertEqual(self.http.call_count, 2)

    def test_other_callers_still_fetch_on_each_call(self):
        for _ in range(2):
            self.assertEqual(om_http.get_json(self.url, self.params), self.payload)
        self.assertEqual(self.http.call_count, 2)


if __name__ == "__main__":
    unittest.main()
