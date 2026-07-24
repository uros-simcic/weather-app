# Weather App

**Live:** https://uros-simcic.github.io/weather-app/

An AI-corrected weather forecast for Brda, Slovenia, merged from six numerical
weather models and scored against local station measurements.

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
from), and every published forecast is re-scored the next day against real ARSO
station readings in [`data/verification_report.md`](data/verification_report.md)
— tracking not just average error but whether the daily temperature swing was
right, which average error alone can hide.

## The rest of the page

Current conditions come from the nearest ARSO automatic stations (Bilje, Nova
Gorica), lag-corrected along the model's own trend since ARSO publishes ~2 hours
behind. Alongside: ARSO radar and satellite animations, hail probability sampled
from ARSO's INCA nowcast, and cross-check links to other forecasters.

No backend and no build step — GitHub Actions fetches, blends and commits JSON
every day (observations every 30 minutes), which a dependency-free static page
renders via GitHub Pages.

Data: Open-Meteo (CC BY 4.0) · ARSO · ARPA FVG · GeoSphere Austria
