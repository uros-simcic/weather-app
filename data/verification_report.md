# Verification report

Rolling 30 days, scored against **real ARSO station readings** (Bilje / Nova Gorica median) — not ERA5, so unlike backtest_report.md this carries no ECMWF self-grading bias.

`range_error` = our daily swing minus the measured one. Persistent negative values mean the forecast is flattening (under-predicting how much the temperature moves), which plain MAE can hide.

_No scored days yet._ Scoring needs a full day where we published a forecast **and** later observed it — so the first rows appear a day after `log_published.csv` starts filling.
