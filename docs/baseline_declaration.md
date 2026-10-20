# Baseline Declaration

**Declared:** 20 Oct 2026, before any model was trained or any test-set result was seen.
**Commit rule:** this file is committed before `src/bijlicast/model/` exists. Its git timestamp is the proof.

## What we forecast

Hourly electricity demand profiles (MW, average for each hour of the day across a month) for **K-Electric (Karachi)** and the nine other distribution companies (DISCOs) reported by ISMO:
FESCO, GEPCO, HESCO, IESCO, LESCO, MEPCO, PESCO, QESCO, SEPCO.

One row = one entity × one month × one hour of the day (0–23, Pakistan time).

## Declared baseline (fixed, will not change)

**Seasonal naive:** the forecast for entity *e*, month *m*, hour *h* equals the observed demand for the same entity and hour in the **same calendar month one year earlier** (*m − 12*).

If the month one year earlier is missing in ISMO's publications, the baseline falls back to the **most recent month that was already published at forecast time**. ISMO publishes month *m* around the 15th of month *m + 1*, so the most recent usable month is *m − 2*.

## Evaluation protocol (fixed)

| Item | Rule |
|---|---|
| Split | Time-based. Train ≤ Sep 2025, validation Oct–Dec 2025, **test Jan–Sep 2026** (touched once, at the end). |
| Leakage guard | Demand lags are at least 2 months old (publication delay). Scalers, encoders and conformal residuals are fitted on train/validation only. |
| Primary metric | MAPE (%) over all entities and hours of the test months. |
| Secondary metrics | MAE (MW) for K-Electric only; peak-hour (18:00–22:59) MAPE; interval coverage. |
| "Better" means | Model MAPE at least **10% lower (relative)** than the seasonal-naive MAPE on the test months, and K-Electric MAPE also lower than its baseline. |
| Uncertainty | 80% prediction intervals from split-conformal residuals on the validation months; we report empirical coverage on test. |
| Groups | Entity (DISCO / K-Electric), province, season (summer May–Sep, winter Nov–Feb, shoulder), hour band (night, day, evening peak). |

## Why this baseline

Demand in Pakistan is strongly seasonal (summer cooling load), so "same month last year" is the simplest sensible answer a utility planner would use without a model. A model has to show it adds value beyond that: weather, the recent level of demand, and trends such as rooftop solar reducing grid demand.
