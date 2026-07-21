"""Daily retrain: LightGBM per variable on historical archive + accumulated
live logs (data/log_forecasts.csv, data/log_obs.csv once they exist).
Only trains variables/cells where blend_decisions.json says the ML blend
actually beats the equal-weight mean (§5.3 fallback rule) — otherwise
blend.py just uses the mean directly, no model needed for that cell.
"""
import json
import os
import pickle
import sys
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from backtest import BACKFILL_MONTHS, feature_columns, fit_blend_model, to_wide
from config import TRAINING_HISTORY_START
from features import TRAIN_VARS, build_training_rows

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MODELS_DIR = os.path.join(DATA_DIR, "models")
DECISIONS_PATH = os.path.join(DATA_DIR, "blend_decisions.json")
LOG_PATH = os.path.join(DATA_DIR, "log_forecasts.csv")


def load_live_rows():
    """Today's own logged forecasts (fetch_models.py) — has real lead_hours,
    unlike the historical archive. Ground truth isn't known yet for future
    hours, so these only contribute once matched against later observations;
    for now train.py just uses the historical set plus whatever's matchable."""
    if not os.path.exists(LOG_PATH):
        return []
    df = pd.read_csv(LOG_PATH)
    return df.to_dict("records")


def any_ml_cell(decisions):
    return any(v == "lightgbm_blend" for v in decisions.values())


def main():
    if not os.path.exists(DECISIONS_PATH):
        print("train: no blend_decisions.json — run backtest.py first", file=sys.stderr)
        return
    with open(DECISIONS_PATH) as f:
        decisions = json.load(f)

    if not any_ml_cell(decisions):
        print("train: no cell where the blend beats the mean — nothing to train")
        return

    end = date.today()
    start = date(end.year, end.month, 1) - timedelta(days=BACKFILL_MONTHS * 31)
    start = max(start, date.fromisoformat(TRAINING_HISTORY_START))
    rows = build_training_rows(start.isoformat(), end.isoformat())
    wide = to_wide(rows)
    if wide.empty:
        print("train: no training data available, aborting", file=sys.stderr)
        return

    cols = feature_columns()
    os.makedirs(MODELS_DIR, exist_ok=True)
    trained = []
    for var in TRAIN_VARS:
        # Only bother training variables with at least one cell that actually
        # ships the ML blend (§5.3) — otherwise blend.py never uses this model.
        if not any(k.startswith(var + "|") and v == "lightgbm_blend" for k, v in decisions.items()):
            continue
        sub = wide[wide.variable == var]
        if sub.empty:
            continue
        model = fit_blend_model(sub[cols].astype(float), sub["truth"])
        path = os.path.join(MODELS_DIR, f"{var}.pkl")
        with open(path, "wb") as f:
            pickle.dump({"model": model, "feature_columns": cols}, f)
        trained.append(var)

    print(f"train: retrained {trained}")


if __name__ == "__main__":
    main()
