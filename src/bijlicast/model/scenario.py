"""What-if scenarios: shift a month's temperature and re-forecast hourly demand.

The live weather for the month (observations + forecast + climatology, see forecast.py) is
shifted by `delta_c` degrees; the production model re-predicts every hour. Only temperature
moves - humidity, solar radiation and K-Electric's own generation are held fixed - so this is
the model's learned weather->demand response, not a full system simulation.

Cooling/heating degree-hours are monthly means of max(T-24, 0) / max(18-T, 0); after a shift
they are approximated from the hour's mean temperature with a 4-degree ramp (documented).
Shifts that push temperatures above anything seen in training are flagged: tree models flatten
outside the observed range, so large shifts are likely under-stated.
"""

from __future__ import annotations

from functools import lru_cache

import duckdb
import numpy as np
import pandas as pd

from ..serving import snapshot_path
from .features import build_panel, load_inputs
from .forecast import live_weather
from .production import load_live_model

ALLOWED = (-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 5.0)


def shift_weather(lw: pd.DataFrame, d: float) -> pd.DataFrame:
    w = lw.copy()
    t = w["temp_c"] + d / 2  # mid-point of the shift for the ramp
    above = np.clip((t - 22) / 4, 0, 1)   # share of hours plausibly above 24 C
    below = np.clip((20 - t) / 4, 0, 1)   # share of hours plausibly below 18 C
    w["temp_c"] = w["temp_c"] + d
    w["apparent_c"] = w["apparent_c"] + d
    w["cdh24"] = np.maximum(0.0, w["cdh24"] + d * above)
    w["hdh18"] = np.maximum(0.0, w["hdh18"] - d * below)
    return w


@lru_cache(maxsize=32)
def _inputs(month: str, snap_mtime: float):
    con = duckdb.connect(str(snapshot_path()), read_only=True)
    try:
        prof, wx = load_inputs(con)
        lw, cov = live_weather(con, wx, pd.Timestamp(month + "-01"))
    finally:
        con.close()
    return prof, wx, lw, cov


@lru_cache(maxsize=512)
def _cached(entity: str, month: str, delta: float, snap_mtime: float) -> dict:
    prof, wx, lw, cov = _inputs(month, snap_mtime)
    m = pd.Timestamp(month + "-01")
    lw = lw[lw.entity == entity]
    bundle = load_live_model()
    model, feats, (q_lo, q_hi) = bundle["model"], bundle["features"], bundle["q"]

    def predict(weather):
        p = build_panel(prof, wx, targets=[(entity, m)], weather_mode="live", live_wx=weather)
        if p.empty:
            return None, None
        p["entity"] = pd.Categorical(p["entity"].astype(str), categories=bundle["categories"])
        return p, p["lag_level"].to_numpy() * np.exp(model.predict(p[feats]))

    base_p, base = predict(lw)
    if base_p is None:
        return {"entity": entity, "month": month, "delta_c": delta, "hours": [],
                "empty_reason": f"No outlook for {entity} in {month}."}
    shifted = shift_weather(lw, delta)
    _, scen = predict(shifted)
    train_max = float(wx[(wx.entity == entity)]["temp_c"].max())
    scen_max = float(shifted["temp_c"].max())
    hours = [{"hour": int(h), "base": round(float(b), 1), "scen": round(float(s), 1),
              "lo": round(float(s * np.exp(q_lo)), 1), "hi": round(float(s * np.exp(q_hi)), 1),
              "temp_base": round(float(tb), 1), "temp_scen": round(float(ts), 1)}
             for h, b, s, tb, ts in zip(base_p["hour"], base, scen,
                                        lw.set_index("hour").loc[base_p["hour"], "temp_c"],
                                        shifted.set_index("hour").loc[base_p["hour"], "temp_c"])]
    bmean, smean = float(np.mean(base)), float(np.mean(scen))
    bpk, spk = int(np.argmax(base)), int(np.argmax(scen))
    return {
        "entity": entity, "month": month, "delta_c": delta, "hours": hours,
        "summary": {"base_mean_mw": round(bmean, 1), "scen_mean_mw": round(smean, 1),
                    "change_mw": round(smean - bmean, 1), "change_pct": round((smean / bmean - 1) * 100, 2),
                    "base_peak_mw": round(float(base[bpk]), 1), "base_peak_hour": int(base_p["hour"].iloc[bpk]),
                    "scen_peak_mw": round(float(scen[spk]), 1), "scen_peak_hour": int(base_p["hour"].iloc[spk]),
                    "peak_change_mw": round(float(scen[spk] - base[bpk]), 1)},
        "weather_coverage": float(cov.get(entity, 0.0)),
        "training_max_temp_c": round(train_max, 1), "scenario_max_temp_c": round(scen_max, 1),
        "outside_training_range": scen_max > train_max,
        "model_version": bundle["version"],
        "assumptions": "Only temperature shifts; humidity, solar radiation and K-Electric's own generation are held fixed. "
                       "Degree-hours after the shift are approximated with a 4-degree ramp.",
    }


def scenario(entity: str, month: str, delta_c: float, with_curve: bool = False) -> dict:
    d = float(delta_c)
    if d not in ALLOWED:
        raise ValueError(f"delta_c must be one of {ALLOWED}")
    mt = snapshot_path().stat().st_mtime
    out = dict(_cached(entity, month, d, mt))
    if with_curve and out.get("hours"):
        out["curve"] = []
        for x in ALLOWED:
            r = _cached(entity, month, x, mt)
            out["curve"].append({"delta_c": x, "mean_mw": r["summary"]["scen_mean_mw"],
                                 "change_pct": r["summary"]["change_pct"], "peak_mw": r["summary"]["scen_peak_mw"],
                                 "outside_training_range": r["outside_training_range"]})
    return out


if __name__ == "__main__":
    for d in ALLOWED:
        r = scenario("KE", pd.Timestamp.now().strftime("%Y-%m"), d)
        s = r["summary"]
        print(f"{d:+.0f}C  mean {s['scen_mean_mw']:,.0f} MW ({s['change_pct']:+.2f}%)  peak {s['scen_peak_mw']:,.0f} @ {s['scen_peak_hour']:02d}:00"
              f"  max temp {r['scenario_max_temp_c']} (train max {r['training_max_temp_c']}){'  OUTSIDE' if r['outside_training_range'] else ''}")
