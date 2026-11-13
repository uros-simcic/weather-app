from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import fetch_obs


class ObservationTimestampTests(unittest.TestCase):
    def test_actual_observation_time_is_separate_from_publication_in_both_seasons(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(fetch_obs, "SITE_DIR", tmp), \
                patch.object(fetch_obs, "NOW_PATH", str(Path(tmp) / "now.json")), \
                patch.object(fetch_obs, "current_hour_icon_uv", return_value=("cloud", 0)):
            for month, offset in [(7, "+02:00"), (11, "+01:00")]:
                with self.subTest(month=month):
                    fetch_obs.write_now_json(datetime(2026, month, 12, 14, 7),
                                             {"temperature_2m": 14}, ["NOVA_GORICA"],
                                             observed_at=datetime(2026, month, 12, 14))
                    data = json.loads(Path(fetch_obs.NOW_PATH).read_text())
                    self.assertEqual(data["observed_at"], f"2026-{month:02d}-12T14:00:00{offset}")
                    self.assertEqual(data["measured_at"], f"2026-{month:02d}-12T14:07:00{offset}")
                    self.assertEqual(data["source"], "stations")
            fetch_obs.write_now_json(datetime(2026, 11, 12, 14), {}, [],
                                     observed_at=datetime(2026, 11, 12, 13))
            data = json.loads(Path(fetch_obs.NOW_PATH).read_text())
            self.assertIsNone(data["observed_at"])
            self.assertEqual(data["source"], "model_fallback")


if __name__ == "__main__":
    unittest.main()
