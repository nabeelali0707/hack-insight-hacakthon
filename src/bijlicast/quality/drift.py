"""Drift monitor: does the data arriving now still look like the data the model learned from?

* weather drift: Population Stability Index (PSI) of this month's hourly temperatures
  (observed + forecast) against the same calendar month in the training years;
* level drift: latest published demand level against the range seen in training.
PSI < 0.1 stable, 0.1-0.25 watch, > 0.25 drifted (standard rule of thumb).
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..model.forecast import _hourly_obs
from ..model.train import FINAL_TRAIN_END
from ..warehouse import _write, connect


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    qs = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(qs) < 3:
        return 0.0
    qs[0], qs[-1] = -np.inf, np.inf
    e = np.histogram(expected, qs)[0] / len(expected)
    a = np.histogram(actual, qs)[0] / len(actual)
    e, a = np.clip(e, 1e-4, None), np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def status(v: float, watch: float, alert: float) -> str:
    return "DRIFT" if v > alert else ("WATCH" if v > watch else "STABLE")


def run(now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz="Asia/Karachi")
    month = pd.Timestamp(now.year, now.month, 1)
    con = connect()
    hist = con.execute("""SELECT entity, ts_utc + INTERVAL 5 HOUR AS ts_pkt, temp_c FROM cleaned.weather_hourly
                          WHERE month(ts_utc + INTERVAL 5 HOUR) = ? AND ts_utc + INTERVAL 5 HOUR < ?""",
                       [month.month, FINAL_TRAIN_END + pd.DateOffset(months=1)]).df()
    cur = _hourly_obs(con)
    cur = cur[cur.period == month]
    lv = con.execute("SELECT entity, period, avg(demand_mw) AS level FROM gold.demand_profile GROUP BY ALL").df()
    lv["period"] = pd.to_datetime(lv["period"])
    rows, ts = [], datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for ent in sorted(lv.entity.unique()):
        h, c = hist[hist.entity == ent]["temp_c"].dropna(), cur[cur.entity == ent]["temp_c"].dropna()
        if len(h) > 100 and len(c) > 24:
            v = psi(h.to_numpy(), c.to_numpy())
            rows.append({"row_id": f"DR-{ent}-TEMP-{month:%Y%m}", "entity": ent, "metric": "temperature PSI vs training",
                         "value": round(v, 3), "status": status(v, 0.10, 0.25),
                         "detail": f"{len(c)} current hours (mean {c.mean():.1f} C) vs {len(h)} training hours "
                                   f"(mean {h.mean():.1f} C) for {month:%B}"})
        tr = lv[(lv.entity == ent) & (lv.period <= FINAL_TRAIN_END)]["level"]
        latest = lv[lv.entity == ent].sort_values("period").iloc[-1]
        ratio = latest.level / tr.max()
        rows.append({"row_id": f"DR-{ent}-LEVEL-{latest.period:%Y%m}", "entity": ent,
                     "metric": "latest level / training max", "value": round(float(ratio), 3),
                     "status": "DRIFT" if ratio > 1.25 or latest.level < tr.min() * 0.8 else ("WATCH" if ratio > 1.0 else "STABLE"),
                     "detail": f"{latest.period:%b %Y} level {latest.level:,.0f} MW vs training range "
                               f"{tr.min():,.0f}-{tr.max():,.0f} MW"})
    out = pd.DataFrame(rows)
    out["checked_at_utc"] = ts
    _write(con, "gold", "drift_status", out)
    con.close()
    return out


if __name__ == "__main__":
    print(run().to_string())
