"""Feature panel: one row per (entity, target month, hour PKT).

Information discipline (no leakage):
* demand lags come only from months ISMO had published at the forecast origin: the latest
  usable month <= m - 2 (ISMO publishes month m around the 15th of m + 1);
* target-month weather is either the ACTUAL month (training the weather->demand relation,
  and ex-post analysis) or CLIMATOLOGY built only from earlier years (ex-ante evaluation,
  i.e. what a planner can know a month ahead), or LIVE (observed + forecast + climatology).

Vectorised with merges (optimization log OPT-12: ~50x faster than the row loop it replaced).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR

WX_VARS = ["temp_c", "apparent_c", "rh_pct", "dewpoint_c", "swrad_wm2", "cloud_pct", "cdh24", "hdh18"]
FEATURES = [
    "entity", "hour", "moy_sin", "moy_cos", "lag_gap", "lag_shape", "ly_shape", "ly_seasonal_ratio",
    "temp_c", "apparent_c", "rh_pct", "swrad_wm2", "cdh24", "hdh18",
    "d_temp", "d_apparent", "d_cdh", "d_cdh_month", "d_swrad", "ramadan_frac", "ramadan_frac_lag",
]
MIN_LAG = 2


def load_inputs(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    prof = con.execute("""SELECT entity, period, hour_pkt AS hour, demand_mw, row_id
                          FROM gold.demand_profile""").df()
    wx = con.execute(f"""SELECT entity, period, hour_pkt AS hour, {', '.join(WX_VARS)}
                         FROM gold.weather_month_hour""").df()
    for df in (prof, wx):
        df["period"] = pd.to_datetime(df["period"]).astype("datetime64[ns]")
        df["hour"] = df["hour"].astype(int)
    return prof, wx


@lru_cache(maxsize=1)
def _calendar() -> dict:
    with open(CONFIG_DIR / "calendar.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=256)
def ramadan_fraction(period: pd.Timestamp) -> float:
    days = pd.date_range(period, period + pd.offsets.MonthEnd(0), freq="D")
    inside = np.zeros(len(days), dtype=bool)
    for r in _calendar()["ramadan"]:
        inside |= (days >= pd.Timestamp(r["start"])) & (days <= pd.Timestamp(r["end"]))
    return float(inside.mean())


def climatology(wx: pd.DataFrame, year: int) -> pd.DataFrame:
    """Mean weather per (entity, month-of-year, hour) using only years strictly before `year`."""
    past = wx[wx["period"].dt.year < year]
    clim = past.groupby([past["entity"], past["period"].dt.month.rename("moy"), past["hour"]])[WX_VARS].mean()
    return clim.reset_index()


def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (a.year - b.year) * 12 + (a.month - b.month)


def _mdiff(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.dt.year - b.dt.year) * 12 + (a.dt.month - b.dt.month)


def build_panel(prof: pd.DataFrame, wx: pd.DataFrame, targets: list[tuple[str, pd.Timestamp]] | None = None,
                weather_mode: str = "actual", live_wx: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return one row per (entity, period, hour) with target (if known) and features.

    targets: (entity, period) pairs to build; default = every published entity-month.
    weather_mode: 'actual' | 'climatology' | 'live' (live_wx: entity, hour, WX_VARS for the target month).
    """
    level = prof.groupby(["entity", "period"], as_index=False)["demand_mw"].mean().rename(columns={"demand_mw": "level"})
    long = prof[["entity", "period", "hour", "demand_mw"]].merge(level, on=["entity", "period"])
    long["shape"] = long["demand_mw"] / long["level"]

    if targets is None:
        tg = level[["entity", "period"]].copy()
    else:
        tg = pd.DataFrame(targets, columns=["entity", "period"])
        tg["period"] = pd.to_datetime(tg["period"]).astype("datetime64[ns]")
    tg["entity"] = tg["entity"].astype(str)
    tg["origin"] = tg["period"] - pd.DateOffset(months=MIN_LAG)

    # latest published month <= m - 2, per entity
    av = level.rename(columns={"period": "lag_period", "level": "lag_level"}).sort_values("lag_period")
    tg = pd.merge_asof(tg.sort_values("origin"), av, left_on="origin", right_on="lag_period",
                       by="entity", direction="backward").dropna(subset=["lag_period"])
    tg["lag_gap"] = _mdiff(tg["period"], tg["lag_period"])
    tg["ly_period"] = tg["period"] - pd.DateOffset(years=1)
    tg["lag_ly_period"] = tg["lag_period"] - pd.DateOffset(years=1)
    lv = level.set_index(["entity", "period"])["level"]
    ly_lvl = pd.Series(lv.reindex(list(zip(tg.entity, tg.ly_period))).to_numpy(), index=tg.index)
    lag_ly_lvl = pd.Series(lv.reindex(list(zip(tg.entity, tg.lag_ly_period))).to_numpy(), index=tg.index)
    tg["ly_seasonal_ratio"] = ly_lvl / lag_ly_lvl
    tg["has_ly"] = ly_lvl.notna()

    # explode to 24 hours
    p = tg.merge(pd.DataFrame({"hour": range(24)}), how="cross")
    p = p.merge(long[["entity", "period", "hour", "demand_mw"]].rename(columns={"demand_mw": "y"}),
                on=["entity", "period", "hour"], how="left")
    p = p.merge(long[["entity", "period", "hour", "shape", "demand_mw"]].rename(
        columns={"period": "lag_period", "shape": "lag_shape", "demand_mw": "lag_value"}),
        on=["entity", "lag_period", "hour"], how="left")
    p = p.merge(long[["entity", "period", "hour", "shape"]].rename(columns={"period": "ly_period", "shape": "ly_shape"}),
                on=["entity", "ly_period", "hour"], how="left")
    p.loc[~p["has_ly"], "ly_shape"] = np.nan

    # target-month weather
    if weather_mode == "actual":
        p = p.merge(wx, on=["entity", "period", "hour"], how="left")
    elif weather_mode == "climatology":
        parts = []
        for year in sorted(p["period"].dt.year.unique()):
            c = climatology(wx, int(year)); c["year"] = year; parts.append(c)
        clim = pd.concat(parts, ignore_index=True)
        p["moy"], p["year"] = p["period"].dt.month, p["period"].dt.year
        p = p.merge(clim, on=["entity", "moy", "hour", "year"], how="left").drop(columns=["moy", "year"])
    elif weather_mode == "live":
        p = p.merge(live_wx[["entity", "hour"] + WX_VARS], on=["entity", "hour"], how="left")
    else:
        raise ValueError(weather_mode)

    # lag-month (actual, known) weather and deltas
    lw = wx.rename(columns={"period": "lag_period", **{v: f"lag_{v}" for v in WX_VARS}})
    p = p.merge(lw, on=["entity", "lag_period", "hour"], how="left")
    lag_cdh_m = wx.groupby(["entity", "period"], as_index=False)["cdh24"].mean().rename(
        columns={"period": "lag_period", "cdh24": "lag_cdh_month"})
    p = p.merge(lag_cdh_m, on=["entity", "lag_period"], how="left")
    p["tgt_cdh_month"] = p.groupby(["entity", "period"])["cdh24"].transform("mean")
    p["d_temp"] = p["temp_c"] - p["lag_temp_c"]
    p["d_apparent"] = p["apparent_c"] - p["lag_apparent_c"]
    p["d_cdh"] = p["cdh24"] - p["lag_cdh24"]
    p["d_cdh_month"] = p["tgt_cdh_month"] - p["lag_cdh_month"]
    p["d_swrad"] = p["swrad_wm2"] - p["lag_swrad_wm2"]

    p["moy_sin"] = np.sin(2 * np.pi * p["period"].dt.month / 12)
    p["moy_cos"] = np.cos(2 * np.pi * p["period"].dt.month / 12)
    rf = {d: ramadan_fraction(pd.Timestamp(d)) for d in pd.concat([p["period"], p["lag_period"]]).unique()}
    p["ramadan_frac"] = p["period"].map(rf)
    p["ramadan_frac_lag"] = p["lag_period"].map(rf)

    # need complete weather for the target and lag months
    p = p.dropna(subset=["temp_c", "lag_temp_c", "lag_shape"])
    complete = p.groupby(["entity", "period"])["hour"].transform("size") == 24
    p = p[complete].copy()
    p["row_id"] = "DP-" + p["entity"] + "-" + p["period"].dt.strftime("%Y%m") + "-" + p["hour"].map("{:02d}".format)
    p["target"] = np.log(p["y"] / p["lag_level"])
    cols = ["row_id", "entity", "period", "hour", "lag_period", "lag_level", "y", "lag_value"] + \
           [f for f in FEATURES if f not in ("entity", "hour")] + ["target"]
    p = p[cols].sort_values(["entity", "period", "hour"]).reset_index(drop=True)
    p["entity"] = pd.Categorical(p["entity"])
    return p
