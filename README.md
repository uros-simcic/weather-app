# Weather App

**Live:** https://uros-simcic.github.io/weather-app/

A weather forecast for Brda, Slovenia, combining six numerical weather models
with local station observations.

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

The forecast combines available models using variable-specific weights and a
LightGBM correction trained on historical Open-Meteo data. Backtesting selects
between the weighted blend and corrected forecasts. Results are recorded in
[`data/backtest_report.md`](data/backtest_report.md), while comparisons with
station measurements appear in
[`data/verification_report.md`](data/verification_report.md).

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

## The rest of the page

Current conditions combine available observations from ARSO stations at Bilje,
Nova Gorica and Vedrijan. The page displays the observation time.

Alongside: ARSO radar and satellite animations, hail probability sampled from
ARSO's INCA nowcast, and cross-check links to other forecasters.

GitHub Actions refreshes forecast and observation data on scheduled runs and
saves measurements for comparison. The static website displays these updates
through GitHub Pages.

Data: Open-Meteo (CC BY 4.0) · ARSO · ARPA FVG · GeoSphere Austria
