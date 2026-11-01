# Backtest report

Holdout: most recent 12 weeks (temporal split, not random).

Every row below is `unknown-horizon`: Open-Meteo's historical archive returns one value per hour, not the original forecast trajectory, so true lead-time can't be recovered from it. Real per-run lead time (and the 0-24h/1-3d/3-5d/5-10d buckets this cell will eventually split into) only exists once fetch_models.py's live daily logs accumulate — train.py combines both sources going forward.

**Truth-source caveat:** ground truth here is Open-Meteo's archive (ERA5), which is ECMWF's own reanalysis — so ECMWF-family members are measured partly against their own output and will look better than they are. Treat any ECMWF-favouring result as an upper bound, and prefer verification.csv (real Bilje / Nova Gorica station readings) as it accumulates. This is why the shipped choice is a weighted blend rather than ECMWF alone, even where ECMWF alone scores best here.

**The winner's own score is optimistic.** All five candidates are scored on the same holdout the winner is then picked from, so the `ships` column and its MAE come from one number doing two jobs. The lowest of five is low partly on merit and partly on luck, and the margin over the runner-up is the part that is least real — a win by less than a few thousandths should be read as a tie. The comparison between candidates is still fair; it is the winning figure taken as an estimate of live accuracy that is biased low. Note also that every row is one decision made on ~85 days of hourly rows, and consecutive hours are far from independent, so the effective sample behind each choice is nearer 85 than the printed `n`.

## temperature_2m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 1.035 | 1.155 | 0.947 | 0.454 | 1.214 | 1.797 | 0.722 | 0.626 | 0.534 | 0.472 | 0.547 | weighted_mean_p3 |

## relative_humidity_2m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 7.451 | 7.749 | 6.271 | 2.895 | 6.705 | 10.856 | 4.936 | 4.26 | 3.557 | 3.082 | 3.713 | weighted_mean_p3 |

## wind_speed_10m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 2.79 | 2.551 | 2.988 | 2.051 | 2.833 | 2.934 | 1.9 | 1.786 | 1.667 | 1.571 | 1.488 | lightgbm_blend |

## precipitation

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 0.303 | 0.253 | 0.239 | 0.117 | 0.253 | 0.256 | 0.179 | 0.166 | 0.153 | 0.139 | 0.132 | lightgbm_blend |
