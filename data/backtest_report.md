# Backtest report

Holdout: most recent 12 weeks (temporal split, not random).

Every row below is `unknown-horizon`: Open-Meteo's historical archive returns one value per hour, not the original forecast trajectory, so true lead-time can't be recovered from it. Real per-run lead time (and the 0-24h/1-3d/3-5d/5-10d buckets this cell will eventually split into) only exists once fetch_models.py's live daily logs accumulate — train.py combines both sources going forward.

## temperature_2m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 1.212 | 1.132 | 0.92 | 0.571 | 1.487 | 1.543 | 0.792 | 0.523 | lightgbm_blend |

## relative_humidity_2m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 9.49 | 8.557 | 6.911 | 4.026 | 9.581 | 10.419 | 6.326 | 4.206 | lightgbm_blend |

## wind_speed_10m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 3.013 | 3.022 | 2.88 | 1.861 | 2.87 | 3.184 | 2.153 | 1.722 | lightgbm_blend |

## precipitation

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 0.276 | 0.219 | 0.17 | 0.116 | 0.213 | 0.271 | 0.168 | 0.145 | lightgbm_blend |
