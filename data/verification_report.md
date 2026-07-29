# Verification report

Rolling 30 days, scored against **real ARSO station readings** (Bilje / Nova Gorica median) — not ERA5, so unlike backtest_report.md this carries no ECMWF self-grading bias.

`range_error` = our daily swing minus the measured one. Persistent negative values mean the forecast is flattening (under-predicting how much the temperature moves), which plain MAE can hide.

## relative_humidity_2m

- days scored: **5**
- mean MAE: **8.18**
- mean range error: **-1.81** (negative = forecast too flat)

| date | n_hours | mae | forecast_range | observed_range | range_error |
|---|---|---|---|---|---|
| 2026-07-29 | 4 | 8.42 | 27.5 | 35.0 | -7.5 |
| 2026-07-28 | 4 | 6.65 | 36.22 | 42.0 | -5.78 |
| 2026-07-27 | 5 | 4.994 | 15.43 | 28.0 | -12.57 |
| 2026-07-26 | 5 | 12.342 | 25.36 | 5.0 | 20.36 |
| 2026-07-25 | 11 | 8.518 | 27.44 | 31.0 | -3.56 |

## temperature_2m

- days scored: **5**
- mean MAE: **1.21**
- mean range error: **-0.13** (negative = forecast too flat)

| date | n_hours | mae | forecast_range | observed_range | range_error |
|---|---|---|---|---|---|
| 2026-07-29 | 4 | 0.787 | 7.26 | 6.4 | 0.86 |
| 2026-07-28 | 4 | 1.105 | 4.54 | 6.3 | -1.76 |
| 2026-07-27 | 5 | 1.372 | 4.12 | 7.4 | -3.28 |
| 2026-07-26 | 5 | 1.918 | 6.54 | 3.3 | 3.24 |
| 2026-07-25 | 11 | 0.855 | 9.39 | 9.1 | 0.29 |

## wind_speed_10m

- days scored: **5**
- mean MAE: **1.92**
- mean range error: **-0.89** (negative = forecast too flat)

| date | n_hours | mae | forecast_range | observed_range | range_error |
|---|---|---|---|---|---|
| 2026-07-29 | 4 | 1.28 | 2.48 | 3.0 | -0.52 |
| 2026-07-28 | 4 | 2.223 | 12.85 | 13.0 | -0.15 |
| 2026-07-27 | 5 | 1.18 | 1.38 | 3.0 | -1.62 |
| 2026-07-26 | 5 | 1.448 | 2.85 | 3.0 | -0.15 |
| 2026-07-25 | 11 | 3.452 | 9.0 | 11.0 | -2.0 |
