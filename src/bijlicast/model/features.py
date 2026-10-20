"""Feature panel: one row per (entity, target month, hour PKT).

Information discipline (no leakage):
* demand lags come only from months ISMO had published at the forecast origin: the latest
  usable month <= m - 2 (ISMO publishes month m around the 15th of m + 1);
* target-month weather is either the ACTUAL month (training the weather->demand relation,
  and ex-post analysis) or CLIMATOLOGY built only from earlier years (ex-ante evaluation,
  i.e. what a planner can know a month ahead), or LIVE (observed + forecast + climatology).
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
        df["period"] = pd.to_datetime(df["period"])
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


def build_panel(prof: pd.DataFrame, wx: pd.DataFrame, targets: list[tuple[str, pd.Timestamp]] | None = None,
                weather_mode: str = "actual", live_wx: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return one row per (entity, period, hour) with target (if known) and features.

    targets: (entity, period) pairs to build; default = every published entity-month.
    weather_mode: 'actual' | 'climatology' | 'live' (live_wx gives entity, hour, WX_VARS for the target month).
    """
    level = prof.groupby(["entity", "period"])["demand_mw"].mean().rename("level")
    wide = prof.pivot_table(index=["entity", "period"], columns="hour", values="demand_mw")
    shape = wide.div(level, axis=0)
    avail = {e: sorted(g.index.get_level_values("period")) for e, g in level.groupby(level="entity")}
    wx_idx = wx.set_index(["entity", "period", "hour"])
    wx_month = wx.groupby(["entity", "period"])[["cdh24"]].mean()
    clim_cache: dict[int, pd.DataFrame] = {}

    if targets is None:
        targets = list(level.index)
    rows = []
    for ent, m in targets:
        past = [p for p in avail.get(ent, []) if _months_between(m, p) >= MIN_LAG]
        if not past:
            continue
        lag = past[-1]
        ly, lag_ly = m - pd.DateOffset(years=1), lag - pd.DateOffset(years=1)
        has_ly = (ent, ly) in shape.index and _months_between(m, ly) >= MIN_LAG
        ly_ratio = (level[(ent, ly)] / level[(ent, lag_ly)]) if has_ly and (ent, lag_ly) in level.index else np.nan

        if weather_mode == "actual":
            tw = wx[(wx.entity == ent) & (wx.period == m)].set_index("hour")[WX_VARS]
        elif weather_mode == "climatology":
            if m.year not in clim_cache:
                clim_cache[m.year] = climatology(wx, m.year)
            c = clim_cache[m.year]
            tw = c[(c.entity == ent) & (c.moy == m.month)].set_index("hour")[WX_VARS]
        elif weather_mode == "live":
            tw = live_wx[live_wx.entity == ent].set_index("hour")[WX_VARS]
        else:
            raise ValueError(weather_mode)
        if len(tw) < 24:
            continue
        lw = wx_idx.loc[(ent, lag)][WX_VARS] if (ent, lag, 0) in wx_idx.index else None
        if lw is None:
            continue
        lag_cdh_month = float(wx_month.loc[(ent, lag), "cdh24"])
        lvl = float(level[(ent, lag)])
        r_m, r_lag = ramadan_fraction(m), ramadan_fraction(lag)
        for h in range(24):
            y = wide.loc[(ent, m), h] if (ent, m) in wide.index else np.nan
            rid = f"DP-{ent}-{m:%Y%m}-{h:02d}"
            rows.append({
                "row_id": rid, "entity": ent, "period": m, "hour": h, "lag_period": lag, "lag_level": lvl,
                "y": y, "lag_gap": _months_between(m, lag), "lag_shape": float(shape.loc[(ent, lag), h]),
                "lag_value": float(wide.loc[(ent, lag), h]),
                "ly_shape": float(shape.loc[(ent, ly), h]) if has_ly else np.nan,
                "ly_seasonal_ratio": ly_ratio,
                "moy_sin": np.sin(2 * np.pi * m.month / 12), "moy_cos": np.cos(2 * np.pi * m.month / 12),
                **{v: float(tw.loc[h, v]) for v in WX_VARS},
                "d_temp": float(tw.loc[h, "temp_c"] - lw.loc[h, "temp_c"]),
                "d_apparent": float(tw.loc[h, "apparent_c"] - lw.loc[h, "apparent_c"]),
                "d_cdh": float(tw.loc[h, "cdh24"] - lw.loc[h, "cdh24"]),
                "d_cdh_month": float(tw["cdh24"].mean() - lag_cdh_month),
                "d_swrad": float(tw.loc[h, "swrad_wm2"] - lw.loc[h, "swrad_wm2"]),
                "ramadan_frac": r_m, "ramadan_frac_lag": r_lag,
            })
    panel = pd.DataFrame(rows)
    if not panel.empty:
        panel["target"] = np.log(panel["y"] / panel["lag_level"])
        panel["entity"] = pd.Categorical(panel["entity"])
    return panel
