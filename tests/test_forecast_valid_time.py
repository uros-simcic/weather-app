import csv
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import fetch_models


class ForecastValidTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "forecasts.csv"
        self.addCleanup(patch.stopall)
        patch.object(fetch_models, "LOG_PATH", str(self.path)).start()
        patch.object(fetch_models, "DATA_DIR", self.tmp.name).start()
        patch.object(fetch_models, "trim_log").start()

    def test_legacy_rows_preserved_and_new_valid_time_appended(self):
        self.path.write_bytes(b"run_time,member,lead_hours,variable,value\r\n"
                              b"2026-11-15T12:07:00,model,1,temperature_2m,10\r\n")
        row = {"run_time": "2026-11-15T13:07:00", "member": "model",
               "lead_hours": 1, "variable": "temperature_2m", "value": 11,
               "valid_time": "2026-11-15T14:00"}
        fetch_models.append_rows([row])
        with self.path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, fetch_models.CSV_FIELDS)
        self.assertEqual(rows[0]["value"], "10")
        self.assertEqual(rows[0]["valid_time"], "")
        self.assertEqual(rows[1]["valid_time"], row["valid_time"])
        before = self.path.read_bytes()
        fetch_models.ensure_log_schema()
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_migration_preserves_original(self):
        original = b"run_time,member,lead_hours,variable,value\r\nx,m,0,t,1\r\n"
        self.path.write_bytes(original)
        with patch.object(fetch_models.os, "replace", side_effect=OSError("test")):
            with self.assertRaises(OSError):
                fetch_models.ensure_log_schema()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(Path(str(self.path) + ".schema.tmp").exists())

    def test_unknown_schema_is_not_rewritten(self):
        original = b"unexpected,columns\r\na,b\r\n"
        self.path.write_bytes(original)
        with self.assertRaises(ValueError):
            fetch_models.ensure_log_schema()
        self.assertEqual(self.path.read_bytes(), original)

    def test_empty_file_gets_header_and_unknown_times_stay_blank(self):
        self.path.touch()
        fetch_models.append_rows([{"run_time": "x", "member": "bulletin",
                                  "lead_hours": 24, "variable": "reliability_pct", "value": 70}])
        with self.path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(list(reader)[0]["valid_time"], "")
            self.assertEqual(reader.fieldnames, fetch_models.CSV_FIELDS)

    def test_open_meteo_preserves_source_time(self):
        payload = {"hourly": {"time": ["2026-11-15T14:00"],
                             "temperature_2m_model": [10]}}
        with patch.object(fetch_models, "get_json", return_value=payload), \
                patch.object(fetch_models, "OPEN_METEO_MODELS", ["model"]), \
                patch.object(fetch_models, "OPEN_METEO_HOURLY_VARS", ["temperature_2m"]):
            rows = fetch_models.fetch_open_meteo("2026-11-15T13:07:00",
                                                datetime(2026, 11, 15, 13, 7))
        self.assertEqual(rows[0]["valid_time"], "2026-11-15T14:00")

    def test_arso_preserves_offset_in_source_time(self):
        valid = "2026-11-15T13:00:00+00:00"
        response = Mock()
        response.json.return_value = {"forecast1h": {"features": [{"properties": {
            "days": [{"timeline": [{"valid": valid, "t": "10"}]}]}}]}}
        with patch.object(fetch_models.requests, "get", return_value=response):
            rows = fetch_models.fetch_arso("2026-11-15T14:07:00",
                                          datetime(2026, 11, 15, 14, 7))
        self.assertEqual(rows[0]["valid_time"], valid)


if __name__ == "__main__":
    unittest.main()
