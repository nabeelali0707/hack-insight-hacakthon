# Model Report (generated from gold tables)

Trained 2026-10-20T17:18:29Z · seed 42 · test months 2026-01, 2026-02, 2026-03, 2026-04, 2026-05, 2026-08, 2026-09 (Jun-Jul 2026 not published by ISMO).

## Headline (test set, evaluated once, ex-ante weather = climatology)

| | Declared baseline | BijliCast model |
|---|---|---|
| MAPE, all 10 entities x 24 h | 17.97% | **13.61%** (24% better) |
| K-Electric MAPE | 17.31% | **10.91%** |
| K-Electric MAE | 338 MW | **216 MW** |
| Evening peak 18-22 h MAPE | 16.90% | **12.89%** |
| 80% interval coverage | - | 74.5% (mean width 42% of forecast) |
| Same model, actual (ex-post) weather | - | 12.41% (upper bound if weather were known) |

Declared success criterion (>= 10% lower MAPE and K-Electric better): **met**.

![baseline vs model](figures/baseline_vs_model.png)

![K-Electric profiles](figures/ke_profiles_test.png)

## Errors by group

| entity | rows | baseline MAPE | model MAPE | change | 80% coverage | bias |
|---|---|---|---|---|---|---|
| PESCO | 168 | 25.4% | 17.6% | -31% | 66% | +0.7% |
| IESCO | 168 | 14.9% | 15.9% | +6% | 65% | -8.0% |
| FESCO | 168 | 15.5% | 15.5% | +0% | 68% | -1.7% |
| SEPCO | 168 | 21.8% | 14.5% | -34% | 78% | -4.5% |
| MEPCO | 168 | 19.0% | 13.9% | -27% | 73% | -5.8% |
| HESCO | 168 | 20.6% | 13.2% | -36% | 82% | +4.5% |
| LESCO | 168 | 16.0% | 13.1% | -18% | 71% | -5.2% |
| KE | 168 | 17.3% | 10.9% | -37% | 86% | -2.4% |
| QESCO | 168 | 13.3% | 10.8% | -19% | 79% | -4.0% |
| GEPCO | 168 | 15.8% | 10.7% | -32% | 77% | -8.4% |

| province | rows | baseline MAPE | model MAPE | change | 80% coverage | bias |
|---|---|---|---|---|---|---|
| Khyber Pakhtunkhwa | 168 | 25.4% | 17.6% | -31% | 66% | +0.7% |
| ICT/Punjab | 168 | 14.9% | 15.9% | +6% | 65% | -8.0% |
| Punjab | 672 | 16.6% | 13.3% | -20% | 72% | -5.1% |
| Sindh | 504 | 19.9% | 12.9% | -35% | 82% | -1.2% |
| Balochistan | 168 | 13.3% | 10.8% | -19% | 79% | -4.0% |

| season | rows | baseline MAPE | model MAPE | change | 80% coverage | bias |
|---|---|---|---|---|---|---|
| shoulder | 480 | 17.9% | 14.9% | -17% | 79% | +8.2% |
| summer | 720 | 18.2% | 14.5% | -20% | 62% | -11.4% |
| winter | 480 | 17.6% | 11.0% | -38% | 88% | +0.9% |

| hour band | rows | baseline MAPE | model MAPE | change | 80% coverage | bias |
|---|---|---|---|---|---|---|
| afternoon 12-17 | 420 | 17.3% | 14.7% | -15% | 72% | -1.2% |
| morning 06-11 | 420 | 17.4% | 13.8% | -21% | 72% | -2.3% |
| night 00-05 | 420 | 19.9% | 13.4% | -33% | 74% | -7.2% |
| evening peak 18-22 | 350 | 16.9% | 12.9% | -24% | 79% | -4.0% |
| late 23 | 70 | 19.2% | 11.2% | -42% | 86% | -7.5% |

![errors by group](figures/errors_by_group.png)

## Where the model is weakest and what a user should do

* **Weakest entity: PESCO** (17.6% MAPE). Its profile has
  Ramadan sehri spikes and recurring scheduled-load-management jumps (see quality log `DQ-ISMO-SPIKE`).
* **No gain over the baseline for: FESCO, IESCO.** For these, planners should keep the
  seasonal-naive figure and use our interval as a range check.
* **Summer is hardest:** the model under-forecasts summer months (negative bias) and interval coverage falls below 80%.
  Treat summer evening-peak forecasts as a floor, not a ceiling.
* Intervals cover 75% of test values against an 80% target: slightly too narrow, mainly in summer.

## Method

* Target: log(demand / latest published level); prediction = level x exp(model). Handles K-Electric's 2025 step
  change in grid draw without extrapolating trends.
* Model: scikit-learn HistGradientBoostingRegressor {'learning_rate': 0.05, 'max_leaf_nodes': 15, 'l2_regularization': 1.0, 'max_iter': 400} chosen on validation months Oct-Dec 2025
  (validation MAPE 13.94%).
* Leakage guards: demand lags >= 2 months (ISMO publication lag); climatology uses only earlier years; final model
  trained on targets <= Nov 2025 (all ISMO had published by 1 Jan 2026); test touched once.
* Intervals: split-conformal on 1440 rolling-origin out-of-sample residuals,
  log-quantiles -0.220 / 0.200.
