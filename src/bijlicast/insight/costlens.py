"""Peak Cost Lens: what each hour of demand costs at ISMO's system marginal price, what a
small peak-to-off-peak shift would save, and how much money a forecast error puts at risk.

All inputs are gold tables; outputs are gold tables with row IDs, so the Insight Agent can
cite every rupee. Marginal price is the system's cost of the last MWh in that hour (ISMO),
an indicator of cost - not K-Electric's tariff or actual purchase price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..warehouse import _write, connect

SHIFT_PCT = 0.05   # move 5% of demand out of the 3 most expensive hours
N_HOURS = 3


def run() -> dict[str, pd.DataFrame]:
    con = connect()
    dp = con.execute("SELECT row_id, entity, period, hour_pkt, demand_mw FROM gold.demand_profile").df()
    pm = con.execute("SELECT row_id AS price_row_id, period, hour_pkt, avg_price_rs_kwh FROM gold.price_month_hour").df()
    m = dp.merge(pm, on=["period", "hour_pkt"], how="inner")
    m["cost_rs"] = m["demand_mw"] * 1000 * m["avg_price_rs_kwh"]

    rows = []
    for (ent, per), g in m.groupby(["entity", "period"]):
        if len(g) < 24:
            continue
        g = g.sort_values("avg_price_rs_kwh")
        cheap, dear = g.head(N_HOURS), g.tail(N_HOURS)
        shift_mwh = (dear["demand_mw"] * SHIFT_PCT).sum()
        saving = (dear["demand_mw"] * SHIFT_PCT * 1000 * dear["avg_price_rs_kwh"]).sum() \
            - shift_mwh * 1000 * cheap["avg_price_rs_kwh"].mean()
        peak = g[g.hour_pkt.between(18, 22)]
        energy = g["demand_mw"].sum()
        cost = g["cost_rs"].sum()
        days = pd.Timestamp(per).days_in_month
        rows.append({
            "row_id": f"PC-{ent}-{pd.Timestamp(per):%Y%m}", "entity": ent, "period": per,
            "daily_energy_mwh": round(energy, 1), "daily_cost_rs_m": round(cost / 1e6, 2),
            "weighted_price_rs_kwh": round(cost / (energy * 1000), 3),
            "evening_peak_energy_share_pct": round(peak["demand_mw"].sum() / energy * 100, 1),
            "evening_peak_cost_share_pct": round(peak["cost_rs"].sum() / cost * 100, 1),
            "dearest_hours": ",".join(str(h) for h in sorted(dear.hour_pkt)),
            "cheapest_hours": ",".join(str(h) for h in sorted(cheap.hour_pkt)),
            "dearest_price_rs_kwh": round(dear["avg_price_rs_kwh"].mean(), 3),
            "cheapest_price_rs_kwh": round(cheap["avg_price_rs_kwh"].mean(), 3),
            "shift_pct": SHIFT_PCT * 100, "shift_mwh_per_day": round(shift_mwh, 1),
            "shift_saving_rs_m_per_day": round(saving / 1e6, 3),
            "shift_saving_rs_m_per_month": round(saving * days / 1e6, 2),
            "source_rows": f"DP-{ent}-{pd.Timestamp(per):%Y%m}-00..23; PM-{pd.Timestamp(per):%Y%m}-00..23",
        })
    pc = pd.DataFrame(rows)
    _write(con, "gold", "peak_cost", pc)

    # value of accuracy: energy mismatch priced at the marginal price of that month-hour
    bt = con.execute("SELECT entity, period, hour AS hour_pkt, y, pred, baseline FROM gold.backtest").df()
    e = bt.merge(pm, on=["period", "hour_pkt"], how="inner")
    e["model_risk_rs"] = (e["pred"] - e["y"]).abs() * 1000 * e["avg_price_rs_kwh"]
    e["base_risk_rs"] = (e["baseline"] - e["y"]).abs() * 1000 * e["avg_price_rs_kwh"]
    ec = e.groupby(["entity", "period"], as_index=False).agg(
        model_mismatch_mwh=("pred", lambda s: float(np.abs(s - e.loc[s.index, "y"]).sum())),
        baseline_mismatch_mwh=("baseline", lambda s: float(np.abs(s - e.loc[s.index, "y"]).sum())),
        model_risk_rs_m_per_day=("model_risk_rs", lambda s: s.sum() / 1e6),
        baseline_risk_rs_m_per_day=("base_risk_rs", lambda s: s.sum() / 1e6))
    ec["risk_reduction_rs_m_per_day"] = ec["baseline_risk_rs_m_per_day"] - ec["model_risk_rs_m_per_day"]
    ec.insert(0, "row_id", "EC-" + ec["entity"] + "-" + pd.to_datetime(ec["period"]).dt.strftime("%Y%m"))
    ec = ec.round(3)
    _write(con, "gold", "error_cost", ec)
    con.close()
    return {"peak_cost": pc, "error_cost": ec}


if __name__ == "__main__":
    out = run()
    pc, ec = out["peak_cost"], out["error_cost"]
    print(pc[pc.entity == "KE"].tail(4)[["row_id", "daily_cost_rs_m", "evening_peak_cost_share_pct", "dearest_hours",
                                         "cheapest_hours", "shift_saving_rs_m_per_month"]].to_string())
    print(ec.groupby("entity")[["model_risk_rs_m_per_day", "baseline_risk_rs_m_per_day", "risk_reduction_rs_m_per_day"]]
          .mean().round(2).sort_values("risk_reduction_rs_m_per_day").to_string())
