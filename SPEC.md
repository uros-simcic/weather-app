# Brda weather app — specification

The app combines regional and global forecasts with local station observations
for Brda, Slovenia.

## §4 — Sources

### §4.1 Forecast members

Six numerical models, all fetched in a single Open-Meteo request:

| Model | Run by | Grid | Reaches |
|---|---|---|---|
| ECMWF IFS | ECMWF | 25 km | 10 days |
| ICON-D2 | DWD | 2 km | 2 days |
| ICON-EU | DWD | 7 km | 5 days |
| ICON-2I | ItaliaMeteo / ARPAE | 2 km | 3 days |
| AROME | GeoSphere Austria | 2.5 km | 2.5 days |
| GFS | NOAA | 13 km | 10+ days |

A member that errors, or that omits a variable for a given hour, is **skipped
for that run — never guessed or back-filled** (see §7.10). Member counts
therefore fall with lead time as the regional models drop out.

OSMER's regional bulletin is prose, symbol codes and a reliability percentage,
not per-point numeric values. It is logged as supplementary metadata and is
**never blended** as a member.

### §4.2 Observations

Current conditions combine available observations from Bilje, Nova Gorica and
Vedrijan. Readings are checked for freshness and combined separately for each
weather variable. Temperature and humidity can be adjusted using the forecast's
trend.

Station readings display `zdaj` with their observation time. Forecast fallback
displays `danes`.

The app logs observations from Capriva and Cormons. Their 24-hour restriction
on republication keeps them out of current conditions. Model fitting uses the
Open-Meteo archive. Station verification excludes FVG observations.

Station rainfall is logged under four separate fields:

| Variable | Source | Meaning |
|---|---|---|
| `precipitation_10min` | ARSO `tp_acc` | mm in the 10-minute interval, recorded only when the entry's own `interval` field says 10 |
| `precipitation_12h` | ARSO `tp_12h_acc` | mm in the rolling 12 hours |
| `precipitation_rate` | Optional Vipolže station `precipRate` | instantaneous mm/h |
| `precipitation_today` | Optional Vipolže station `precipTotal` | mm since local midnight |

ARSO supplies no 1-hour or 24-hour rainfall totals in these observations.
The logger discards negative rainfall values and values above 200.

### §4.4 Cross-check links

Six buttons, in this order and casing:

`pro-vreme` · `ARSO` · `meteo.it` · `bergfex` · `yr.no` · `windy`

`meteo.it` is a link only — never fetched or parsed.

---

## §5 — Blending

### §5.3 Method selection and fallback

Per variable, candidate methods are scored on a held-out slice and the winner is
recorded in `data/blend_decisions.json`:

- `equal_weight_mean`
- `weighted_mean_p1` / `p2` / `p3` — weight ∝ (1/MAE)^p
- `lightgbm_blend`

The learned blend **ships only where it measurably beats the equal-weight mean**;
otherwise the simpler blend is used, and `train.py` does not retrain a variable
no cell ships ML for.

The forecast bypasses the learned blend when fewer than three members are
available. Beyond about five days, only ECMWF and GFS remain.

The backtest selects and scores the winning method on the same holdout, which
can make the reported error optimistic. See `data/backtest_report.md`.

---

## §6 — Regression targets

Four variables are corrected and scored:

`temperature_2m` · `relative_humidity_2m` · `wind_speed_10m` · `precipitation`

Backtesting and model fitting use archived Open-Meteo forecasts and weather
records. Backtesting holds out the most recent 12 weeks in time order. The
production model is fitted on all available rows in its archive window.

---

## §7 — Presentation

### §7.2 Blocks

A day is **eight 3-hour blocks running midnight to midnight**:

```
00-03  03-06  06-09  09-12  12-15  15-18  18-21  21-00
```

The daily icon and rain probability cover **06:00–20:59**. Daily wind uses
the highest speed over all eight blocks. Each block takes its wind direction
from the hour with the highest wind speed in that block.

Icon severity, most severe first:

`storm` > `snow` > `rain` > `fog` > `cloud` > `partly` > `sun`

The daily icon uses the most severe icon among the daytime hours. The app
treats weather codes as categories.

### §7.5 Weather codes, rain probability, UV

WMO code → icon:

| Codes | Icon |
|---|---|
| 0, 1 | sun |
| 2 | partly |
| 3 | cloud |
| 45, 48 | fog |
| 51–67, 80–82 | rain |
| 71–77, 85, 86 | snow |
| 95–99 | storm |
| anything else | cloud |

The app combines ECMWF and GFS rain probabilities with the share of available
members forecasting at least 0.1 mm/h. It displays probabilities of **30% or
higher**, rounds to the nearest 5 percentage points and caps the result at **95%**.

### §7.8 Never present stale data as current

If `now.json` is missing, unparseable, lacks a numeric temperature, or was
generated more than **120 minutes** ago, the app uses the forecast block
covering the current time when one is available. A forecast older than
**24 hours** raises a staleness banner.

Timestamps are published with their UTC offset so a reading's age cannot be
misjudged across the daylight-saving change.

### §7.10 Never guess

Any fetch or parse failure yields **no value**, never an interpolated or assumed
one. A member missing a variable is skipped for that hour; a station whose
reading fails a sanity bound is dropped from the median; a partial reading is
discarded rather than half-used. Sanity bounds: temperature −25…45 °C, relative
humidity 1…100 %, wind speed 0…180 km/h.
