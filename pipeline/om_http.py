"""Shared Open-Meteo GET with retries that match the failure mode.

429 is a rate limit: sleep (Retry-After, else 15/30/60s) and retry.
502/503/504 are blips: short sleep and retry.
Timeouts retry with the next timeout budget.
Do not treat 429 as "needs a longer read timeout" (forecast #237).
"""
import json
import sys
import time

import requests

from safe_write import write_json


def _load_snapshot(path, url, params):
    """Reuse only a recent response for this exact request."""
    try:
        with open(path) as f:
            saved = json.load(f)
        if (saved["url"] == url and saved["params"] == params
                and 0 <= time.time() - saved["fetched_at"] <= 15 * 60
                and isinstance(saved["data"], dict)):
            return saved["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def get_json(url, params, timeouts=(30, 60, 90), *, snapshot_path=None):
    # The workflow puts this in runner.temp, outside the repository and the
    # persistent Actions cache. fetch_models and blend share it for one job.
    if snapshot_path:
        saved = _load_snapshot(snapshot_path, url, params)
        if saved is not None:
            print("open-meteo: reusing this job's forecast response", file=sys.stderr)
            return saved
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
            data = resp.json()
            if snapshot_path:
                try:
                    write_json(snapshot_path, {
                        "url": url, "params": params,
                        "fetched_at": time.time(), "data": data,
                    })
                except OSError:
                    # An optional optimization must not lose a good response.
                    print("open-meteo: could not save forecast snapshot", file=sys.stderr)
            return data
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
