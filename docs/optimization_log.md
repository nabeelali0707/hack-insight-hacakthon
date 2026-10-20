# Optimization Log

All accuracy numbers are **rolling-origin validation MAPE** on months <= Dec 2025 with ex-ante
(climatology) weather. The test set (Jan-Sep 2026) was not used for any of these decisions.
Seed 42; same split for every run. Peak MB = Python allocations during fitting (tracemalloc).

| # | Area | Change | Val MAPE | Fit time (s) | Peak MB | Kept? | Why |
|---|---|---|---|---|---|---|---|
| OPT-00 | reference | 0. Reference: declared seasonal-naive baseline on the same validation months | 19.26% | 0.0 | 0.0 | no | reference |
| OPT-01 | accuracy | 1. Linear model (Ridge, one-hot entity) instead of gradient boosting | 31.15% | 0.27 | 4.4 | no | simpler but cannot learn hour x season x entity interactions |
| OPT-02 | accuracy | 2. Gradient boosting, all features, log-ratio target, 400 rounds (v1) | 12.81% | 34.97 | 5.9 | yes | best validation accuracy; explainable via relative change vs latest published month |
| OPT-03 | accuracy | 3. Drop all weather features (calendar + lags only) | 17.14% | 35.78 | 5.1 | no | tests whether weather earns its place |
| OPT-04 | accuracy | 4. Drop last-year features (ly_shape, ly_seasonal_ratio) | 14.17% | 35.33 | 6.0 | no | tests seasonal memory |
| OPT-05 | accuracy | 5. Ratio target instead of log-ratio | 13.88% | 27.19 | 5.8 | no | log stabilises multiplicative changes |
| OPT-06 | speed | 6. Fewer boosting rounds (max_iter 400 -> 150) (ADOPTED v2) | 12.8% | 10.33 | 4.7 | yes | same validation accuracy, ~4x faster fit; now chosen automatically by the tie-break rule |
| OPT-07 | memory | 7. float32 features (halve feature memory) | 12.74% | 27.31 | 5.4 | no | memory trade-off; panel is small, so not needed |
| OPT-08 | speed | 8. Weather month-hour aggregation inside DuckDB instead of pandas (419k rows) | - | 0.172 | - | yes | DuckDB 0.17s vs pandas 2.16s and 76 MB Python peak |
| OPT-09 | memory | 9. Gold tables stored as Parquet (columnar, compressed) | - | - | 1.03 | yes | all gold tables = 1.0 MB on disk; dashboard loads only needed columns |
| OPT-10 | pipeline | 10. Incremental runs: reuse SHA-verified raw files (make data-fast) and fetch only live weather each hour | - | - | - | yes | full rebuild ~108 s (96 s is download); hourly run re-downloads only 10 small files |
| OPT-11 | speed | 11. Feature panel build, vectorised with merges (both weather modes) | - | 1.91 | 11.9 | yes | replaced a per-row Python loop: 24.4 s -> 0.5 s (measured 2026-10-20), identical output (max abs diff 3.6e-15, 0 NaN mismatches on 6,216 rows) |
| OPT-12 | accuracy | 12. Select hyper-parameters on rolling-origin validation (6 months) instead of 3 fixed months; tie-break to fewer rounds | - | - | - | yes | 3 validation months were dominated by K-Electric's Oct 2025 step change; rolling origin is more robust and gives the conformal residuals for free |

## Trade-offs in plain words

* The adopted model cuts validation error from 19.26% (baseline) to 12.8%.
* Removing weather changes validation MAPE to 17.14%: weather helps, and it is what lets the live outlook react to heatwaves.
* Fewer boosting rounds trains faster; we kept 400 because monthly retraining takes seconds anyway.
* Reliability after each change: same seed gives identical numbers; the time split never changed; per-group errors are re-checked in reports/model_report.md for the adopted version.

## Test-set use (full disclosure)

The test set was scored twice, never to choose anything:

| Version | Chosen by | Test MAPE | K-Electric MAPE | Peak MAPE | 80% coverage |
|---|---|---|---|---|---|
| v1 (400 rounds, chosen on Oct-Dec 2025) | validation | 13.61% | 10.91% | 12.89% | 74.5% |
| **v2 (150 rounds, rolling-origin selection)** | validation | **13.49%** | **10.11%** | **12.51%** | **75.9%** |

v2 was adopted because of validation results (OPT-06, OPT-12) recorded before its test run.
