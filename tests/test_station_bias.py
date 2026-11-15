from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from evaluate_station_bias import evaluate, unambiguous_local


class StationBiasTests(unittest.TestCase):
    def fixture(self):
        rows, truth = [], {}
        for offset in range(30):
            day = date(2026, 11, 1) + timedelta(days=offset)
            key = day.isoformat()
            rows.append({"run_time": key + "T11:00:00", "valid_time": key + "T12:00",
                         "variable": "temperature_2m", "value": "8"})
            truth[key] = {"temperature_2m": {12: 10}}
        return rows, truth

    def test_bias_is_fit_on_earlier_dates(self):
        rows, truth = self.fixture()
        report = evaluate(rows, truth, date(2026, 12, 1))
        result = report["results"][0]
        self.assertEqual(result["fitted_bias"], 2)
        self.assertEqual(result["train_days"], 21)
        self.assertEqual(result["test_days"], 9)
        self.assertEqual(result["corrected_mae"], 0)
        self.assertFalse(report["deployment_approved"])

    def test_holdout_labels_do_not_change_fitted_bias(self):
        rows, truth = self.fixture()
        for offset in range(21, 30):
            truth[(date(2026, 11, 1) + timedelta(days=offset)).isoformat()]["temperature_2m"][12] = 20
        result = evaluate(rows, truth, date(2026, 12, 1))["results"][0]
        self.assertEqual(result["fitted_bias"], 2)
        self.assertEqual(result["corrected_mae"], 10)

    def test_invalid_future_and_negative_lead_records_are_excluded(self):
        rows, truth = self.fixture()
        baseline = evaluate(rows, truth, date(2026, 12, 1))
        bad = [dict(rows[0], value="nan"), dict(rows[0], value="inf"),
               dict(rows[0], run_time="2026-11-01T13:00"),
               dict(rows[0], valid_time="2026-12-01T12:00"),
               dict(rows[0], variable="precipitation")]
        self.assertEqual(evaluate(rows + bad, truth, date(2026, 12, 1)), baseline)

    def test_ambiguous_dst_hour_is_not_guessed(self):
        with self.assertRaises(ValueError):
            unambiguous_local("2026-10-25T02:30:00")

    def test_missing_observations_give_no_result(self):
        rows, _ = self.fixture()
        self.assertEqual(evaluate(rows, {}, date(2026, 12, 1))["results"], [])


if __name__ == "__main__":
    unittest.main()
