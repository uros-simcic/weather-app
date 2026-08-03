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
    WU_PWS_NAME, WU_PWS_STATION, WU_PWS_URL, WU_PWS_WEB_KEY,
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
            # Rain, collected but not yet used anywhere — see the note in
            # build_log_rows. ARSO publishes tp_acc over the interval named in
            # the same entry (always 10 min so far) and a rolling 12h total;
            # tp_1h_acc and tp_24h_acc exist in the schema but come back empty.
            # tp_acc is only recorded when the interval really is 10 minutes,
            # so the variable name can never be a lie about the window.
            "precipitation_10min": (_to_precip(entry.get("tp_acc"))
                                    if str(entry.get("interval", "")).strip() == "10" else None),
            "precipitation_12h": _to_precip(entry.get("tp_12h_acc")),
        }
    return out


def fetch_vipolze():
    """The Vipolže personal weather station, the only one inside Brda.

    Joins the ARSO pair in the zdaj median for temperature and humidity. It
    reports no usable wind and UV comes back null, so those stay ARSO-only.
    Its rain gauge is logged but not yet used anywhere. Any failure returns
    nothing rather than a partial reading, never guessed (§7.10).
    """
    try:
        resp = requests.get(WU_PWS_URL, params={
            "stationId": WU_PWS_STATION, "format": "json",
            "units": "m", "apiKey": WU_PWS_WEB_KEY,
        }, timeout=20)
        resp.raise_for_status()
        observations = resp.json().get("observations") or []
    except (requests.RequestException, ValueError) as e:
        print(f"vipolze: request failed, skipping ({e})", file=sys.stderr)
        return {}
    if not observations:
        print("vipolze: no observation returned", file=sys.stderr)
        return {}

    obs = observations[0]
    # -1 is WU's "failed quality control"; 0 is "not checked", which is normal
    # for a station that reports rarely, so only -1 is rejected.
    if obs.get("qcStatus") == -1:
        print("vipolze: reading failed WU quality control, skipping", file=sys.stderr)
        return {}
    epoch = obs.get("epoch")
    if epoch is None:
        return {}
    # From the epoch rather than obsTimeLocal, so the clock matches the naive
    # Ljubljana wall time every other station in this file is keyed on without
    # trusting a preformatted string.
    obs_time = (datetime.fromtimestamp(epoch, ZoneInfo(TIMEZONE))
                .replace(tzinfo=None, second=0, microsecond=0))
    metric = obs.get("metric") or {}
    readings = {
        "obs_time": obs_time,
        "temperature_2m": metric.get("temp"),
        "relative_humidity_2m": obs.get("humidity"),
        # Rain, collected but not yet used. This is the only gauge inside Brda,
        # and rain is the most local of all the variables — the valley stations
        # can be dry while the hills are not. precipRate is an instantaneous
        # mm/h, precipTotal the running total since local midnight; they are
        # different quantities from ARSO's accumulations and from each other,
        # so each keeps its own name rather than being folded together.
        "precipitation_rate": _to_precip(metric.get("precipRate")),
        "precipitation_today": _to_precip(metric.get("precipTotal")),
    }
    if readings["temperature_2m"] is None and readings["relative_humidity_2m"] is None:
        return {}
    return {WU_PWS_NAME: readings}


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


# No gauge anywhere reports negative rain, and nothing near Brda has ever put
# this much down in one reading. A tipping bucket that has iced up or lost its
# zero reports either, so both are dropped rather than logged — a wrong number
# in the archive is worse than a missing one, because a correction fitted later
# cannot tell them apart.
MAX_PRECIP_MM = 200.0


def _to_precip(v):
    value = _to_float(v)
    if value is None or value < 0 or value > MAX_PRECIP_MM:
        return None
    return value


def build_log_rows(now_dt, arso, fvg, pws=None):
    """Every reading a station gave us, one row per variable.

    Includes the rain variables, which nothing reads yet. Rain is what the
    forecast is mostly consulted for and the one variable no correction can ever
    be fitted for without an archive of what actually fell — so the archive has
    to start accumulating before it can be useful, not after someone decides to
    use it. They are deliberately kept under distinct names
    (precipitation_10min, precipitation_12h, precipitation_rate,
    precipitation_today) rather than one shared "precipitation": they are four
    different quantities over four different windows, and collapsing them would
    make the archive unusable for exactly the analysis it exists for.
    """
    rows = []
    # Logged under its own network name, not "arso": verify.py scores against
    # arso rows only, and quietly folding a personal station into the official
    # ground truth would change what every past number was measured against.
    for station, network, readings in (
        [(k, "arso", v) for k, v in arso.items()]
        + [(k, "fvg", v) for k, v in fvg.items()]
        + [(k, "wu", v) for k, v in (pws or {}).items()]
    ):
        obs_time = readings["obs_time"].isoformat()
        for var, value in readings.items():
            if var == "obs_time" or value is None:
                continue
            rows.append({"obs_time": obs_time, "station": station,
                         "network": network, "variable": var, "value": value})
    return rows


def compute_zdaj(now_dt, stations):
    """Staleness + sanity-bounded median across Bilje, Nova Gorica and Vipolže.

    Vipolže is the only one inside Brda; the ARSO pair are 9-14km away in the
    valley. It reports no wind, and a variable a station does not report is
    skipped below, so wind stays an ARSO figure on its own.
    """
    fresh = {}
    for station, readings in stations.items():
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
        # Published with its UTC offset, the way blend.py writes generated_at.
        # It used to go out naive and app.js pinned "+02:00" onto it to parse
        # it, which is right only in CEST — after the October change that reads
        # every measurement as an hour older than it is, and since anything over
        # 120 min is rejected, now.json would be thrown away from ~61 min old
        # and the page would quietly show a forecast block as if it were a
        # station reading. now_dt stays naive everywhere else: the rest of this
        # file does arithmetic against other naive datetimes.
        "measured_at": now_dt.replace(tzinfo=ZoneInfo(TIMEZONE)).isoformat(),
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
    pws = fetch_vipolze()
    append_log(build_log_rows(now_dt, arso, fvg, pws))

    if latest:
        # FVG stays out of the live figure: its feed carries a 24h no-republish
        # clause, so it is training and backtest only.
        zdaj, stations_used, latest_obs_time = compute_zdaj(now_dt, {**arso, **pws})
        hourly = fetch_model_hourly(now_dt)
        zdaj = apply_lag_correction(zdaj, latest_obs_time, now_dt, hourly)
        write_now_json(now_dt, zdaj, stations_used, hourly)
        print(f"zdaj: {zdaj} from {stations_used} (obs {latest_obs_time})")

    print(f"logged {len(arso)} ARSO + {len(fvg)} FVG + {len(pws)} PWS station readings")


if __name__ == "__main__":
    main()
