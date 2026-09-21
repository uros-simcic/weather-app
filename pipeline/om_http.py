"""Shared Open-Meteo GET with retries that match the failure mode.

429 is a rate limit: sleep (Retry-After, else 15/30/60s) and retry.
502/503/504 are blips: short sleep and retry.
Timeouts retry with the next timeout budget.
Do not treat 429 as "needs a longer read timeout" (forecast #237).
"""
import sys
import time

import requests


def get_json(url, params, timeouts=(30, 60, 90)):
    last_error = None
    n = len(timeouts)
    for i, timeout in enumerate(timeouts):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = _retry_after(resp, default=15 * (i + 1))
                print(f"open-meteo: 429, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                last_error = requests.HTTPError(
                    f"429 Client Error for url: {resp.url}", response=resp
                )
                continue
            if resp.status_code in (502, 503, 504):
                wait = min(10 * (i + 1), 60)
                print(f"open-meteo: {resp.status_code}, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                last_error = requests.HTTPError(
                    f"{resp.status_code} Server Error for url: {resp.url}",
                    response=resp,
                )
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
            print(f"open-meteo: attempt failed ({e})", file=sys.stderr)
            if i + 1 < n:
                time.sleep(5)
    raise last_error


def _retry_after(resp, default):
    raw = resp.headers.get("Retry-After")
    try:
        wait = int(raw)
    except (TypeError, ValueError):
        wait = default
    return min(max(wait, 1), 90)
