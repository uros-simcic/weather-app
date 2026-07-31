"""Score what we actually published against what the stations actually measured.

The backtest scores against Open-Meteo's archive (ERA5) — which is ECMWF's own
reanalysis, so ECMWF-family members are partly graded on their own homework.
This script uses real Bilje / Nova Gorica readings from data/log_obs.csv as
truth instead, which is the only bias-free signal we have.

It tracks two things per variable:
  * MAE            — how far off the value was
  * daily range err — (our max-min) minus (measured max-min). This is the metric
                      that catches the forecast going flat: a model predicting a
                      constant 28C all day can post a decent MAE while being
                      obviously wrong to anyone looking out of the window.

Appends to data/verification.csv and rewrites data/verification_report.md.
"""
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import TIMEZONE

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
OBS_LOG = os.path.join(DATA_DIR, "log_obs.csv")
FORECAST_LOG = os.path.join(DATA_DIR, "log_published.csv")
VERIFY_CSV = os.path.join(DATA_DIR, "verification.csv")
VERIFY_REPORT = os.path.join(DATA_DIR, "verification_report.md")

REPORT_DAYS = 30
# Observations logged before this point used the runner's timezone (UTC in CI)
# rather than Europe/Ljubljana, so their hours are 2 off and would corrupt any
# score computed from them. Scoring starts from the fix.
TZ_FIX_CUTOFF = datetime(2026, 7, 26)
# Both log_published.csv and log_obs.csv use the pipeline's own variable names,
# so no translation is needed. (An earlier VAR_MAP translated to forecast.json's
# short keys — 't', 'rh' — which never matched the log, so every lookup missed
# and verification silently scored zero rows.)
SCORED_VARS = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m")
SCORED_NETWORKS = ("arso", "wu")


def load_observations():
    """{date: {variable: {hour: median_value}}} from ARSO stations only.

    Both logs are naive Europe/Ljubljana. That is only true for rows written
    after the astimezone fix in fetch_obs.py — earlier rows are UTC and would
    be scored 2 hours out of step against the forecast, so they are skipped.
    """
    if not os.path.exists(OBS_LOG):
        return {}
    per_hour = defaultdict(list)
    with open(OBS_LOG) as f:
        for r in csv.DictReader(f):
            # The same sources zdaj is built from, so what the forecast is
            # scored against is what the app actually showed — Vipolže included,
            # since it is the only station in Brda. FVG is still excluded: its
            # 24h no-republish clause makes it training-only.
            if r.get("network") not in SCORED_NETWORKS:
                continue
            try:
                dt = datetime.fromisoformat(r["obs_time"])
                value = float(r["value"])
            except (ValueError, KeyError):
                continue
            if dt < TZ_FIX_CUTOFF:
                continue  # logged on the old, UTC-shifted clock
            per_hour[(dt.date().isoformat(), r["variable"], dt.hour)].append(value)

    out = defaultdict(lambda: defaultdict(dict))
    for (d, var, hour), values in per_hour.items():
        values.sort()
        out[d][var][hour] = values[len(values) // 2]  # median across stations
    return out


def load_published():
    """{target_date: {variable: {hour: value}}} — what we showed, per block."""
    if not os.path.exists(FORECAST_LOG):
        return {}
    out = defaultdict(lambda: defaultdict(dict))
    with open(FORECAST_LOG) as f:
        for r in csv.DictReader(f):
            try:
                dt = datetime.fromisoformat(r["valid_time"])
                value = float(r["value"])
            except (ValueError, KeyError):
                continue
            out[dt.date().isoformat()][r["variable"]][dt.hour] = value
    return out


def score_day(day, published, observed):
    """One row per variable for a single day: MAE + how well the daily swing matched."""
    rows = []
    for var in SCORED_VARS:
        pub = published.get(var, {})
        obs = observed.get(var, {})
        shared = sorted(set(pub) & set(obs))
        if len(shared) < 4:  # too little overlap to say anything meaningful
            continue
        errors = [abs(pub[h] - obs[h]) for h in shared]
        pub_range = max(pub[h] for h in shared) - min(pub[h] for h in shared)
        obs_range = max(obs[h] for h in shared) - min(obs[h] for h in shared)
        rows.append({
            "date": day,
            "variable": var,
            "n_hours": len(shared),
            "mae": round(sum(errors) / len(errors), 3),
            "forecast_range": round(pub_range, 2),
            "observed_range": round(obs_range, 2),
            "range_error": round(pub_range - obs_range, 2),
        })
    return rows


def append_rows(rows):
    if not rows:
        return
    fields = ["date", "variable", "n_hours", "mae", "forecast_range", "observed_range", "range_error"]
    existing = set()
    if os.path.exists(VERIFY_CSV):
        with open(VERIFY_CSV) as f:
            existing = {(r["date"], r["variable"]) for r in csv.DictReader(f)}
    fresh = [r for r in rows if (r["date"], r["variable"]) not in existing]
    if not fresh:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    is_new = not os.path.exists(VERIFY_CSV)
    with open(VERIFY_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            w.writeheader()
        w.writerows(fresh)
    return len(fresh)


def write_report():
    cutoff = (date.today() - timedelta(days=REPORT_DAYS)).isoformat()
    per_var = defaultdict(list)
    if os.path.exists(VERIFY_CSV):
        with open(VERIFY_CSV) as f:
            for r in csv.DictReader(f):
                if r["date"] >= cutoff:
                    per_var[r["variable"]].append(r)

    lines = [
        "# Verification report", "",
        f"Rolling {REPORT_DAYS} days, scored against **real ARSO station readings** "
        "(Bilje / Nova Gorica median) — not ERA5, so unlike backtest_report.md this "
        "carries no ECMWF self-grading bias.", "",
        "`range_error` = our daily swing minus the measured one. Persistent "
        "negative values mean the forecast is flattening (under-predicting how much "
        "the temperature moves), which plain MAE can hide.", "",
    ]
    if not per_var:
        lines += [
            "_No scored days yet._ Scoring needs a full day where we published a "
            "forecast **and** later observed it — so the first rows appear a day "
            "after `log_published.csv` starts filling.", ""]
    for var, rows in sorted(per_var.items()):
        maes = [float(r["mae"]) for r in rows]
        rerrs = [float(r["range_error"]) for r in rows]
        lines += [
            f"## {var}", "",
            f"- days scored: **{len(rows)}**",
            f"- mean MAE: **{sum(maes)/len(maes):.2f}**",
            f"- mean range error: **{sum(rerrs)/len(rerrs):+.2f}** "
            f"(negative = forecast too flat)", "",
            "| date | n_hours | mae | forecast_range | observed_range | range_error |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(rows, key=lambda x: x["date"], reverse=True)[:REPORT_DAYS]:
            lines.append(
                f"| {r['date']} | {r['n_hours']} | {r['mae']} | {r['forecast_range']} "
                f"| {r['observed_range']} | {r['range_error']} |")
        lines.append("")

    with open(VERIFY_REPORT, "w") as f:
        f.write("\n".join(lines))


def main():
    observations = load_observations()
    published = load_published()
    if not observations or not published:
        print("verify: not enough logged data yet (need both published forecasts "
              "and station observations)", file=sys.stderr)
        write_report()
        return

    rows = []
    for day in sorted(set(observations) & set(published)):
        rows += score_day(day, published[day], observations[day])

    added = append_rows(rows) or 0
    write_report()
    print(f"verify: scored {len(rows)} variable-days ({added} new), wrote {VERIFY_REPORT}")


if __name__ == "__main__":
    main()
