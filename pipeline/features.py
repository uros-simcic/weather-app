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
import json
import math
import os
import sys
from datetime import date, datetime

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from config import (
    LAT, LON, OPEN_METEO_HISTORICAL_FORECAST_URL,
    OPEN_METEO_HISTORICAL_WEATHER_URL, OPEN_METEO_MODELS, TIMEZONE,
)
from om_http import get_json

TRAIN_VARS = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precipitation"]
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "archive_cache")
ARCHIVE_TIMEOUTS = (60, 120, 180)


def _cache_month():
    return date.today().strftime("%Y-%m")


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _load_cache(name):
    path = _cache_path(name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"features: cache {name} unreadable ({e})", file=sys.stderr)
        return None


def _save_cache(name, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _cache_is_current(start_date):
    meta = _load_cache("meta.json") or {}
    return (
        meta.get("month") == _cache_month()
        and meta.get("start_date") == start_date
        and _load_cache("truth.json") is not None
    )


def _get_archive(url, params):
    return get_json(url, params, timeouts=ARCHIVE_TIMEOUTS)


def fetch_model_history(model, start_date, end_date):
    params = {
        "latitude": LAT, "longitude": LON, "timezone": TIMEZONE,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(TRAIN_VARS), "models": model,
    }
    return _get_archive(OPEN_METEO_HISTORICAL_FORECAST_URL, params)


def fetch_truth_history(start_date, end_date):
    params = {
        "latitude": LAT, "longitude": LON, "timezone": TIMEZONE,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(TRAIN_VARS),
    }
    return _get_archive(OPEN_METEO_HISTORICAL_WEATHER_URL, params)


def _truth_payload(start_date, end_date):
    """Current-month cache, else fetch and store, else stale cache, else raise."""
    cached = _load_cache("truth.json")
    if _cache_is_current(start_date) and cached is not None:
        print("features: truth from archive cache", file=sys.stderr)
        return cached, False
    try:
        data = fetch_truth_history(start_date, end_date)
        _save_cache("truth.json", data)
        return data, True
    except requests.RequestException as e:
        if cached is not None:
            print(f"features: truth fetch failed, using stale cache ({e})", file=sys.stderr)
            return cached, False
        raise


def _model_payload(model, start_date, end_date, allow_cache):
    name = f"{model}.json"
    cached = _load_cache(name)
    if allow_cache and cached is not None:
        return cached, False
    try:
        data = fetch_model_history(model, start_date, end_date)
        _save_cache(name, data)
        return data, True
    except requests.RequestException as e:
        if cached is not None:
            print(f"features: {model} fetch failed, using stale cache ({e})", file=sys.stderr)
            return cached, False
        print(f"features: {model} history failed, skipping ({e})", file=sys.stderr)
        return None, False


def build_training_rows(start_date, end_date):
    """One row per (hour, member, variable) with truth + engineered features."""
    truth, truth_fresh = _truth_payload(start_date, end_date)
    truth_hourly = truth.get("hourly", {})
    times = truth_hourly.get("time", [])
    truth_by_var = {var: dict(zip(times, truth_hourly.get(var, []))) for var in TRAIN_VARS}
    allow_model_cache = not truth_fresh
    any_fresh = truth_fresh

    rows = []
    for model in OPEN_METEO_MODELS:
        data, fresh = _model_payload(model, start_date, end_date, allow_model_cache)
        any_fresh = any_fresh or fresh
        if not data:
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
    if any_fresh:
        _save_cache("meta.json", {
            "month": _cache_month(),
            "start_date": start_date,
            "end_date": end_date,
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


def wmo_to_icon(code):
    """WMO weather_code -> icon name per spec §7.5. Shared by blend.py
    (forecast blocks/days) and fetch_obs.py (zdaj icon)."""
    if code is None:
        return "cloud"
    code = int(code)
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 95 <= code <= 99:
        return "storm"
    return "cloud"
