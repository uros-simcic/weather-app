"""Fetch all forecast model members for the current run and log their values.

Appends one row per (member, lead_hours, variable) to data/log_forecasts.csv,
long-format so backtest.py/train.py can pivot as needed. A member that errors
or omits a variable is skipped for that run — never guessed (spec §4.1/§7.10).
"""
import csv
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    ARSO_FORECAST_TOWN, ARSO_FORECAST_URL, FVG_FORECAST_URL_TEMPLATE,
    LAT, LON, ELEVATION, TIMEZONE, OPEN_METEO_MODELS, OPEN_METEO_DAILY_VARS,
    OPEN_METEO_HOURLY_VARS, OPEN_METEO_URL, PRO_VREME_URL, PRO_VREME_USER_AGENT,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LOG_PATH = os.path.join(DATA_DIR, "log_forecasts.csv")
CSV_FIELDS = ["run_time", "member", "lead_hours", "variable", "value"]

# ARSO field -> our canonical variable name
ARSO_VAR_MAP = {
    "t": "temperature_2m", "rh": "relative_humidity_2m",
    "ff_val": "wind_speed_10m", "dd_val": "wind_direction_10m",
    "tp_acc": "precipitation",
}

# Pro-vreme's Slovenian row labels -> our canonical variable name (day columns only)
PRO_VREME_ROW_MAP = {
    "Temperatura popoldne:": "temperature_2m_pm",
    "Hitrost vetra:": "wind_speed_10m",
    "Smer vetra:": "wind_direction_10m",
    "Padavine:": "precipitation",
}


# How much of the log to keep. It is committed to the repo on every run, and
# every run adds ~6,700 rows / ~390 KB, so left alone it grows about 1.6 MB a
# day — it was on course to cross GitHub's hard 100 MB push limit around
# September 2026, at which point every push fails, the retry loop exhausts, and
# the page silently freezes on its last forecast.
#
# 30 days is roughly 47 MB, which is the most that is reasonable to carry in a
# repo GitHub Pages serves and CI checks out four times a day. Note that this
# is far short of the 13 months train.py would want for live-row training: if
# that is ever wired up (load_live_rows is currently defined but never called),
# the way to buy history is to log fewer leads per run rather than to raise
# this number.
LOG_RETENTION_DAYS = 30


def append_rows(rows):
    if not rows:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    is_new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
    trim_log()


def trim_log():
    """Drop rows older than the retention window.

    Written to a temp file and renamed rather than rewritten in place: this
    runs right after the append, so a crash part way through an in-place
    rewrite would take the freshly logged run down with the old rows.
    """
    if not os.path.exists(LOG_PATH):
        return
    cutoff = (datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
              - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
    tmp = LOG_PATH + ".tmp"
    kept = dropped = 0
    try:
        with open(LOG_PATH, newline="") as src, open(tmp, "w", newline="") as dst:
            reader = csv.reader(src)
            writer = csv.writer(dst)
            header = next(reader, None)
            if header is None:
                os.remove(tmp)
                return
            writer.writerow(header)
            for row in reader:
                # ISO timestamps compare correctly as strings at fixed width;
                # a malformed or empty run_time is kept rather than silently
                # discarded, so a parse bug can never eat the archive.
                if row and row[0] and row[0] < cutoff:
                    dropped += 1
                    continue
                writer.writerow(row)
                kept += 1
        os.replace(tmp, LOG_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    size_mb = os.path.getsize(LOG_PATH) / 1e6
    print(f"log_forecasts: kept {kept} rows, dropped {dropped} older than "
          f"{LOG_RETENTION_DAYS}d ({size_mb:.1f} MB)")


def fetch_open_meteo(run_time, run_dt):
    """One request covers all six Open-Meteo member models (spec §4.1)."""
    params = {
        "latitude": LAT, "longitude": LON, "elevation": ELEVATION,
        "timezone": TIMEZONE, "forecast_days": 10,
        "models": ",".join(OPEN_METEO_MODELS),
        "hourly": ",".join(OPEN_METEO_HOURLY_VARS),
        "daily": ",".join(OPEN_METEO_DAILY_VARS),
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"open-meteo: request failed, skipping run ({e})", file=sys.stderr)
        return []

    rows = []
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    for model in OPEN_METEO_MODELS:
        for var in OPEN_METEO_HOURLY_VARS:
            series = hourly.get(f"{var}_{model}")
            if series is None:
                continue  # this member doesn't supply this variable
            for t, v in zip(times, series):
                if v is None:
                    continue
                lead_hours = round((datetime.fromisoformat(t) - run_dt).total_seconds() / 3600)
                rows.append({"run_time": run_time, "member": model,
                             "lead_hours": lead_hours, "variable": var, "value": v})
    return rows


def fetch_arso(run_time, run_dt):
    try:
        resp = requests.get(ARSO_FORECAST_URL.format(town=ARSO_FORECAST_TOWN.replace(" ", "%20")), timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"arso: request failed, skipping ({e})", file=sys.stderr)
        return []

    timeline = []
    for block_key in ("forecast1h", "forecast3h"):
        block = data.get(block_key)
        if block and block.get("features"):
            for day in block["features"][0]["properties"]["days"]:
                timeline.extend(day["timeline"])
            break  # prefer 1h resolution; only fall back to 3h if absent

    rows = []
    for entry in timeline:
        valid = entry.get("valid")
        if not valid:
            continue
        # Same trap as fetch_obs.py: run_dt is naive so .astimezone(run_dt.tzinfo)
        # is .astimezone(None) = the runner's timezone (UTC in CI), which shifted
        # every logged ARSO lead_hours by -2 and corrupted the training archive.
        valid_dt = (datetime.fromisoformat(valid)
                    .astimezone(ZoneInfo(TIMEZONE)).replace(tzinfo=None))
        lead_hours = round((valid_dt - run_dt).total_seconds() / 3600)
        for field, var in ARSO_VAR_MAP.items():
            raw = entry.get(field)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            rows.append({"run_time": run_time, "member": "arso",
                         "lead_hours": lead_hours, "variable": var, "value": value})
    return rows


def fetch_osmer_bulletin(run_time):
    """Qualitative regional bulletin only (symbol + reliability, no per-point
    numeric values) — logged as supplementary metadata, not blended (§4.1)."""
    date_str = run_time[:10].replace("-", "")
    url = FVG_FORECAST_URL_TEMPLATE.format(date=date_str)
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"osmer bulletin: request failed, skipping ({e})", file=sys.stderr)
        return []

    rows = []
    for m in re.finditer(
        r'<scadenza id="(\d+)"[^>]*>.*?<ATTENDIBILITA um="%">(\d+)</ATTENDIBILITA>',
        resp.text, re.DOTALL,
    ):
        scadenza_id, reliability = m.groups()
        rows.append({"run_time": run_time, "member": "osmer_bulletin",
                     "lead_hours": int(scadenza_id) * 24, "variable": "reliability_pct",
                     "value": float(reliability)})
    return rows


def fetch_pro_vreme(run_time, run_dt):
    """Strict regex/float parsing; skip on any parse failure, never guess (§7.10)."""
    headers = {"User-Agent": PRO_VREME_USER_AGENT}
    try:
        resp = requests.get(PRO_VREME_URL, headers=headers, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"pro-vreme: request failed, skipping ({e})", file=sys.stderr)
        return []

    text = re.sub(r"<[^>]+>", "\n", resp.text)
    rows = []
    for label, var in PRO_VREME_ROW_MAP.items():
        m = re.search(re.escape(label) + r"\s*((?:-|[\d.,]+\s*(?:°C|m/s|°|mm))+)", text)
        if not m:
            continue
        cells = re.findall(r"-|[\d.,]+\s*(?:°C|m/s|°|mm)", m.group(1))
        for day_index, cell in enumerate(cells[:6]):
            if cell == "-":
                continue
            num = re.match(r"[\d.,]+", cell)
            if not num:
                continue
            try:
                value = float(num.group(0).replace(",", "."))
            except ValueError:
                continue
            lead_hours = day_index * 24 + 15  # PROFKO afternoon-representative value
            rows.append({"run_time": run_time, "member": "provreme",
                         "lead_hours": lead_hours, "variable": var, "value": value})
    return rows


def main():
    tz = ZoneInfo(TIMEZONE)
    run_dt = datetime.now(tz).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    run_time = run_dt.isoformat()

    rows = []
    rows += fetch_open_meteo(run_time, run_dt)
    rows += fetch_arso(run_time, run_dt)
    rows += fetch_osmer_bulletin(run_time)
    rows += fetch_pro_vreme(run_time, run_dt)

    append_rows(rows)
    print(f"logged {len(rows)} rows for run {run_time}")


if __name__ == "__main__":
    main()
