"""Pixel-sample ARSO's INCA hail-probability raster at Brda's coordinates.

No per-town hail page exists (verified in Step 0) — only a whole-Slovenia PNG
where probability is alpha-encoded on a fixed red channel (verified by pixel
histogram: near-uniform (255,0,0,*), alpha varying). The alpha->status
threshold below is inferred, not documented by ARSO — flagged as such.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from config import HAIL_INCA_BBOX, HAIL_INCA_URL_TEMPLATE, LAT, LON, TIMEZONE
from safe_write import write_json

SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
NOW_PATH = os.path.join(SITE_DIR, "now.json")

# Inferred from the alpha histogram; no ARSO documentation found for exact cuts.
ALPHA_LOW, ALPHA_MEDIUM = 40, 130


def latlon_to_px(lat, lon, size):
    min_lon, min_lat, max_lon, max_lat = HAIL_INCA_BBOX
    xf = (lon - min_lon) / (max_lon - min_lon)
    yf = 1 - (lat - min_lat) / (max_lat - min_lat)
    return int(xf * size[0]), int(yf * size[1])


def fetch_latest_inca(now_dt):
    """5-min cadence but published with a lag (verified ~2h) — step back to find it."""
    base = now_dt - timedelta(minutes=now_dt.minute % 5, seconds=now_dt.second)
    for steps_back in range(48):  # covers several hours of possible lag
        bucket = base - timedelta(minutes=5 * steps_back)
        ts = bucket.strftime("%Y%m%d-%H%M")
        url = HAIL_INCA_URL_TEMPLATE.format(timestamp=ts)
        try:
            resp = requests.get(url, timeout=20)
        except requests.RequestException as e:
            print(f"inca: request failed ({e})", file=sys.stderr)
            continue
        if resp.status_code == 200:
            return resp.content
    return None


def status_from_alpha(alpha):
    if alpha == 0:
        return "none"
    if alpha < ALPHA_LOW:
        return "low"
    if alpha < ALPHA_MEDIUM:
        return "medium"
    return "high"


def compute_hail_status():
    tz = ZoneInfo(TIMEZONE)
    now_dt = datetime.now(tz).replace(tzinfo=None)
    png_bytes = fetch_latest_inca(now_dt)
    if png_bytes is None:
        print("inca: no bucket found, leaving hail status unchanged", file=sys.stderr)
        return None

    try:
        from io import BytesIO
        im = Image.open(BytesIO(png_bytes)).convert("RGBA")
    except Exception as e:
        print(f"inca: unreadable image, skipping ({e})", file=sys.stderr)
        return None

    px = latlon_to_px(LAT, LON, im.size)
    r, g, b, a = im.getpixel(px)
    return status_from_alpha(a)


def update_now_json(status):
    try:
        with open(NOW_PATH) as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}
    payload["hail"] = {"status": status}
    os.makedirs(SITE_DIR, exist_ok=True)
    write_json(NOW_PATH, payload, indent=2)


def main():
    status = compute_hail_status()
    if status is None:
        return
    update_now_json(status)
    print(f"hail status: {status}")


if __name__ == "__main__":
    main()
