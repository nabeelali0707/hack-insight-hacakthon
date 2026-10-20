"""The declared baseline (docs/baseline_declaration.md), implemented exactly as written:

seasonal naive: y_hat(e, m, h) = y(e, m - 12 months, h);
fallback when m - 12 is not published/usable: the latest month already published at the
forecast origin (<= m - 2), same hour.
"""

from __future__ import annotations

import pandas as pd

from .features import MIN_LAG, _months_between


def seasonal_naive(prof: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """targets: DataFrame with entity, period, hour. Returns it with baseline + baseline_source."""
    val = prof.set_index(["entity", "period", "hour"])["demand_mw"]
    avail = {e: sorted(g["period"].unique()) for e, g in prof.groupby("entity")}
    out = targets[["entity", "period", "hour"]].copy()
    preds, srcs = [], []
    for ent, m, h in out.itertuples(index=False):
        ent = str(ent)
        ly = m - pd.DateOffset(years=1)
        if (ent, ly, h) in val.index:
            preds.append(float(val[(ent, ly, h)])); srcs.append(f"same month last year ({ly:%Y-%m})")
            continue
        past = [p for p in avail.get(ent, []) if _months_between(m, p) >= MIN_LAG]
        if past:
            preds.append(float(val[(ent, past[-1], h)])); srcs.append(f"fallback: latest published ({past[-1]:%Y-%m})")
        else:
            preds.append(float("nan")); srcs.append("unavailable")
    out["baseline"] = preds
    out["baseline_source"] = srcs
    return out
