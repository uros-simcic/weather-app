# Backtest report

Holdout: most recent 12 weeks (temporal split, not random).

Every row below is `unknown-horizon`: Open-Meteo's historical archive returns one value per hour, not the original forecast trajectory, so true lead-time can't be recovered from it. Real per-run lead time (and the 0-24h/1-3d/3-5d/5-10d buckets this cell will eventually split into) only exists once fetch_models.py's live daily logs accumulate — train.py combines both sources going forward.

**Truth-source caveat:** ground truth here is Open-Meteo's archive (ERA5), which is ECMWF's own reanalysis — so ECMWF-family members are measured partly against their own output and will look better than they are. Treat any ECMWF-favouring result as an upper bound, and prefer verification.csv (real Bilje / Nova Gorica station readings) as it accumulates. This is why the shipped choice is a weighted blend rather than ECMWF alone, even where ECMWF alone scores best here.

**The winner's own score is optimistic.** All five candidates are scored on the same holdout the winner is then picked from, so the `ships` column and its MAE come from one number doing two jobs. The lowest of five is low partly on merit and partly on luck, and the margin over the runner-up is the part that is least real — a win by less than a few thousandths should be read as a tie. The comparison between candidates is still fair; it is the winning figure taken as an estimate of live accuracy that is biased low. Note also that every row is one decision made on ~85 days of hourly rows, and consecutive hours are far from independent, so the effective sample behind each choice is nearer 85 than the printed `n`.

## temperature_2m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 1.237 | 1.138 | 0.936 | 0.576 | 1.509 | 1.589 | 0.804 | 0.73 | 0.654 | 0.596 | 0.538 | lightgbm_blend |

## relative_humidity_2m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 9.47 | 8.493 | 6.987 | 4.046 | 8.908 | 10.496 | 6.19 | 5.54 | 4.848 | 4.34 | 3.753 | lightgbm_blend |

## wind_speed_10m

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 2.95 | 2.915 | 2.772 | 1.83 | 2.891 | 3.178 | 2.105 | 2.022 | 1.929 | 1.833 | 1.69 | lightgbm_blend |

## precipitation

| lead_bucket | n | mae_italia_meteo_arpae_icon_2i | mae_icon_d2 | mae_icon_eu | mae_ecmwf_ifs025 | mae_gfs_seamless | mae_geosphere_arome_austria | mae_equal_weight_mean | mae_weighted_mean_p1 | mae_weighted_mean_p2 | mae_weighted_mean_p3 | mae_lightgbm_blend | ships |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unknown-horizon | 2040 | 0.264 | 0.213 | 0.153 | 0.098 | 0.188 | 0.252 | 0.156 | 0.158 | 0.162 | 0.169 | 0.129 | lightgbm_blend |
