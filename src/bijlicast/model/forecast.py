"""Live outlook: hourly demand profile forecasts for the current and next month, refreshed
every pipeline run as weather observations and forecasts arrive.

Weather input for target month m, per entity and hour (priority order, per calendar day):
  1. observed ERA5 hours (cleaned.weather_hourly),
  2. latest Open-Meteo snapshot (analysis for past days + forecast up to 16 days),
  3. climatology from earlier years for the days not yet covered.
The share of days covered by 1+2 is stored as `weather_coverage` so users see how much of
the outlook is driven by real forecasts versus climatology.
"""

from __future__ import annotations

from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from ..config import MODELS_DIR
from ..warehouse import _write, connect
from .features import WX_VARS, build_panel, climatology, load_inputs


def _hourly_obs(con) -> pd.DataFrame:
    """Best available hourly weather (observed ERA5, then latest live snapshot), PKT."""
    arch = con.execute("""SELECT entity, ts_utc, temp_c, apparent_c, rh_pct, dewpoint_c, swrad_wm2, cloud_pct, 1 AS pri
                          FROM cleaned.weather_hourly WHERE ts_utc >= now() - INTERVAL 75 DAY""").df()
    live = con.execute("""SELECT entity, ts_utc, temp_c, apparent_c, rh_pct, dewpoint_c, swrad_wm2, cloud_pct, 2 AS pri
                          FROM cleaned.weather_live""").df()
    w = pd.concat([arch, live], ignore_index=True).dropna(subset=["temp_c"])
    w = w.sort_values("pri").drop_duplicates(["entity", "ts_utc"], keep="first")
    w["ts_pkt"] = pd.to_datetime(w["ts_utc"]).dt.tz_convert("Asia/Karachi").dt.tz_localize(None)
    w["period"] = w["ts_pkt"].dt.to_period("M").dt.to_timestamp()
    w["hour"] = w["ts_pkt"].dt.hour
    w["cdh24"] = (w["temp_c"] - 24).clip(lower=0)
    w["hdh18"] = (18 - w["temp_c"]).clip(lower=0)
    return w


def live_weather(con, wx_month_hour: pd.DataFrame, month: pd.Timestamp) -> tuple[pd.DataFrame, pd.Series]:
    obs = _hourly_obs(con)
    obs = obs[obs.period == month]
    clim = climatology(wx_month_hour, month.year)
    clim = clim[clim.moy == month.month].drop(columns="moy")
    days = month.days_in_month
    out, cov = [], {}
    for ent, c in clim.groupby("entity"):
        o = obs[obs.entity == ent]
        n_days = o["ts_pkt"].dt.date.nunique()
        cov[ent] = min(n_days / days, 1.0)
        om = o.groupby("hour")[WX_VARS].mean() if len(o) else None
        cnt = o.groupby("hour").size() if len(o) else None
        c = c.set_index("hour")[WX_VARS]
        if om is None:
            blended = c
        else:
            w = (cnt.reindex(c.index).fillna(0) / days).clip(upper=1.0)
            blended = c.mul(1 - w, axis=0) + om.reindex(c.index).fillna(c).mul(w, axis=0)
        b = blended.reset_index()
        b["entity"] = ent
        out.append(b)
    return pd.concat(out, ignore_index=True), pd.Series(cov, name="weather_coverage")


def run(now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz="Asia/Karachi")
    con = connect()
    prof, wx = load_inputs(con)
    bundle = joblib.load(MODELS_DIR / "bijlicast_hgb.joblib")
    model, feats, (q_lo, q_hi) = bundle["model"], bundle["features"], bundle["q"]
    this_month = pd.Timestamp(now.year, now.month, 1)
    rows = []
    snapshot = con.execute("SELECT max(snapshot_utc) FROM cleaned.weather_live").fetchone()[0]
    for month in (this_month, this_month + pd.DateOffset(months=1)):
        lw, cov = live_weather(con, wx, month)
        targets = [(e, month) for e in sorted(prof.entity.unique())]
        panel = build_panel(prof, wx, targets=targets, weather_mode="live", live_wx=lw)
        if panel.empty:
            continue
        panel["entity"] = pd.Categorical(panel["entity"].astype(str), categories=bundle["categories"])
        pred = panel["lag_level"].to_numpy() * np.exp(model.predict(panel[feats]))
        out = panel[["entity", "period", "hour", "lag_period", "lag_level", "temp_c", "cdh24"]].copy()
        out["entity"] = out["entity"].astype(str)
        out["pred_mw"], out["lo_mw"], out["hi_mw"] = pred, pred * np.exp(q_lo), pred * np.exp(q_hi)
        out["weather_coverage"] = out["entity"].map(cov)
        rows.append(out)
    fc = pd.concat(rows, ignore_index=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fc.insert(0, "row_id", "FC-" + fc["entity"] + "-" + fc["period"].dt.strftime("%Y%m") + "-" + fc["hour"].map("{:02d}".format))
    fc["generated_at_utc"] = gen
    fc["weather_snapshot_utc"] = str(snapshot)
    fc["model_version"] = f"hgb-{bundle['params']['max_iter']}r"
    for c in ("pred_mw", "lo_mw", "hi_mw", "lag_level", "temp_c", "cdh24"):
        fc[c] = fc[c].round(2)
    fc["period"] = fc["period"].dt.date
    fc["lag_period"] = pd.to_datetime(fc["lag_period"]).dt.date
    _write(con, "gold", "forecast_outlook", fc)
    hist = fc.copy()
    hist["row_id"] = hist["row_id"] + "@" + gen
    con.register("_h", hist)
    con.execute("CREATE TABLE IF NOT EXISTS gold.forecast_history AS SELECT * FROM _h WHERE 1=0")
    con.execute("INSERT INTO gold.forecast_history SELECT * FROM _h")
    con.unregister("_h")
    con.close()
    return fc


if __name__ == "__main__":
    f = run()
    ke = f[f.entity == "KE"]
    print(ke.groupby("period").agg(mean_mw=("pred_mw", "mean"), peak_mw=("pred_mw", "max"),
                                   coverage=("weather_coverage", "first"), lag=("lag_period", "first")))
