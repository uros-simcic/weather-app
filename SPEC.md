# Brda weather app — specification

The original spec lived outside the repository, and the block grid drifted from
it the moment the phasing changed (see §7.2). This file replaces it, kept beside
the code so the two can be checked against each other.

**Reconstructed from the implementation**, section numbers preserved so the
`§` citations already in the source resolve here. Where the code and the earlier
document disagreed, the code is what shipped and is what is written down.
Sections not cited anywhere in the source are omitted rather than invented.

---

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

Current conditions are the median across three stations:

| Station | Network | Elevation | Distance | Supplies |
|---|---|---|---|---|
| Bilje | ARSO | 55 m | ~13–14 km | all variables |
| Nova Gorica | ARSO | 113 m | ~9–10 km | all variables |
| Vipolže (IBRDAM11) | personal station | self-reported 37 m | ~2.5 km | temperature, humidity |

Vipolže is the only station inside Brda; the ARSO pair are in the valley. It
reports no usable wind, so wind is an ARSO figure alone — a variable a station
does not report is simply absent from that variable's median.

A reading older than **60 minutes** is dropped before the median is taken. Wind
direction is not medianed (the median of 350° and 10° is not 180°); it is taken
from whichever fresh station reported most recently.

ARSO publishes roughly two hours behind, so the median is lag-corrected along
the models' own trend between the observation time and now.

FVG's stations (Capriva, Cormons) carry a 24-hour no-republish clause on
real-time data. They are logged for **training and backtesting only and never
appear in the live figure**.

**Rainfall is logged, prepared for future integration.** Nothing reads it yet.
Four quantities over four windows, kept under separate names:

| Variable | Source | Meaning |
|---|---|---|
| `precipitation_10min` | ARSO `tp_acc` | mm in the 10-minute interval, recorded only when the entry's own `interval` field says 10 |
| `precipitation_12h` | ARSO `tp_12h_acc` | mm in the rolling 12 hours |
| `precipitation_rate` | Vipolže `precipRate` | instantaneous mm/h |
| `precipitation_today` | Vipolže `precipTotal` | mm since local midnight |

ARSO's `tp_1h_acc` and `tp_24h_acc` exist in the schema but are always empty, so
no hourly station total is available from that source. Negative readings and
anything above 200 mm are dropped rather than logged — a frozen or un-zeroed
tipping bucket produces both, and a wrong number in the archive is worse than a
missing one, because a correction fitted later cannot tell them apart.

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

Below **3 available members** the ML path is bypassed regardless of what was
selected. Beyond ~5 days only ECMWF and GFS remain, and with the other four
missing the tree collapses toward climatology — measured at 28–29 °C where the
two live members said 34–40 °C.

The reported winning score is **optimistic**: all candidates are scored on the
same holdout the winner is chosen from, so the margin over the runner-up is the
least trustworthy part of it. See `data/backtest_report.md`.

---

## §6 — Regression targets

Four variables are corrected and scored:

`temperature_2m` · `relative_humidity_2m` · `wind_speed_10m` · `precipitation`

Training uses at least 12 months of archived forecasts (13 are fetched, for
margin) with a **temporal** train/holdout split of the most recent 12 weeks —
never a random split.

---

## §7 — Presentation

### §7.2 Blocks

A day is **eight 3-hour blocks running midnight to midnight**:

```
00-03  03-06  06-09  09-12  12-15  15-18  18-21  21-00
```

Every block belongs entirely to its own calendar day. None crosses midnight, and
a day's last block ends exactly where the next day's first begins — no hour is
covered twice and none is missed.

> **Changed.** The grid was previously phased to 23:00 the previous evening,
> giving every day a `23-02` block that belonged to the night before and leaving
> nothing ending on midnight. A day could not then be shown without either
> borrowing a block from its neighbour or leaving 23:00–midnight uncovered.

The day's icon and rain probability summarise **daytime only, 06:00–20:59** —
exactly blocks `06-09` through `18-21`. Using all 24 hours let a pre-dawn shower
that had cleared by sunrise flip an otherwise sunny day to rain.

Wind is the exception and stays whole-day: it answers "windiest it gets", not
"how is the day".

Block wind **direction** comes from the hour of that block's maximum speed, not
from an average.

Icon severity, most severe first:

`storm` > `snow` > `rain` > `fog` > `cloud` > `partly` > `sun`

A day takes the most severe icon among its daytime hours. Weather codes are
categorical and are **never averaged** — two members forecasting rain (63 and
81) average to 72, a snow code.

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

Rain probability is shown only at **≥ 30 %**, rounded to the nearest 5, and is
**capped at 95 %** — never 99 or 100. On 2026-07-26 both probability-carrying
members said 98–100 % and the stations measured 0.0 mm under a sunny sky; a
summer convective bust is ordinary meteorology, and claiming certainty about it
is not.

Only ECMWF and GFS publish a probability at all, so it is combined with the
share of *all* members forecasting measurable rain (≥ 0.1 mm/h) — otherwise the
figure came from the two coarsest members exactly when terrain matters most.

### §7.8 Never present stale data as current

If `now.json` is missing, unparseable, or its reading is more than **120 minutes**
old, the app falls back to the forecast block covering the current time rather
than showing a stale measurement as if it were fresh. A forecast older than
**24 hours** raises a staleness banner.

Timestamps are published with their UTC offset so a reading's age cannot be
misjudged across the daylight-saving change.

### §7.10 Never guess

Any fetch or parse failure yields **no value**, never an interpolated or assumed
one. A member missing a variable is skipped for that hour; a station whose
reading fails a sanity bound is dropped from the median; a partial reading is
discarded rather than half-used. Sanity bounds: temperature −25…45 °C, relative
humidity 1…100 %, wind speed 0…180 km/h.
