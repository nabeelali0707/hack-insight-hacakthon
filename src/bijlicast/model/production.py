"""Production model for the LIVE outlook (human-approved retrain).

The evaluated model (models/bijlicast_hgb.joblib, trained on targets <= Nov 2025) stays exactly
as it is: every reported score, backtest row and figure refers to it. After evaluation, the
standard practice is to refit the same specification on all data available, so live forecasts
learn from the newest months (K-Electric's grid draw rose above anything in the evaluation
training set - drift row DR-KE-LEVEL-*).

* Same features and hyper-parameters as the evaluated model (no re-tuning).
* Trained on every published month (targets up to the latest ISMO month).
* 80% intervals re-calibrated on rolling-origin out-of-sample residuals over ALL months: each
  month is forecast by a model trained only on months published before it (<= t - 2).
* Reads the read-only serving snapshot, writes only models/ - never the live warehouse.

    python -m bijlicast.model.production --approved-by "<name>"
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import duckdb
import joblib
import numpy as np
import pandas as pd

from ..config import MODELS_DIR
from ..serving import snapshot_path
from .features import FEATURES, build_panel, load_inputs
from .train import ALPHA, fit, mape, predict_mw, rolling_residuals

EVAL_PATH = MODELS_DIR / "bijlicast_hgb.joblib"
PROD_PATH = MODELS_DIR / "bijlicast_prod.joblib"
PROD_META = MODELS_DIR / "production.json"


def load_live_model() -> dict:
    """The model the live outlook uses: the approved production model if present, else the evaluated one."""
    if PROD_PATH.exists():
        b = joblib.load(PROD_PATH)
        b.setdefault("version", f"hgb-{b['params']['max_iter']}r-prod-{b['trained_through']}")
        return b
    b = joblib.load(EVAL_PATH)
    b.setdefault("version", f"hgb-{b['params']['max_iter']}r")
    return b


def run(approved_by: str, note: str = "") -> dict:
    con = duckdb.connect(str(snapshot_path()), read_only=True)
    prof, wx = load_inputs(con)
    con.close()
    actual = build_panel(prof, wx, weather_mode="actual").dropna(subset=["target"])
    clim = build_panel(prof, wx, weather_mode="climatology").dropna(subset=["target"])
    ev = joblib.load(EVAL_PATH)
    params = ev["params"]

    months = sorted(actual.period.unique())
    resid = rolling_residuals(actual, clim, params, months)
    q_lo, q_hi = np.quantile(resid["log_resid"], [ALPHA / 2, 1 - ALPHA / 2])
    recent = resid[resid.period >= pd.Timestamp("2026-01-01")]
    inside = lambda r, lo, hi: float(((r.log_resid >= lo) & (r.log_resid <= hi)).mean() * 100)

    model = fit(actual, params)
    through = pd.Timestamp(max(months)).strftime("%Y-%m")
    in_sample = mape(actual["y"], predict_mw(model, actual))
    bundle = {"model": model, "features": FEATURES, "params": params, "q": [float(q_lo), float(q_hi)],
              "categories": list(actual["entity"].cat.categories), "kind": "production",
              "trained_through": through, "version": f"hgb-{params['max_iter']}r-prod-{through}"}
    joblib.dump(bundle, PROD_PATH)
    meta = {
        "kind": "production (live outlook only; all reported scores use the evaluated model)",
        "approved_by": approved_by, "approval_note": note,
        "approved_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trained_through": through, "training_months": len(months), "training_rows": int(len(actual)),
        "params": params, "version": bundle["version"],
        "conformal_log_quantiles": [round(float(q_lo), 4), round(float(q_hi), 4)],
        "evaluated_model_quantiles": [round(float(x), 4) for x in ev["q"]],
        "n_calibration_residuals": int(len(resid)),
        "coverage_with_new_intervals_all_months": round(inside(resid, q_lo, q_hi), 1),
        "coverage_2026_months_old_intervals": round(inside(recent, *ev["q"]), 1),
        "coverage_2026_months_new_intervals": round(inside(recent, q_lo, q_hi), 1),
        "in_sample_mape_not_a_test_score": round(in_sample, 2),
    }
    PROD_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-by", required=True, help="person approving the model replacement")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    print(json.dumps(run(a.approved_by, a.note), indent=2))
