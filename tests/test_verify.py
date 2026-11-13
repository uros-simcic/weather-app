import contextlib
import csv
from datetime import date, datetime
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import verify


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(verify, "DATA_DIR", self.tmp.name).start()
        for name, filename in [("OBS_LOG", "obs.csv"), ("VERIFY_CSV", "scores.csv"),
                               ("VERIFY_REPORT", "report.md")]:
            patch.object(verify, name, str(Path(self.tmp.name) / filename)).start()
        self.today = date(2026, 11, 12)

    @staticmethod
    def row(day, hours=4, mae=1):
        return {"date": day, "variable": "temperature_2m", "n_hours": hours,
                "mae": mae, "forecast_range": 4, "observed_range": 3, "range_error": 1}

    def read_scores(self):
        with open(verify.VERIFY_CSV) as f:
            return list(csv.DictReader(f))

    def test_even_station_median_and_excluded_network(self):
        with open(verify.OBS_LOG, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["obs_time", "station", "network", "variable", "value"])
            writer.writeheader()
            for station, network, value in [("BILJE", "arso", 10), ("VIPOLZE", "wu", 20),
                                             ("CAPRIVA", "fvg", 90)]:
                writer.writerow({"obs_time": "2026-11-11T14:00:00", "station": station,
                                 "network": network, "variable": "temperature_2m", "value": value})
        self.assertEqual(verify.load_observations()["2026-11-11"]["temperature_2m"][14], 15)

    def test_replaces_partial_scores_preserves_unavailable_history_and_is_idempotent(self):
        verify.save_rows([self.row("2026-08-01"), self.row("2026-11-11")], self.today)
        replacement = self.row("2026-11-11", hours=20, mae=2)
        self.assertEqual(verify.save_rows([replacement], self.today), (0, 1, 0))
        rows = self.read_scores()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["n_hours"], "20")
        self.assertEqual(rows[-1]["mae"], "2")
        original = Path(verify.VERIFY_CSV).read_bytes()
        self.assertEqual(verify.save_rows([replacement], self.today), (0, 0, 0))
        self.assertEqual(Path(verify.VERIFY_CSV).read_bytes(), original)

    def test_incomplete_saved_scores_removed_and_new_ones_not_inserted(self):
        verify.save_rows([self.row("2026-11-11"), self.row("2026-11-12")], date(2026, 11, 13))
        self.assertEqual(verify.save_rows([self.row("2026-11-12")], self.today), (0, 0, 1))
        self.assertEqual([r["date"] for r in self.read_scores()], ["2026-11-11"])

    def test_report_has_exact_30_completed_calendar_day_window(self):
        verify.save_rows([self.row(d) for d in ["2026-10-12", "2026-10-13", "2026-11-11", "2026-11-12"]],
                         date(2026, 11, 13))
        verify.write_report(self.today)
        report = Path(verify.VERIFY_REPORT).read_text()
        self.assertIn("days scored: **2**", report)
        self.assertIn("2026-10-13", report)
        self.assertIn("2026-11-11", report)
        self.assertNotIn("2026-10-12", report)
        self.assertNotIn("2026-11-12", report)

    def test_main_uses_ljubljana_day_after_utc_midnight_boundary(self):
        # At 23:30 UTC on Nov 11, Ljubljana has already completed Nov 11.
        instant = datetime.fromisoformat("2026-11-11T23:30:00+00:00")
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz)
        hours = {"temperature_2m": {0: 10, 6: 12, 12: 16, 18: 14}}
        days = {"2026-11-11": hours, "2026-11-12": hours}
        with patch.object(verify, "datetime", Clock), \
                patch.object(verify, "load_observations", return_value=days), \
                patch.object(verify, "load_published", return_value=days), \
                contextlib.redirect_stdout(io.StringIO()):
            verify.main()
        self.assertEqual([r["date"] for r in self.read_scores()], ["2026-11-11"])

    def test_failed_replace_keeps_existing_scores_and_cleans_temp_file(self):
        verify.save_rows([self.row("2026-11-11")], self.today)
        previous = Path(verify.VERIFY_CSV).read_bytes()
        with patch.object(verify.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                verify.save_rows([self.row("2026-11-11", hours=20)], self.today)
        self.assertEqual(Path(verify.VERIFY_CSV).read_bytes(), previous)
        self.assertFalse(Path(verify.VERIFY_CSV + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
