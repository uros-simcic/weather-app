"""Shared historical data fetch + feature engineering for backtest.py and train.py.

Historical training uses Open-Meteo only: ARSO's archive is login-gated and
pro-vreme has none (both verified), so — same treatment the spec already
gives pro-vreme — they join the live blend at equal weight instead of
contributing historical features.

Open-Meteo's Historical Forecast API returns one value per hour, not the
original multi-day forecast trajectory — true lead-time genuinely can't be
recovered from it (verified: any hours-since-run heuristic caps at 0-12h by
construction, silently faking multi-day lead buckets we have no data for).
Historical rows get lead_hours=None ("unknown horizon"); real per-run lead
time only exists once fetch_models.py's live logs accumulate, and train.py
combines both sources — see backtest_report.md's caveat.
"""
import math
import sys
from datetime import datetime, timedelta

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from config import (
    ELEVATION, LAT, LON, OPEN_METEO_HISTORICAL_FORECAST_URL,
    OPEN_METEO_HISTORICAL_WEATHER_URL, OPEN_METEO_MODELS, TIMEZONE,
)

TRAIN_VARS = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precipitation"]




def fetch_model_history(model, start_date, end_date):
    params = {
        "latitude": LAT, "longitude": LON, "timezone": TIMEZONE,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(TRAIN_VARS), "models": model,
    }
    # A ~13-month single-model pull is a large response; the API has been
    # observed to occasionally exceed a 60s timeout — one retry with more
    # headroom before giving up on this member for the run.
    last_error = None
    for timeout in (60, 120):
        try:
            resp = requests.get(OPEN_METEO_HISTORICAL_FORECAST_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
    raise last_error


def fetch_truth_history(start_date, end_date):
    params = {
        "latitude": LAT, "longitude": LON, "timezone": TIMEZONE,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(TRAIN_VARS),
    }
    resp = requests.get(OPEN_METEO_HISTORICAL_WEATHER_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def build_training_rows(start_date, end_date):
    """One row per (hour, member, variable) with truth + engineered features."""
    truth = fetch_truth_history(start_date, end_date)
    truth_hourly = truth.get("hourly", {})
    times = truth_hourly.get("time", [])
    truth_by_var = {var: dict(zip(times, truth_hourly.get(var, []))) for var in TRAIN_VARS}

    rows = []
    for model in OPEN_METEO_MODELS:
        try:
            data = fetch_model_history(model, start_date, end_date)
        except requests.RequestException as e:
            print(f"features: {model} history failed, skipping ({e})", file=sys.stderr)
            continue
        hourly = data.get("hourly", {})
        m_times = hourly.get("time", [])
        for var in TRAIN_VARS:
            series = hourly.get(var)
            if series is None:
                continue
            for t, value in zip(m_times, series):
                if value is None:
                    continue
                truth_value = truth_by_var.get(var, {}).get(t)
                if truth_value is None:
                    continue
                dt = datetime.fromisoformat(t)
                rows.append({
                    "time": t, "member": model, "variable": var,
                    "value": value, "truth": truth_value,
                    "lead_hours": None,  # unknown horizon — see module docstring
                    "hour_of_day": dt.hour,
                    "doy_sin": math.sin(2 * math.pi * dt.timetuple().tm_yday / 365),
                    "doy_cos": math.cos(2 * math.pi * dt.timetuple().tm_yday / 365),
                    "elevation_delta": 0,  # at-target grid point; live station logs add diversity
                })
    return rows


def lead_bucket(lead_hours):
    """Coarse buckets for the backtest report, matching the member horizons in §4.1.
    None means unknown horizon (historical archive rows — see module docstring)."""
    if lead_hours is None:
        return "unknown-horizon"
    if lead_hours <= 24:
        return "0-24h"
    if lead_hours <= 72:
        return "1-3d"
    if lead_hours <= 120:
        return "3-5d"
    return "5-10d"
