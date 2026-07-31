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
from safe_write import write_json

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
            wide[model] = float("nan")  # pd.NA breaks .astype(float) downstream
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


def member_maes(train_df):
    """Per-member MAE on the TRAIN split only — using holdout MAEs to build
    holdout weights would leak the answer into the evaluation."""
    out = {}
    for m in OPEN_METEO_MODELS:
        sub = train_df[train_df[m].notna()]
        if len(sub):
            out[m] = float(mae(sub[m], sub["truth"]))
    return out


def weighted_mean(row, maes, power):
    """Skill-weighted ensemble: weight ∝ (1/MAE)^power. power=0 is the plain
    mean; higher powers concentrate weight on the historically better members."""
    num = den = 0.0
    for m in OPEN_METEO_MODELS:
        v = row[m]
        if pd.notna(v) and maes.get(m):
            w = (1.0 / maes[m]) ** power
            num += w * v
            den += w
    return num / den if den else float("nan")


# Candidate blend methods, evaluated per variable x lead bucket. The winner is
# whatever actually has the lowest holdout MAE — measured, never assumed:
# weighting helps temperature/RH/wind a lot but HURTS precipitation, so no
# single scheme can be applied blanket across variables.
WEIGHT_POWERS = (1, 2, 3)


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

        maes = member_maes(var_train)
        model = fit_blend_model(var_train[cols].astype(float), var_train["truth"])
        var_hold["blend_pred"] = model.predict(var_hold[cols].astype(float))
        var_hold["mean_pred"] = var_hold.apply(equal_weight_mean, axis=1)
        for p in WEIGHT_POWERS:
            var_hold[f"w{p}_pred"] = var_hold.apply(lambda r, p=p: weighted_mean(r, maes, p), axis=1)

        for bucket, bucket_df in var_hold.groupby("lead_bucket"):
            row = {"variable": var, "lead_bucket": bucket, "n": len(bucket_df)}
            for member in OPEN_METEO_MODELS:
                sub = bucket_df[bucket_df[member].notna()]
                row[f"mae_{member}"] = round(mae(sub[member], sub["truth"]), 3) if len(sub) else None

            candidates = {
                "equal_weight_mean": mae(bucket_df["mean_pred"], bucket_df["truth"]),
                "lightgbm_blend": mae(bucket_df["blend_pred"], bucket_df["truth"]),
            }
            for p in WEIGHT_POWERS:
                candidates[f"weighted_mean_p{p}"] = mae(bucket_df[f"w{p}_pred"], bucket_df["truth"])

            for name, value in candidates.items():
                row[f"mae_{name}"] = round(value, 3)
            winner = min(candidates, key=candidates.get)
            row["ships"] = winner
            results.append(row)
            decisions[f"{var}|{bucket}"] = winner

        # Weights travel with the decisions so blend.py can reproduce the exact
        # weighted mean the backtest picked, without recomputing any history.
        decisions[f"{var}|member_mae"] = {k: round(v, 4) for k, v in maes.items()}

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
        "**Truth-source caveat:** ground truth here is Open-Meteo's archive "
        "(ERA5), which is ECMWF's own reanalysis — so ECMWF-family members are "
        "measured partly against their own output and will look better than they "
        "are. Treat any ECMWF-favouring result as an upper bound, and prefer "
        "verification.csv (real Bilje / Nova Gorica station readings) as it "
        "accumulates. This is why the shipped choice is a weighted blend rather "
        "than ECMWF alone, even where ECMWF alone scores best here.", "",
        "**The winner's own score is optimistic.** All five candidates are "
        "scored on the same holdout the winner is then picked from, so the "
        "`ships` column and its MAE come from one number doing two jobs. The "
        "lowest of five is low partly on merit and partly on luck, and the "
        "margin over the runner-up is the part that is least real — a win by "
        "less than a few thousandths should be read as a tie. The comparison "
        "between candidates is still fair; it is the winning figure taken as "
        "an estimate of live accuracy that is biased low. Note also that every "
        "row is one decision made on ~85 days of hourly rows, and consecutive "
        "hours are far from independent, so the effective sample behind each "
        "choice is nearer 85 than the printed `n`.", "",
    ]
    for var in TRAIN_VARS:
        var_rows = [r for r in results if r["variable"] == var]
        if not var_rows:
            continue
        lines.append(f"## {var}")
        lines.append("")
        header = ["lead_bucket", "n"] + [f"mae_{m}" for m in OPEN_METEO_MODELS] + \
            ["mae_equal_weight_mean"] + [f"mae_weighted_mean_p{p}" for p in WEIGHT_POWERS] + \
            ["mae_lightgbm_blend", "ships"]
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
    write_json(DECISIONS_PATH, decisions, indent=2)


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
