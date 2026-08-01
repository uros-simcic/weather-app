# Weather App

**Live:** https://uros-simcic.github.io/weather-app/

An AI-corrected weather forecast for Brda, Slovenia, merged from six numerical
weather models and scored against local station measurements.

Full behaviour is specified in [`SPEC.md`](SPEC.md); this page is the summary.

## The models being merged

| Model | Run by | Grid | Reaches |
|---|---|---|---|
| **ECMWF IFS** | ECMWF (Europe) | 25 km | 10 days |
| **ICON-D2** | DWD (Germany) | 2 km | 2 days |
| **ICON-EU** | DWD (Germany) | 7 km | 5 days |
| **ICON-2I** | ItaliaMeteo / ARPAE | 2 km | 3 days |
| **AROME** | GeoSphere Austria | 2.5 km | 2.5 days |
| **GFS** | NOAA (USA) | 13 km | 10+ days |

The three high-resolution regional models (ICON-D2, ICON-2I, AROME) resolve the
Brda hills and the Adriatic–Alpine boundary that coarse global models smooth
over, but only reach 2–3 days out. ECMWF and GFS carry the rest of the week.

## How they are merged

Rather than averaging the six equally, each model is weighted by how accurate it
has actually been here — measured over ~13 months of archived forecasts against
observed weather, per variable and per forecast horizon. A LightGBM model learns
the residual bias on top; it ships **only** where it measurably beats the
weighted average on held-out data, otherwise the simpler blend is used. Both
choices are re-derived monthly and written to
[`data/backtest_report.md`](data/backtest_report.md).

Two guards keep the merge honest: beyond ~5 days, where only ECMWF and GFS
remain, the machine-learned correction is bypassed (too few inputs to correct
from), and every published forecast is re-scored the next day against the real
station readings in [`data/verification_report.md`](data/verification_report.md)
— tracking not just average error but whether the daily temperature swing was
right, which average error alone can hide.

## How a day is divided

Each day is eight 3-hour blocks running midnight to midnight:

```
00-03  03-06  06-09  09-12  12-15  15-18  18-21  21-00
```

Every block belongs entirely to its own calendar day. None crosses midnight, and
a day's last block ends exactly where the next day's first begins, so no hour is
covered twice and none is missed. The daytime summary — the day's icon and rain
probability — is taken over 06:00–20:59, which is exactly the blocks `06-09`
through `18-21`, so the summary and the blocks it sits above always agree on
which hours count as daytime.

The grid was previously phased to 23:00 the previous evening, which gave every
day a `23-02` block belonging to the night before and left nothing ending on
midnight.

## The rest of the page

Current conditions are the median of three stations: ARSO's Bilje and Nova
Gorica, 9–14 km away in the valley, and a personal weather station at Vipolže,
the only one inside Brda. They are lag-corrected along the model's own trend
since ARSO publishes ~2 hours behind. Vipolže contributes temperature and
humidity only — it reports no usable wind — and is scored against alongside the
ARSO pair, so the forecast is corrected toward what Brda itself reads.

Alongside: ARSO radar and satellite animations, hail probability sampled from
ARSO's INCA nowcast, and cross-check links to other forecasters.

No backend and no build step — GitHub Actions fetches, blends and commits JSON
every day, with observations requested every 15 minutes, which a dependency-free
static page renders via GitHub Pages. GitHub drops scheduled runs freely, so the
observation cadence is a ceiling rather than a promise; the daily forecast job
refreshes the current conditions too, as a floor under it.

Data: Open-Meteo (CC BY 4.0) · ARSO · ARPA FVG · GeoSphere Austria
