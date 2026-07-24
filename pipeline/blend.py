"""Apply trained models (or the equal-weight-mean fallback) to today's member
forecasts and write site/forecast.json — the daily step in forecast.yml.
"""
import json
import math
import os
import pickle
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.dirname(__file__))
from backtest import feature_columns
from config import (
    ELEVATION, LAT, LON, OPEN_METEO_DAILY_VARS, OPEN_METEO_HOURLY_VARS,
    OPEN_METEO_MODELS, OPEN_METEO_URL, TIMEZONE,
)
from features import TRAIN_VARS, lead_bucket, wmo_to_icon

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MODELS_DIR = os.path.join(DATA_DIR, "models")
DECISIONS_PATH = os.path.join(DATA_DIR, "blend_decisions.json")
SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
FORECAST_PATH = os.path.join(SITE_DIR, "forecast.json")

BLOCK_LABELS = ["23-02", "02-05", "05-08", "08-11", "11-14", "14-17", "17-20", "20-23"]
# storm > snow > rain > fog > cloud > partly > sun (spec §7.2)
ICON_SEVERITY = ["sun", "partly", "cloud", "fog", "rain", "snow", "storm"]


def worst_icon(icons):
    icons = [i for i in icons if i]
    if not icons:
        return "cloud"
    return max(icons, key=lambda i: ICON_SEVERITY.index(i) if i in ICON_SEVERITY else 0)


def block_drops(precip_mm):
    if precip_mm >= 6:
        return 3
    if precip_mm >= 2:
        return 2
    if precip_mm >= 0.2:
        return 1
    return 0


def daily_drops(precip_mm):
    if precip_mm >= 15:
        return 3
    if precip_mm >= 5:
        return 2
    if precip_mm >= 1:
        return 1
    return 0


def fetch_open_meteo(now_dt):
    params = {
        "latitude": LAT, "longitude": LON, "elevation": ELEVATION,
        "timezone": TIMEZONE, "forecast_days": 10,
        "models": ",".join(OPEN_METEO_MODELS),
        "hourly": ",".join(OPEN_METEO_HOURLY_VARS),
        "daily": ",".join(OPEN_METEO_DAILY_VARS),
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def load_models():
    models = {}
    if not os.path.isdir(MODELS_DIR):
        return models
    for var in TRAIN_VARS:
        path = os.path.join(MODELS_DIR, f"{var}.pkl")
        if os.path.exists(path):
            with open(path, "rb") as f:
                models[var] = pickle.load(f)
    return models


def load_decisions():
    if not os.path.exists(DECISIONS_PATH):
        return {}
    with open(DECISIONS_PATH) as f:
        return json.load(f)


def ships_ml_blend(var, bucket, decisions):
    """Exact bucket match if one exists; otherwise fall back to the
    variable's only backtested signal ("unknown-horizon" — historical
    archives can't carry real lead-time, see features.py) rather than
    silently never using a model that's already proven to beat the mean."""
    exact = decisions.get(f"{var}|{bucket}")
    if exact is not None:
        return exact == "lightgbm_blend"
    return decisions.get(f"{var}|unknown-horizon") == "lightgbm_blend"


def blend_hourly(data, now_dt, models, decisions):
    """Returns {var: {time_str: value}} for each of our training variables,
    plus raw per-model series for anything not in TRAIN_VARS (weather_code,
    uv_index, precipitation_probability, cloud_cover — averaged as-is, no
    trained correction for these per spec §6's four regression targets)."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    out = {var: {} for var in OPEN_METEO_HOURLY_VARS}

    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t)
        lead_hours = round((dt - now_dt).total_seconds() / 3600)
        bucket = lead_bucket(lead_hours)
        hour_of_day = dt.hour
        doy = dt.timetuple().tm_yday
        doy_sin, doy_cos = math.sin(2 * math.pi * doy / 365), math.cos(2 * math.pi * doy / 365)

        for var in OPEN_METEO_HOURLY_VARS:
            member_values = {}
            for model_name in OPEN_METEO_MODELS:
                series = hourly.get(f"{var}_{model_name}")
                if series is not None and i < len(series) and series[i] is not None:
                    member_values[model_name] = series[i]
            if not member_values:
                continue

            if var in TRAIN_VARS and var in models and ships_ml_blend(var, bucket, decisions):
                bundle = models[var]
                row = {m: member_values.get(m) for m in OPEN_METEO_MODELS}
                row.update({f"{m}_avail": 1 if m in member_values else 0 for m in OPEN_METEO_MODELS})
                row.update({"lead_hours": lead_hours, "hour_of_day": hour_of_day,
                            "doy_sin": doy_sin, "doy_cos": doy_cos})
                import pandas as pd
                X = pd.DataFrame([row])[bundle["feature_columns"]].astype(float)
                value = float(bundle["model"].predict(X)[0])
            else:
                value = sum(member_values.values()) / len(member_values)

            out[var][t] = value
    return out


def build_blocks(blended, target_date):
    """Eight 3-hour blocks for target_date, starting the previous day at 23:00
    (the 23-02 block spans midnight, per spec §7.2). Built for every day so the
    frontend can show any day's hourly breakdown on tap."""
    blocks = []
    start = datetime.combine(target_date - timedelta(days=1), datetime.min.time()).replace(hour=23)
    for label in BLOCK_LABELS:
        end = start + timedelta(hours=3)
        hours_in_block = []
        for h in range(3):
            t = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
            hours_in_block.append(t)

        temps = [blended["temperature_2m"][t] for t in hours_in_block if t in blended["temperature_2m"]]
        rhs = [blended["relative_humidity_2m"][t] for t in hours_in_block if t in blended["relative_humidity_2m"]]
        winds = [(blended["wind_speed_10m"].get(t), blended["wind_direction_10m"].get(t)) for t in hours_in_block]
        winds = [(s, d) for s, d in winds if s is not None]
        precs = [blended["precipitation"][t] for t in hours_in_block if t in blended["precipitation"]]
        codes = [blended["weather_code"][t] for t in hours_in_block if t in blended["weather_code"]]
        uvs = [blended["uv_index"][t] for t in hours_in_block if t in blended["uv_index"]]
        pops = [blended["precipitation_probability"][t] for t in hours_in_block if t in blended["precipitation_probability"]]

        precip_sum = round(sum(precs), 1) if precs else 0.0
        wind_kmh, wind_dir = (max(winds, key=lambda x: x[0]) if winds else (None, None))

        block = {
            "start": start.replace(tzinfo=ZoneInfo(TIMEZONE)).isoformat(),
            "end": end.replace(tzinfo=ZoneInfo(TIMEZONE)).isoformat(),
            "label": label,
            "icon": worst_icon([wmo_to_icon(c) for c in codes]),
            "t": round(sum(temps) / len(temps)) if temps else None,
            "rh": round(sum(rhs) / len(rhs)) if rhs else None,
            "uv": round(max(uvs)) if uvs else 0,
            "wind_kmh": round(wind_kmh) if wind_kmh is not None else 0,
            "wind_dir": round(wind_dir) if wind_dir is not None else 0,
            "precip_mm": precip_sum,
            "drops": block_drops(precip_sum),
            "members_used": OPEN_METEO_MODELS,
        }
        if pops:
            block["pop"] = round(max(pops) / 5) * 5
        blocks.append(block)
        start = end
    return blocks


def build_days(data, blended):
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    days = []
    day_names = ["PON", "TOR", "SRE", "ČET", "PET", "SOB", "NED"]
    # 8 days = today + 7 ahead: the frontend puts today in the top row and shows
    # the 7 following days in the week row (today would be redundant there).
    for i, d in enumerate(dates[:8]):
        weekday = datetime.fromisoformat(d).weekday()
        t_am_key = f"{d}T10:00"
        t_pm_key = f"{d}T15:00"
        rh_pm_key = t_pm_key

        # Daily fields come back per-model-suffixed (like hourly) when multiple
        # models are requested — summing our already-blended hourly series is
        # simpler and more consistent than re-averaging six suffixed daily keys.
        precip_sum = sum(v for t, v in blended["precipitation"].items() if t.startswith(d))
        codes_today = [v for t, v in blended["weather_code"].items() if t.startswith(d)]
        winds_today = [(blended["wind_speed_10m"].get(t), blended["wind_direction_10m"].get(t))
                        for t in blended["wind_speed_10m"] if t.startswith(d)]
        winds_today = [(s, dd) for s, dd in winds_today if s is not None]
        wind_kmh, wind_dir = (max(winds_today, key=lambda x: x[0]) if winds_today else (0, 0))
        pops_today = [v for t, v in blended["precipitation_probability"].items() if t.startswith(d)]

        day = {
            "date": d, "name": day_names[weekday],
            "icon": worst_icon([wmo_to_icon(c) for c in codes_today]),
            "t_am": round(blended["temperature_2m"][t_am_key]) if t_am_key in blended["temperature_2m"] else None,
            "t_pm": round(blended["temperature_2m"][t_pm_key]) if t_pm_key in blended["temperature_2m"] else None,
            "rh_pm": round(blended["relative_humidity_2m"][rh_pm_key]) if rh_pm_key in blended["relative_humidity_2m"] else None,
            "uv_max": round(max((v for t, v in blended["uv_index"].items() if t.startswith(d)), default=0)),
            "wind_kmh": round(wind_kmh), "wind_dir": round(wind_dir),
            "precip_mm": round(precip_sum, 1),
            "drops": daily_drops(precip_sum),
        }
        if pops_today:
            day["pop"] = round(max(pops_today) / 5) * 5
        day["blocks"] = build_blocks(blended, datetime.fromisoformat(d).date())
        days.append(day)
    return days


def sun_times(data):
    """Sunrise/sunset are astronomical, not model-dependent — daily fields are
    still per-model-suffixed, so just take the first model that has them."""
    daily = data.get("daily", {})
    for model_name in OPEN_METEO_MODELS:
        sunrise = daily.get(f"sunrise_{model_name}")
        sunset = daily.get(f"sunset_{model_name}")
        if sunrise and sunset:
            return {"sunrise": sunrise[0][-5:], "sunset": sunset[0][-5:]}
    return {"sunrise": None, "sunset": None}


def main():
    tz = ZoneInfo(TIMEZONE)
    now_dt = datetime.now(tz).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    today = now_dt.date()

    data = fetch_open_meteo(now_dt)
    models = load_models()
    decisions = load_decisions()
    blended = blend_hourly(data, now_dt, models, decisions)

    days = build_days(data, blended)
    forecast = {
        "generated_at": datetime.now(tz).isoformat(),
        "coords": {"lat": LAT, "lon": LON, "elev": ELEVATION},
        "sun": sun_times(data),
        # Top-level blocks mirror today's, kept for the now.json icon/UV fallback
        # and app.js's forecast-block fallback; per-day blocks live in days[].
        "blocks": days[0]["blocks"] if days else [],
        "days": days,
        "stale_after_hours": 24,
    }

    os.makedirs(SITE_DIR, exist_ok=True)
    with open(FORECAST_PATH, "w") as f:
        json.dump(forecast, f, indent=2, ensure_ascii=False)
    print(f"blend: wrote {FORECAST_PATH}")


if __name__ == "__main__":
    main()
