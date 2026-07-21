"""Backtest: single members vs equal-weight mean vs LightGBM blend.

Temporal split (never random, per spec): train on the older portion of the
historical window, hold out the most recent 12 weeks. Per variable x lead
bucket, ships the LightGBM blend only where it beats the equal-weight mean
on the holdout — otherwise blend.py falls back to the mean for that cell.
"""
import json
import os
import sys
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from config import OPEN_METEO_MODELS, TRAINING_HISTORY_START
from features import TRAIN_VARS, build_training_rows, lead_bucket

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
REPORT_PATH = os.path.join(DATA_DIR, "backtest_report.md")
DECISIONS_PATH = os.path.join(DATA_DIR, "blend_decisions.json")

HOLDOUT_WEEKS = 12
BACKFILL_MONTHS = 13  # >= spec's 12-month minimum, with margin


def to_wide(rows):
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["lead_bucket"] = df["lead_hours"].apply(lead_bucket)
    # lead_hours is excluded from the index: pivot_table silently drops rows
    # wherever an index column is NaN, and it's always None for historical
    # rows (see features.py) — carried as a plain feature column instead.
    wide = df.pivot_table(
        index=["time", "variable", "lead_bucket", "hour_of_day", "doy_sin", "doy_cos", "truth"],
        columns="member", values="value", aggfunc="first",
    ).reset_index()
    wide["lead_hours"] = float("nan")
    for model in OPEN_METEO_MODELS:
        if model not in wide.columns:
            wide[model] = pd.NA
        wide[f"{model}_avail"] = wide[model].notna().astype(int)
    return wide


def fit_blend_model(X, y):
    import lightgbm as lgb
    model = lgb.LGBMRegressor(n_estimators=200, max_depth=6, learning_rate=0.05, verbosity=-1)
    model.fit(X, y)
    return model


def feature_columns():
    return OPEN_METEO_MODELS + [f"{m}_avail" for m in OPEN_METEO_MODELS] + \
        ["lead_hours", "hour_of_day", "doy_sin", "doy_cos"]


def mae(pred, truth):
    return (pred - truth).abs().mean()


def equal_weight_mean(row):
    values = [row[m] for m in OPEN_METEO_MODELS if pd.notna(row[m])]
    return sum(values) / len(values) if values else float("nan")


def run_backtest(wide):
    cutoff = pd.Timestamp(date.today() - timedelta(weeks=HOLDOUT_WEEKS))
    wide["time_dt"] = pd.to_datetime(wide["time"])
    train = wide[wide["time_dt"] < cutoff]
    holdout = wide[wide["time_dt"] >= cutoff]

    cols = feature_columns()
    results = []
    decisions = {}

    for var in TRAIN_VARS:
        var_train = train[train.variable == var]
        var_hold = holdout[holdout.variable == var].copy()
        if var_train.empty or var_hold.empty:
            continue

        model = fit_blend_model(var_train[cols].astype(float), var_train["truth"])
        var_hold["blend_pred"] = model.predict(var_hold[cols].astype(float))
        var_hold["mean_pred"] = var_hold.apply(equal_weight_mean, axis=1)

        for bucket, bucket_df in var_hold.groupby("lead_bucket"):
            row = {"variable": var, "lead_bucket": bucket, "n": len(bucket_df)}
            for member in OPEN_METEO_MODELS:
                sub = bucket_df[bucket_df[member].notna()]
                row[f"mae_{member}"] = round(mae(sub[member], sub["truth"]), 3) if len(sub) else None
            mean_mae = mae(bucket_df["mean_pred"], bucket_df["truth"])
            blend_mae = mae(bucket_df["blend_pred"], bucket_df["truth"])
            row["mae_equal_weight_mean"] = round(mean_mae, 3)
            row["mae_lightgbm_blend"] = round(blend_mae, 3)
            ship_ml = bool(blend_mae < mean_mae)
            row["ships"] = "lightgbm_blend" if ship_ml else "equal_weight_mean"
            results.append(row)
            decisions[f"{var}|{bucket}"] = row["ships"]

    return results, decisions


def write_report(results):
    lines = [
        "# Backtest report", "",
        f"Holdout: most recent {HOLDOUT_WEEKS} weeks (temporal split, not random).", "",
        "Every row below is `unknown-horizon`: Open-Meteo's historical archive "
        "returns one value per hour, not the original forecast trajectory, so "
        "true lead-time can't be recovered from it. Real per-run lead time (and "
        "the 0-24h/1-3d/3-5d/5-10d buckets this cell will eventually split into) "
        "only exists once fetch_models.py's live daily logs accumulate — "
        "train.py combines both sources going forward.", "",
    ]
    for var in TRAIN_VARS:
        var_rows = [r for r in results if r["variable"] == var]
        if not var_rows:
            continue
        lines.append(f"## {var}")
        lines.append("")
        header = ["lead_bucket", "n"] + [f"mae_{m}" for m in OPEN_METEO_MODELS] + \
            ["mae_equal_weight_mean", "mae_lightgbm_blend", "ships"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        for r in var_rows:
            lines.append("| " + " | ".join(str(r.get(h, "")) for h in header) + " |")
        lines.append("")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))


def write_decisions(decisions):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DECISIONS_PATH, "w") as f:
        json.dump(decisions, f, indent=2)


def main():
    end = date.today()
    start = date(end.year, end.month, 1) - timedelta(days=BACKFILL_MONTHS * 31)
    start = max(start, date.fromisoformat(TRAINING_HISTORY_START))
    print(f"backtest: pulling history {start} to {end}")

    rows = build_training_rows(start.isoformat(), end.isoformat())
    print(f"backtest: {len(rows)} raw rows")
    wide = to_wide(rows)
    if wide.empty:
        print("backtest: no data available, aborting", file=sys.stderr)
        return

    results, decisions = run_backtest(wide)
    write_report(results)
    write_decisions(decisions)
    print(f"backtest: wrote {REPORT_PATH} and {DECISIONS_PATH}")


if __name__ == "__main__":
    main()
