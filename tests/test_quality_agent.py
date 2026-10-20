"""Unit tests for the Data Quality Agent's decision rules.

The frames below are tiny hand-made TEST FIXTURES (labelled as such, never used for training or
evaluation); they exist only to check that each rule picks FIX / FILL / FLAG correctly."""

import numpy as np
import pandas as pd

from bijlicast.quality import DataQualityAgent


def _profile(entity, period, base):
    return pd.DataFrame({"entity": entity, "period": pd.Timestamp(period), "hour": range(24),
                         "demand_mw": [float(base + h) for h in range(24)], "dq_flags": "", "exclude": False})


def test_copied_month_is_flagged_and_excluded():
    agent = DataQualityAgent("test")
    p = pd.concat([_profile("KE", "2024-06-01", 1000), _profile("KE", "2024-07-01", 1000),
                   _profile("KE", "2024-08-01", 1100)], ignore_index=True)
    out = agent._check_copied_profiles(p)
    assert out.loc[out.period == "2024-07-01", "exclude"].all()
    assert not out.loc[out.period == "2024-08-01", "exclude"].any()
    d = [x for x in agent.decisions if x.check_id == "DQ-ISMO-COPY"]
    assert len(d) == 1 and d[0].action == "FLAG" and d[0].needs_review


def test_stale_energy_value_repeated_from_any_earlier_month():
    agent = DataQualityAgent("test")
    e = pd.DataFrame({"entity": ["KE", "KE", "KE", "LESCO", "LESCO", "LESCO"],
                      "period": pd.to_datetime(["2025-03-01", "2025-04-01", "2025-10-01"] * 2),
                      "avg_daily_mwh": [31676.0, 30000.0, 31676.0, 50000.0, 51000.0, 52000.0],
                      "dq_flags": "", "exclude": False})
    out = agent._check_stale_energy(e)
    stale = out[out.exclude]
    assert list(stale.entity) == ["KE"] and stale.period.iloc[0] == pd.Timestamp("2025-10-01")


def test_monthly_total_unit_basis_is_fixed():
    agent = DataQualityAgent("test")
    e = pd.DataFrame({"file_id": "f", "period": "2025-05", "entity": ["KE", "LESCO"],
                      "avg_mwh": [31079.2, 85576.0], "total_energy_gwh": [963.5, 2652.9], "share": [0.1, 0.2]})
    out = agent._fix_energy_basis(e, {"period": "2025-05", "file_id": "f"})
    assert np.allclose(out.energy_daily_gwh, [31.0792, 85.576])
    assert any(d.check_id == "DQ-ISMO-UNIT" and d.action == "FIX" for d in agent.decisions)


def test_weather_short_gap_filled_long_gap_flagged():
    agent = DataQualityAgent("test")
    ts = pd.date_range("2025-01-01", periods=48, freq="h", tz="UTC")
    temp = np.linspace(10, 20, 48)
    df = pd.DataFrame({"file_id": "f", "entity": "KE", "ts_utc": ts, "temp_c": temp, "rh_pct": 50.0,
                       "dewpoint_c": 5.0, "apparent_c": temp, "precip_mm": 0.0, "cloud_pct": 10.0,
                       "wind_kmh": 5.0, "swrad_wm2": 0.0})
    df.loc[5:6, "temp_c"] = np.nan          # 2-hour gap -> FILL
    df.loc[20:29, "temp_c"] = np.nan        # 10-hour gap -> FLAG, kept missing
    out = agent.review_weather(df)
    assert out.loc[5:6, "is_filled"].all() and out.loc[5:6, "temp_c"].notna().all()
    assert out.loc[20:29, "temp_c"].isna().all()
    actions = {d.check_id: d.action for d in agent.decisions}
    assert actions["DQ-WX-FILL"] == "FILL" and actions["DQ-WX-GAP"] == "FLAG"


def test_price_converted_to_utc():
    agent = DataQualityAgent("test")
    df = pd.DataFrame({"file_id": "f", "date_pkt": ["2025-01-01"] * 3, "hour_pkt": [0, 1, 2],
                       "price_rs_kwh": [20.0, 21.0, 22.0]})
    out = agent.review_price(df)
    assert str(out.ts_utc.iloc[0]) == "2024-12-31 19:00:00+00:00"
