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

# The LightGBM blend was trained with most members present. Beyond ~5 days only
# the two global models (ECMWF, GFS) reach that far; with the other four missing
# the tree collapses to a ~climatology mean far below the two real members
# (verified: models said 34-40°C at 6-7d, blend output 28-29). Below this many
# members, ship the equal-weight mean instead — it stays anchored to real data.
MIN_MEMBERS_FOR_ML = 3

# Rain probability is never certain, so it is never displayed as 99 or 100.
# On 2026-07-26 all six models forecast 7-28 mm and both probability-carrying
# members said 98-100%; the stations measured 0.0 mm under a sunny sky. A
# summer convective bust like that is ordinary meteorology — claiming certainty
# about it is not. Note also that only ECMWF and GFS publish a probability at
# all; the four high-resolution regional models return null, so this number
# comes from the two coarsest members exactly when terrain matters most.
MAX_POP = 95


# The frontend only renders a probability at >= 30% (spec §7.5). Apply that gate
# to the raw value here rather than after rounding, otherwise a blended 28%
# rounded up to 30 and got displayed — a sub-threshold number, shown higher than
# any model produced.
MIN_POP_SHOWN = 30


def display_pop(values):
    """Round to the nearest 5 and cap, so the UI can never promise certainty.
    Returns None below the display threshold so the key is simply absent."""
    if not values:
        return None
    raw = max(values)
    if raw < MIN_POP_SHOWN:
        return None
    return min(MAX_POP, round(raw / 5) * 5)


# A member is counted as forecasting rain at or above this hourly amount.
POP_WET_MM = 0.1


def combine_pop(stated, precip_members):
    """Probability of precipitation from ALL members, not just the two that
    publish one.

    Only ECMWF and GFS supply precipitation_probability; the four
    high-resolution regional models (ICON-D2, ICON-2I, ICON-EU, AROME) return
    null. Averaging just the two meant that on a convective summer day — when
    the regional models are the ones actually resolving the terrain — the
    figure came from the two coarse global models alone, and both saying ~100%
    produced a certain-looking forecast that then did not happen.

    Every member does supply an hourly amount, so the share of members
    forecasting measurable rain is a genuine ensemble probability. Averaging
    that with the stated probability keeps the calibrated signal while letting
    the regional models pull it down when they disagree.
    """
    values = list(stated.values())
    said = sum(values) / len(values) if values else None
    if not precip_members:
        return said if said is not None else 0.0
    wet = sum(1 for v in precip_members.values() if v >= POP_WET_MM)
    agreement = 100.0 * wet / len(precip_members)
    if said is None:
        return agreement
    return (said + agreement) / 2


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
    # Retry on transient timeouts: this single call is the whole forecast, so
    # one blip must not fail the daily run and leave forecast.json stale.
    last_error = None
    for timeout in (30, 60, 90):
        try:
            resp = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
            print(f"open-meteo: attempt failed ({e})", file=sys.stderr)
    raise last_error


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


def chosen_method(var, bucket, decisions):
    """Which blend method the backtest picked for this variable x lead bucket.
    Exact bucket match if one exists; otherwise the variable's only backtested
    signal ("unknown-horizon" — historical archives can't carry real lead-time,
    see features.py). Defaults to the plain mean when nothing is recorded."""
    exact = decisions.get(f"{var}|{bucket}")
    if isinstance(exact, str):
        return exact
    fallback = decisions.get(f"{var}|unknown-horizon")
    return fallback if isinstance(fallback, str) else "equal_weight_mean"


def weighted_mean(member_values, maes, power):
    """Skill-weighted ensemble mean: weight ∝ (1/MAE)^power, using the same
    per-member MAEs the backtest chose this method with."""
    num = den = 0.0
    for m, v in member_values.items():
        skill = maes.get(m)
        if skill:
            w = (1.0 / skill) ** power
            num += w * v
            den += w
    if not den:  # no member has a recorded skill score — fall back to plain mean
        return sum(member_values.values()) / len(member_values)
    return num / den


def blended_daily_extreme(data, var, d, agg, decisions):
    """A day's min or max taken per member first, then blended — rather than
    read off the blended curve.

    An average never reaches as far as the things it averages: blend six models
    hour by hour and the resulting curve peaks below where the members' own
    peaks average out, and bottoms out above their own troughs. Reading the
    extreme off that curve therefore published a day narrower than the ensemble
    actually said. Measured against the live response: 0.05-0.90 °C on the
    overnight minimum, and 0.5-3.2 km/h on wind — enough to change the printed
    wind figure on six days out of eight, always downwards, in a number the day
    row presents as the windiest it will get.

    Members are read from each model's own hourly series rather than from the
    API's daily aggregate. Open-Meteo nulls a model's daily value on its final,
    partial day while still publishing that day's hours, so the two are taken
    over different member sets on exactly the far-out days this matters most —
    and the correction then comes out backwards. Going through the hourly
    series keeps the member set identical to the blend's own.

    Weighted by the same per-member skill scores the hourly path falls back to;
    variables the backtest never scored have no MAEs and fall to a plain mean.
    """
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    per_member = {}
    for model_name in OPEN_METEO_MODELS:
        series = hourly.get(f"{var}_{model_name}")
        if series is None:
            continue
        vals = [series[i] for i, t in enumerate(times)
                if t.startswith(d) and i < len(series) and series[i] is not None]
        if vals:
            per_member[model_name] = agg(vals)
    if not per_member:
        return None
    return weighted_mean(per_member, decisions.get(f"{var}|member_mae") or {}, 2)


def combine_weather_codes(member_values):
    """WMO codes are categories, not quantities — averaging them invents weather.
    Two members both forecasting rain (63 and 81) average to 72, which is a snow
    code; rain 61 with storm 95 averages to 78 and renders as a plain cloud,
    hiding the storm. So map each member to its icon, take the majority icon
    (ties broken by severity), and return a real code from the winning group."""
    by_icon = {}
    for code in member_values.values():
        by_icon.setdefault(wmo_to_icon(code), []).append(code)
    winner = max(by_icon, key=lambda ic: (len(by_icon[ic]), ICON_SEVERITY.index(ic)))
    # Most severe actual code among the members that agreed on this icon.
    return max(by_icon[winner], key=lambda c: ICON_SEVERITY.index(wmo_to_icon(c)))


def circular_mean_deg(values):
    """Wind direction wraps at 360: a plain mean of 350 and 10 gives 180, the
    exact opposite heading. Average the unit vectors instead."""
    x = sum(math.cos(math.radians(v)) for v in values)
    y = sum(math.sin(math.radians(v)) for v in values)
    if abs(x) < 1e-9 and abs(y) < 1e-9:  # directions cancel out entirely
        return values[0]
    return math.degrees(math.atan2(y, x)) % 360


def blend_hourly(data, now_dt, models, decisions):
    """Returns {var: {time_str: value}} for each of our training variables,
    plus raw per-model series for anything not in TRAIN_VARS (uv_index,
    precipitation_probability, cloud_cover — averaged as-is, no trained
    correction for these per spec §6's four regression targets).

    weather_code and wind_direction_10m are combined by category/angle rather
    than averaged — see the two helpers above."""
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

            # Non-numeric combines first: these must never go through a mean.
            if var == "weather_code":
                out[var][t] = combine_weather_codes(member_values)
                continue
            if var == "wind_direction_10m":
                out[var][t] = circular_mean_deg(list(member_values.values()))
                continue
            if var == "precipitation_probability":
                precip_members = {}
                for model_name in OPEN_METEO_MODELS:
                    s = hourly.get(f"precipitation_{model_name}")
                    if s is not None and i < len(s) and s[i] is not None:
                        precip_members[model_name] = s[i]
                out[var][t] = combine_pop(member_values, precip_members)
                continue

            method = chosen_method(var, bucket, decisions) if var in TRAIN_VARS else "equal_weight_mean"
            maes = decisions.get(f"{var}|member_mae") or {}

            use_ml = (method == "lightgbm_blend" and var in models
                      and len(member_values) >= MIN_MEMBERS_FOR_ML)
            if use_ml:
                bundle = models[var]
                row = {m: member_values.get(m) for m in OPEN_METEO_MODELS}
                row.update({f"{m}_avail": 1 if m in member_values else 0 for m in OPEN_METEO_MODELS})
                row.update({"lead_hours": lead_hours, "hour_of_day": hour_of_day,
                            "doy_sin": doy_sin, "doy_cos": doy_cos})
                import pandas as pd
                X = pd.DataFrame([row])[bundle["feature_columns"]].astype(float)
                value = float(bundle["model"].predict(X)[0])
                # A regressor has no notion of "rain cannot be negative": dry
                # hours accumulated small negative values that subtracted from
                # the daily total, enough to push 1.05 mm to 0.95 and flip the
                # day from one drop to none.
                if var == "precipitation":
                    value = max(0.0, value)
            elif method.startswith("weighted_mean_p") and maes:
                value = weighted_mean(member_values, maes, int(method[-1]))
            elif method == "lightgbm_blend" and maes:
                # ML was chosen but can't run here (too few members, or model
                # file missing) — prefer the skill-weighted mean over the plain
                # one; it beat equal weight on holdout for every variable that
                # picked ML in the first place.
                value = weighted_mean(member_values, maes, 2)
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
        block_pop = display_pop(pops)
        if block_pop is not None:
            block["pop"] = block_pop
        blocks.append(block)
        start = end
    return blocks


def build_days(data, blended, decisions):
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    days = []
    day_names = ["PON", "TOR", "SRE", "ČET", "PET", "SOB", "NED"]
    # 8 days = today + 7 ahead: the frontend puts today in the top row and shows
    # the 7 following days in the week row (today would be redundant there).
    for i, d in enumerate(dates[:8]):
        weekday = datetime.fromisoformat(d).weekday()
        rh_pm_key = f"{d}T15:00"

        # Icon / rain% / precip summarise the DAYTIME (06:00-20:59) only. Using
        # all 24h let a pre-dawn shower that's gone by sunrise flip the whole day
        # to "rain" at a high pop, contradicting an otherwise-sunny hourly view.
        # Wind stays whole-day: it answers "windiest it gets", not "how's the day".
        def daytime(series):
            return [v for t, v in series.items()
                    if t.startswith(d) and 6 <= int(t[11:13]) < 21]

        precip_sum = sum(daytime(blended["precipitation"]))
        codes_day = daytime(blended["weather_code"])
        pops_day = daytime(blended["precipitation_probability"])

        winds_today = [(blended["wind_speed_10m"].get(t), blended["wind_direction_10m"].get(t))
                        for t in blended["wind_speed_10m"] if t.startswith(d)]
        winds_today = [(s, dd) for s, dd in winds_today if s is not None]
        wind_peak, wind_dir = (max(winds_today, key=lambda x: x[0]) if winds_today else (0, 0))

        # Daily min/max over the whole calendar day, not fixed 10:00/15:00
        # readings: every reference forecast (ARSO, meteo.it) publishes min/max,
        # and a 10:00 value read ~10°C warmer than ARSO's overnight minimum,
        # making the two impossible to compare.
        temps_all = [v for t, v in blended["temperature_2m"].items() if t.startswith(d)]
        uv_all = [v for t, v in blended["uv_index"].items() if t.startswith(d)]

        # Blended per member (see blended_daily_extreme), then held to the curve
        # the blocks are drawn from. The two agree on the ensemble mean, but the
        # nearer days blend through LightGBM, which is not an average of its
        # members and so carries no guarantee of sitting inside them — without
        # this a day could print a peak below one of its own blocks.
        t_am = blended_daily_extreme(data, "temperature_2m", d, min, decisions)
        t_pm = blended_daily_extreme(data, "temperature_2m", d, max, decisions)
        uv_max = blended_daily_extreme(data, "uv_index", d, max, decisions)
        wind_kmh = blended_daily_extreme(data, "wind_speed_10m", d, max, decisions)
        if temps_all:
            t_am = min(t_am, min(temps_all)) if t_am is not None else min(temps_all)
            t_pm = max(t_pm, max(temps_all)) if t_pm is not None else max(temps_all)
        if uv_all:
            uv_max = max(uv_max, max(uv_all)) if uv_max is not None else max(uv_all)
        wind_kmh = max(wind_kmh, wind_peak) if wind_kmh is not None else wind_peak

        day = {
            "date": d, "name": day_names[weekday],
            "icon": worst_icon([wmo_to_icon(c) for c in codes_day]),
            "t_am": round(t_am) if t_am is not None else None,
            "t_pm": round(t_pm) if t_pm is not None else None,
            "rh_pm": round(blended["relative_humidity_2m"][rh_pm_key]) if rh_pm_key in blended["relative_humidity_2m"] else None,
            "uv_max": round(uv_max or 0),
            "wind_kmh": round(wind_kmh), "wind_dir": round(wind_dir),
            # Drops from the SAME rounded figure that gets published, or the two
            # disagree at every threshold: 0.96 mm publishes as "1.0 mm" while
            # daily_drops(0.96) returns 0, so the day reads as a millimetre of
            # rain with no drop against it. The block path already rounds first.
            "precip_mm": round(precip_sum, 1),
            "drops": daily_drops(round(precip_sum, 1)),
        }
        day_pop = display_pop(pops_day)
        if day_pop is not None:
            day["pop"] = day_pop
        day["blocks"] = build_blocks(blended, datetime.fromisoformat(d).date())
        days.append(day)
    return days


def log_published(blended, now_dt):
    """Append our own published hourly values to data/log_published.csv.

    We logged every model member's input but never our own output, so there was
    no way to score ourselves after the fact. verify.py reads this back against
    real station readings."""
    import csv
    path = os.path.join(DATA_DIR, "log_published.csv")
    fields = ["run_time", "valid_time", "variable", "value"]
    run_time = now_dt.isoformat()

    rows = []
    for var in ("temperature_2m", "relative_humidity_2m", "wind_speed_10m"):
        for t, value in blended.get(var, {}).items():
            # Only the next 48h: beyond that the row is superseded by a later
            # run before it can ever be verified.
            valid = datetime.fromisoformat(t)
            if 0 <= (valid - now_dt).total_seconds() <= 48 * 3600:
                rows.append({"run_time": run_time, "valid_time": t,
                             "variable": var, "value": round(value, 2)})
    if not rows:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            w.writeheader()
        w.writerows(rows)
    print(f"blend: logged {len(rows)} published values for verification")


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

    log_published(blended, now_dt)

    days = build_days(data, blended, decisions)
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
