"""Fetch station observations, log them for training, and compute "zdaj".

ARSO's observation archive requires a login (verified), so unlike the spec's
literal "pull yesterday's obs once daily" plan, this script logs every run's
readings (called every 30 min by now.yml) to data/log_obs.csv — finer-grained
than a daily backfill would have been, and needs no credentials.

FVG stations are logged for training only, never surfaced in now.json/zdaj —
their feed carries a 24h no-republish clause on real-time data.
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    ARSO_OBS_URL_TEMPLATE, ARSO_STATION_BILJE, ARSO_STATION_NOVA_GORICA,
    ELEVATION, FVG_OBS_URL_TEMPLATE, FVG_STATION_CAPRIVA, FVG_STATION_CORMONS,
    LAT, LON, OPEN_METEO_URL, TIMEZONE,
)
from features import wmo_to_icon
from safe_write import write_json

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
LOG_PATH = os.path.join(DATA_DIR, "log_obs.csv")
NOW_PATH = os.path.join(SITE_DIR, "now.json")
FORECAST_PATH = os.path.join(SITE_DIR, "forecast.json")
CSV_FIELDS = ["obs_time", "station", "network", "variable", "value"]

# ARSO actually publishes within ~10 minutes (measured: 20:39 local, newest
# reading valid 20:30). An earlier note here claimed a ~2h10m lag and loosened
# this to 150 min — that "lag" was really the UTC/CEST offset introduced by the
# astimezone bug above, and the loose threshold then hid genuinely stale data.
# Back to the spec's §4.2 value, with a little headroom for a slow publish.
STALE_MINUTES = 60
SANITY_BOUNDS = {
    "temperature_2m": (-25, 45), "relative_humidity_2m": (1, 100),
    "wind_speed_10m": (0, 180),
}


def append_log(rows):
    if not rows:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    is_new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def fetch_arso_stations(now_dt):
    """ARSO publishes all stations in one JSON per 10-min bucket. The filenames
    are UTC-stamped, so the search must start from UTC — starting from Ljubljana
    wall-clock spent the first ~12 probes on buckets that cannot exist yet
    (and made the feed look ~2h behind when it is really ~10 min behind)."""
    now_utc = datetime.now(timezone.utc)
    base = now_utc.replace(second=0, microsecond=0) - timedelta(minutes=now_utc.minute % 10)
    data = None
    for steps_back in range(12):  # 2h of genuine tolerance; real lag is ~10 min
        bucket = base - timedelta(minutes=10 * steps_back)
        url = ARSO_OBS_URL_TEMPLATE.format(timestamp=bucket.strftime("%Y%m%d-%H%M"))
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as e:
            print(f"arso obs: request failed ({e})", file=sys.stderr)
    if data is None:
        print("arso obs: no bucket found in the last 2 hours", file=sys.stderr)
        return {}

    wanted = {ARSO_STATION_BILJE: "BILJE", ARSO_STATION_NOVA_GORICA: "NOVA_GORICA"}
    out = {}
    for feature in data.get("features", []):
        props = feature["properties"]
        code = props.get("station")
        if code not in wanted:
            continue
        days = props.get("days", [])
        if not days or not days[0].get("timeline"):
            continue
        entry = days[0]["timeline"][0]
        # now_dt is naive, so its tzinfo is None — and .astimezone(None) converts
        # to the SYSTEM timezone, which is UTC on the GitHub runner. That silently
        # recorded every observation 2h early in production while looking correct
        # on a machine already set to Ljubljana. Convert explicitly.
        obs_time = (datetime.fromisoformat(entry["valid"])
                    .astimezone(ZoneInfo(TIMEZONE)).replace(tzinfo=None))
        out[wanted[code]] = {
            "obs_time": obs_time,
            "temperature_2m": _to_float(entry.get("t")),
            "relative_humidity_2m": _to_float(entry.get("rh")),
            "wind_speed_10m": _to_float(entry.get("ff_val")),
            "wind_direction_10m": _to_float(entry.get("dd_val")),
        }
    return out


def fetch_fvg_stations():
    wanted = {FVG_STATION_CAPRIVA: "CAPRIVA", FVG_STATION_CORMONS: "CORMONS"}
    out = {}
    for code, name in wanted.items():
        try:
            resp = requests.get(FVG_OBS_URL_TEMPLATE.format(code=code), timeout=20)
            resp.raise_for_status()
            xml = resp.text
        except requests.RequestException as e:
            print(f"fvg obs {code}: request failed ({e})", file=sys.stderr)
            continue
        obs_time_m = re_search(r"<observation_time>([^<]+)</observation_time>", xml)
        t_m = re_search(r'<t180[^>]*>([^<]+)</t180>', xml)
        v_m = re_search(r'<v10[^>]*>([^<]+)</v10>', xml)
        if not obs_time_m:
            continue
        try:
            # The field is explicitly labelled UTC; parsing it naive put FVG rows
            # on a different clock from the ARSO rows in the same log column.
            obs_time = (datetime.strptime(obs_time_m, "%d/%m/%Y %H.%M UTC")
                        .replace(tzinfo=timezone.utc)
                        .astimezone(ZoneInfo(TIMEZONE)).replace(tzinfo=None))
        except ValueError:
            continue
        out[name] = {
            "obs_time": obs_time,
            "temperature_2m": _to_float(t_m),
            "wind_speed_10m": _to_float(v_m),
        }
    return out


def re_search(pattern, text):
    import re
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def build_log_rows(now_dt, arso, fvg):
    rows = []
    for station, network, readings in (
        [(k, "arso", v) for k, v in arso.items()] + [(k, "fvg", v) for k, v in fvg.items()]
    ):
        obs_time = readings["obs_time"].isoformat()
        for var, value in readings.items():
            if var == "obs_time" or value is None:
                continue
            rows.append({"obs_time": obs_time, "station": station,
                         "network": network, "variable": var, "value": value})
    return rows


def compute_zdaj(now_dt, arso):
    """Staleness + sanity-bounded median across ARSO stations only (§4.2)."""
    fresh = {}
    for station, readings in arso.items():
        age_min = (now_dt - readings["obs_time"]).total_seconds() / 60
        if age_min > STALE_MINUTES:
            continue
        fresh[station] = readings

    result = {}
    for var, bounds in SANITY_BOUNDS.items():
        values = [r[var] for r in fresh.values() if r.get(var) is not None]
        values = [v for v in values if bounds[0] <= v <= bounds[1]]
        if values:
            result[var] = round(median(values), 1)

    # Direction is circular — a plain median is meaningless (median of 350°/10°
    # isn't 180°) — take it from whichever fresh station reported most recently.
    freshest = sorted(fresh.values(), key=lambda r: r["obs_time"], reverse=True)
    for r in freshest:
        if r.get("wind_direction_10m") is not None:
            result["wind_direction_10m"] = r["wind_direction_10m"]
            break

    latest_obs_time = freshest[0]["obs_time"] if freshest else None
    return result, list(fresh.keys()), latest_obs_time


def fetch_model_hourly(now_dt):
    """Small Open-Meteo call used two ways: (a) lag-correcting stale station
    readings — ARSO publishes ~2h behind, which during a fast morning warm-up
    made zdaj show 16° while it was really 21° — and (b) the zdaj icon/UV,
    so those no longer depend on forecast.json being fresh."""
    params = {
        "latitude": LAT, "longitude": LON, "elevation": ELEVATION,
        "timezone": TIMEZONE, "past_days": 1, "forecast_days": 1,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,uv_index",
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json().get("hourly")
    except (requests.RequestException, ValueError) as e:
        print(f"model hourly: request failed ({e})", file=sys.stderr)
        return None


def _model_at(hourly, var, dt):
    key = dt.strftime("%Y-%m-%dT%H:00")
    times = hourly.get("time", [])
    try:
        i = times.index(key)
    except ValueError:
        return None
    series = hourly.get(var)
    return series[i] if series and i < len(series) and series[i] is not None else None


def apply_lag_correction(zdaj, obs_time, now_dt, hourly):
    """Advance a stale station reading along the model's own hour-to-hour
    slope: corrected = measured + (model[now] - model[obs_hour]). The delta is
    capped so a model glitch can't swing the display wildly."""
    if hourly is None or obs_time is None:
        return zdaj
    for var, cap in (("temperature_2m", 6.0), ("relative_humidity_2m", 25.0)):
        if var not in zdaj:
            continue
        m_now = _model_at(hourly, var, now_dt)
        m_obs = _model_at(hourly, var, obs_time)
        if m_now is None or m_obs is None:
            continue
        delta = max(-cap, min(cap, m_now - m_obs))
        zdaj[var] = round(zdaj[var] + delta, 1)
    if "relative_humidity_2m" in zdaj:
        zdaj["relative_humidity_2m"] = min(100.0, max(1.0, zdaj["relative_humidity_2m"]))
    return zdaj


def current_hour_icon_uv(now_dt):
    """Borrow icon/uv from the blended forecast — stations don't report either."""
    try:
        with open(FORECAST_PATH) as f:
            forecast = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return "cloud", 0
    for block in forecast.get("blocks", []):
        start = datetime.fromisoformat(block["start"]).replace(tzinfo=None)
        end = datetime.fromisoformat(block["end"]).replace(tzinfo=None)
        if start <= now_dt < end:
            return block.get("icon", "cloud"), block.get("uv", 0)
    return "cloud", 0


def write_now_json(now_dt, zdaj, stations_used, hourly=None):
    icon, uv = None, None
    if hourly is not None:
        code = _model_at(hourly, "weather_code", now_dt)
        model_uv = _model_at(hourly, "uv_index", now_dt)
        if code is not None:
            icon = wmo_to_icon(code)
        if model_uv is not None:
            uv = round(model_uv)
    if icon is None or uv is None:
        fb_icon, fb_uv = current_hour_icon_uv(now_dt)
        icon = icon if icon is not None else fb_icon
        uv = uv if uv is not None else fb_uv
    payload = {
        "measured_at": now_dt.isoformat(),
        "t": zdaj.get("temperature_2m"),
        "rh": zdaj.get("relative_humidity_2m"),
        "wind_kmh": zdaj.get("wind_speed_10m"),
        "wind_dir": zdaj.get("wind_direction_10m"),
        "icon": icon, "uv": uv,
        "source": "stations" if stations_used else "model_fallback",
        "stations_used": stations_used,
        "hail": {"status": "none"},  # fetch_hail.py updates this key afterward
    }
    os.makedirs(SITE_DIR, exist_ok=True)
    write_json(NOW_PATH, payload, indent=2)


def main():
    latest = "--latest" in sys.argv
    tz = ZoneInfo(TIMEZONE)
    now_dt = datetime.now(tz).replace(second=0, microsecond=0, tzinfo=None)

    arso = fetch_arso_stations(now_dt)
    fvg = fetch_fvg_stations()
    append_log(build_log_rows(now_dt, arso, fvg))

    if latest:
        zdaj, stations_used, latest_obs_time = compute_zdaj(now_dt, arso)
        hourly = fetch_model_hourly(now_dt)
        zdaj = apply_lag_correction(zdaj, latest_obs_time, now_dt, hourly)
        write_now_json(now_dt, zdaj, stations_used, hourly)
        print(f"zdaj: {zdaj} from {stations_used} (obs {latest_obs_time})")

    print(f"logged {len(arso)} ARSO + {len(fvg)} FVG station readings")


if __name__ == "__main__":
    main()
