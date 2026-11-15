"""Offline station-bias experiment; never updates predictions or model files."""
import argparse
import csv
from datetime import date, datetime, timedelta
import json
import math
from statistics import median
from zoneinfo import ZoneInfo

from config import TIMEZONE
from fetch_obs import SANITY_BOUNDS
from verify import FORECAST_LOG, load_observations


def unambiguous_local(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    # Naive legacy records cannot resolve the repeated autumn hour.
    zone = ZoneInfo(TIMEZONE)
    if dt.replace(tzinfo=zone, fold=0).utcoffset() != dt.replace(tzinfo=zone, fold=1).utcoffset():
        raise ValueError("ambiguous or nonexistent local hour")
    return dt


def evaluate(published, observed, as_of):
    start, split = as_of - timedelta(days=30), as_of - timedelta(days=9)
    paired = {variable: [] for variable in SANITY_BOUNDS}
    for row in published:
        try:
            valid = unambiguous_local(row["valid_time"])
            issued = unambiguous_local(row["run_time"])
            variable = row["variable"]
            if variable not in paired or not start <= valid.date() < as_of:
                continue
            lead = (valid - issued).total_seconds() / 3600
            if not 0 <= lead <= 48:
                continue
            truth = float(observed[valid.date().isoformat()][variable][valid.hour])
            pred = float(row["value"])
            low, high = SANITY_BOUNDS[variable]
            if not math.isfinite(pred) or not math.isfinite(truth) or not low <= truth <= high:
                continue
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
        paired[variable].append((valid, pred, truth))

    results = []
    for variable, pairs in paired.items():
        train = [r for r in pairs if r[0].date() < split]
        test = [r for r in pairs if r[0].date() >= split]
        if not train or not test:
            continue
        bias = median(truth - pred for _, pred, truth in train)
        low, high = SANITY_BOUNDS[variable]
        raw = sum(abs(pred - truth) for _, pred, truth in test) / len(test)
        corrected = sum(abs(min(high, max(low, pred + bias)) - truth)
                        for _, pred, truth in test) / len(test)
        results.append({
            "variable": variable, "fitted_bias": bias,
            "train_rows": len(train), "test_rows": len(test),
            "train_days": len({r[0].date() for r in train}),
            "test_days": len({r[0].date() for r in test}),
            "test_observed_hours": len({r[0].replace(minute=0, second=0, microsecond=0) for r in test}),
            "raw_mae": raw, "corrected_mae": corrected,
        })
    return {
        "as_of": as_of.isoformat(), "train_before": split.isoformat(),
        "deployment_approved": False,
        "limitations": [
            "Repeated forecast issues for the same valid hour are correlated.",
            "One chronological split is exploratory, not an independent promotion test.",
            "Targets follow the existing scoring policy; Vedrijan remains excluded.",
            "No rain calibration: station accumulation windows differ.",
        ],
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat,
                        default=datetime.now(ZoneInfo(TIMEZONE)).date())
    args = parser.parse_args()
    with open(FORECAST_LOG, newline="") as handle:
        report = evaluate(csv.DictReader(handle), load_observations(), args.as_of)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
