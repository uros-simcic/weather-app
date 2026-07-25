# Verification report

Rolling 30 days, scored against **real ARSO station readings** (Bilje / Nova Gorica median) — not ERA5, so unlike backtest_report.md this carries no ECMWF self-grading bias.

`range_error` = our daily swing minus the measured one. Persistent negative values mean the forecast is flattening (under-predicting how much the temperature moves), which plain MAE can hide.

## relative_humidity_2m

- days scored: **1**
- mean MAE: **8.52**
- mean range error: **-3.56** (negative = forecast too flat)

| date | n_hours | mae | forecast_range | observed_range | range_error |
|---|---|---|---|---|---|
| 2026-07-25 | 11 | 8.518 | 27.44 | 31.0 | -3.56 |

## temperature_2m

- days scored: **1**
- mean MAE: **0.85**
- mean range error: **+0.29** (negative = forecast too flat)

| date | n_hours | mae | forecast_range | observed_range | range_error |
|---|---|---|---|---|---|
| 2026-07-25 | 11 | 0.855 | 9.39 | 9.1 | 0.29 |

## wind_speed_10m

- days scored: **1**
- mean MAE: **3.45**
- mean range error: **-2.00** (negative = forecast too flat)

| date | n_hours | mae | forecast_range | observed_range | range_error |
|---|---|---|---|---|---|
| 2026-07-25 | 11 | 3.452 | 9.0 | 11.0 | -2.0 |
