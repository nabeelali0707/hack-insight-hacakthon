"""Train, evaluate and save the BijliCast demand-profile model.

Protocol (docs/baseline_declaration.md):
  train      targets <= 2025-08 for tuning; final model on targets <= 2025-11
             (everything ISMO had published before the first test origin, 1 Jan 2026)
  validation 2025-10 .. 2025-12 (hyper-parameter choice only)
  test       2026-01 .. 2026-09, evaluated ONCE with ex-ante (climatology) weather
  intervals  split-conformal 80% from rolling-origin out-of-sample residuals (train + validation)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import HistGradientBoostingRegressor

from ..config import CONFIG_DIR, MODELS_DIR, REPORTS_DIR, ensure_dirs
from ..warehouse import _write, connect
from .baseline import seasonal_naive
from .features import FEATURES, build_panel, load_inputs

SEED = 42
TUNE_TRAIN_END = pd.Timestamp("2025-08-01")
VAL_MONTHS = pd.date_range("2025-10-01", "2025-12-01", freq="MS")
FINAL_TRAIN_END = pd.Timestamp("2025-11-01")
TEST_START, TEST_END = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-09-01")
ALPHA = 0.20  # 80% intervals

PARAM_GRID = [
    {"learning_rate": lr, "max_leaf_nodes": leaves, "l2_regularization": l2, "max_iter": it}
    for lr in (0.05, 0.1) for leaves in (15, 31) for l2 in (0.0, 1.0) for it in (200, 400)
]


def make_model(params: dict) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss="squared_error", categorical_features="from_dtype",
                                         random_state=SEED, **params)


def fit(df: pd.DataFrame, params: dict) -> HistGradientBoostingRegressor:
    m = make_model(params)
    m.fit(df[FEATURES], df["target"])
    return m


def predict_mw(model, df: pd.DataFrame) -> np.ndarray:
    return df["lag_level"].to_numpy() * np.exp(model.predict(df[FEATURES]))


def mape(y, yhat) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float(np.mean(np.abs(yhat - y) / y) * 100)


def _calendar() -> dict:
    with open(CONFIG_DIR / "calendar.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def add_groups(df: pd.DataFrame, provinces: dict) -> pd.DataFrame:
    cal = _calendar()
    season = {m: s for s, ms in cal["seasons"].items() for m in ms}
    peak = set(cal["peak_hours_pkt"])
    df = df.copy()
    df["province"] = df["entity"].astype(str).map(provinces)
    df["season"] = df["period"].dt.month.map(season)
    df["hour_band"] = np.select(
        [df["hour"].isin(peak), df["hour"].between(0, 5), df["hour"].between(6, 11), df["hour"].between(12, 17)],
        ["evening peak 18-22", "night 00-05", "morning 06-11", "afternoon 12-17"], "late 23")
    return df


def group_errors(bt: pd.DataFrame, by: str) -> pd.DataFrame:
    g = bt.groupby(by, observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "model_mape": g.apply(lambda d: mape(d.y, d.pred), include_groups=False),
        "baseline_mape": g.apply(lambda d: mape(d.y, d.baseline), include_groups=False),
        "model_mae_mw": g.apply(lambda d: float(np.mean(np.abs(d.pred - d.y))), include_groups=False),
        "coverage_80": g.apply(lambda d: float(np.mean((d.y >= d.lo) & (d.y <= d.hi)) * 100), include_groups=False),
        "bias_pct": g.apply(lambda d: float((d.pred.sum() - d.y.sum()) / d.y.sum() * 100), include_groups=False),
    }).reset_index().rename(columns={by: "group_value"})
    out.insert(0, "group_by", by)
    out["improvement_pct"] = (1 - out["model_mape"] / out["baseline_mape"]) * 100
    return out


def rolling_residuals(actual: pd.DataFrame, clim: pd.DataFrame, params: dict, months) -> pd.DataFrame:
    """Out-of-sample log residuals: each month predicted by a model trained only on months
    published before its origin (<= t - 2), with ex-ante climatology inputs."""
    res = []
    for t in months:
        tr = actual[actual.period <= t - pd.DateOffset(months=2)].dropna(subset=["target"])
        te = clim[(clim.period == t)].dropna(subset=["target"])
        # need a few months of history and every feature observed at least once
        if tr.period.nunique() < 4 or te.empty or tr[FEATURES].isna().all().any():
            continue
        m = fit(tr, params)
        r = te[["entity", "period", "hour"]].copy()
        r["log_resid"] = te["target"].to_numpy() - m.predict(te[FEATURES])
        res.append(r)
    return pd.concat(res, ignore_index=True)


def run(verbose: bool = True) -> dict:
    t0 = time.time()
    ensure_dirs()
    con = connect()
    prof, wx = load_inputs(con)
    provinces = dict(con.execute("SELECT code, province FROM gold.entity").fetchall())

    actual = build_panel(prof, wx, weather_mode="actual").dropna(subset=["target"])
    clim = build_panel(prof, wx, weather_mode="climatology").dropna(subset=["target"])
    t_features = time.time() - t0

    # ---- hyper-parameters chosen on validation months only (ex-ante inputs)
    tune_tr = actual[actual.period <= TUNE_TRAIN_END]
    val = clim[clim.period.isin(VAL_MONTHS)]
    scores = []
    for p in PARAM_GRID:
        m = fit(tune_tr, p)
        scores.append({**p, "val_mape": mape(val.y, predict_mw(m, val))})
    scores = pd.DataFrame(scores).sort_values("val_mape")
    best = {k: (int(v) if k in ("max_leaf_nodes", "max_iter") else float(v))
            for k, v in scores.iloc[0].items() if k != "val_mape"}

    # ---- conformal calibration on rolling-origin residuals (train + validation months)
    cal_months = sorted(m for m in actual.period.unique() if m <= VAL_MONTHS[-1])
    resid = rolling_residuals(actual, clim, best, cal_months)
    q_lo, q_hi = np.quantile(resid["log_resid"], [ALPHA / 2, 1 - ALPHA / 2])

    # ---- final model and the single test evaluation
    t1 = time.time()
    final = fit(actual[actual.period <= FINAL_TRAIN_END], best)
    t_fit = time.time() - t1
    test_c = clim[(clim.period >= TEST_START) & (clim.period <= TEST_END)].copy()
    test_a = actual[(actual.period >= TEST_START) & (actual.period <= TEST_END)].copy()
    test_c["entity"] = test_c["entity"].astype(str)
    base = seasonal_naive(prof, test_c[["entity", "period", "hour"]])
    test_c["entity"] = pd.Categorical(test_c["entity"], categories=actual["entity"].cat.categories)

    bt = test_c[["row_id", "entity", "period", "hour", "y", "lag_period", "lag_level"]].copy()
    bt["entity"] = bt["entity"].astype(str)
    bt["pred"] = predict_mw(final, test_c)
    bt["lo"] = bt["pred"] * np.exp(q_lo)
    bt["hi"] = bt["pred"] * np.exp(q_hi)
    bt["pred_expost"] = predict_mw(final, test_a.set_index("row_id").loc[bt["row_id"]].reset_index())
    bt = bt.merge(base, on=["entity", "period", "hour"], how="left")
    bt = add_groups(bt, provinces)
    bt = bt.dropna(subset=["baseline"])

    peak = bt[bt.hour_band == "evening peak 18-22"]
    ke = bt[bt.entity == "KE"]
    metrics = {
        "test_months": sorted(bt.period.dt.strftime("%Y-%m").unique()),
        "n_test_rows": int(len(bt)),
        "baseline_mape": mape(bt.y, bt.baseline),
        "model_mape": mape(bt.y, bt.pred),
        "model_mape_expost_weather": mape(bt.y, bt.pred_expost),
        "improvement_pct": (1 - mape(bt.y, bt.pred) / mape(bt.y, bt.baseline)) * 100,
        "ke_baseline_mae_mw": float(np.mean(np.abs(ke.baseline - ke.y))),
        "ke_model_mae_mw": float(np.mean(np.abs(ke.pred - ke.y))),
        "ke_baseline_mape": mape(ke.y, ke.baseline),
        "ke_model_mape": mape(ke.y, ke.pred),
        "peak_baseline_mape": mape(peak.y, peak.baseline),
        "peak_model_mape": mape(peak.y, peak.pred),
        "coverage_80": float(np.mean((bt.y >= bt.lo) & (bt.y <= bt.hi)) * 100),
        "mean_interval_width_pct": float(np.mean((bt.hi - bt.lo) / bt.pred) * 100),
        "conformal_log_quantiles": [float(q_lo), float(q_hi)],
        "n_calibration_residuals": int(len(resid)),
        "best_params": best,
        "val_mape_best": float(scores.iloc[0]["val_mape"]),
        "train_rows_final": int((actual.period <= FINAL_TRAIN_END).sum()),
        "feature_build_s": round(t_features, 2), "final_fit_s": round(t_fit, 3),
        "trained_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": SEED,
    }
    metrics["declared_success"] = bool(metrics["improvement_pct"] >= 10 and metrics["ke_model_mape"] < metrics["ke_baseline_mape"])

    groups = pd.concat([group_errors(bt, by) for by in ("entity", "province", "season", "hour_band")],
                       ignore_index=True)
    worst = groups[groups.group_by == "entity"].sort_values("model_mape", ascending=False).iloc[0]
    metrics["weakest_entity"] = {"entity": worst.group_value, "model_mape": float(worst.model_mape)}

    # ---- save model + gold tables (every number the agent/dashboard shows comes from here)
    joblib.dump({"model": final, "features": FEATURES, "params": best, "q": [float(q_lo), float(q_hi)],
                 "categories": list(actual["entity"].cat.categories)}, MODELS_DIR / "bijlicast_hgb.joblib")
    bt_out = bt.copy()
    bt_out["row_id"] = "BT-" + bt_out["row_id"].str.removeprefix("DP-")
    bt_out["actual_row_id"] = bt["row_id"]
    bt_out["lag_period"] = bt_out["lag_period"].dt.date
    bt_out["period"] = bt_out["period"].dt.date
    for c in ("pred", "lo", "hi", "pred_expost", "baseline", "lag_level"):
        bt_out[c] = bt_out[c].round(2)
    _write(con, "gold", "backtest", bt_out)
    groups_out = groups.copy()
    groups_out.insert(0, "row_id", "EG-" + groups_out["group_by"].str.upper() + "-" +
                      groups_out["group_value"].astype(str).str.replace(r"[^A-Za-z0-9]+", "_", regex=True).str.upper())
    _write(con, "gold", "errors_by_group", groups_out.round(3))
    mrow = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in metrics.items()}
    _write(con, "gold", "model_metrics", pd.DataFrame([{"row_id": "MM-LATEST", **mrow}]))
    _write(con, "gold", "tuning_log", scores.round(4))
    con.close()
    with open(MODELS_DIR / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, default=str)
    groups_out.to_csv(REPORTS_DIR / "errors_by_group.csv", index=False)
    metrics["total_s"] = round(time.time() - t0, 2)
    if verbose:
        print(json.dumps({k: metrics[k] for k in ("baseline_mape", "model_mape", "model_mape_expost_weather",
                                                  "improvement_pct", "ke_baseline_mape", "ke_model_mape",
                                                  "peak_baseline_mape", "peak_model_mape", "coverage_80",
                                                  "declared_success", "weakest_entity", "best_params", "total_s")},
                         indent=1, default=str))
    return metrics


if __name__ == "__main__":
    run()
