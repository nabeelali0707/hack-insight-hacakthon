"""The web API serves real gold data, never invented values, and the frontend shell is reachable."""

import pytest

from conftest import needs_index, needs_warehouse


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from bijlicast.api import app
    return TestClient(app)


@needs_warehouse
def test_core_endpoints_ok(client):
    for url in ["/api/meta", "/api/forecasts", "/api/cost?entity=KE", "/api/performance", "/api/confidence",
                "/api/quality", "/api/runs", "/api/sources", "/"]:
        assert client.get(url).status_code == 200, url


@needs_warehouse
def test_workspace_outlook_matches_forecast_rows(client):
    meta = client.get("/api/meta").json()
    ws = client.get(f"/api/workspace?entity=KE&month={meta['forecast_months'][-1]}").json()
    preds = [r["pred"] for r in ws["forecast"]]
    assert len(preds) == 24
    assert ws["outlook"]["peak_mw"] == max(preds)
    assert abs(ws["outlook"]["mean_mw"] - sum(preds) / 24) < 0.1
    assert all(r["row_id"].startswith("FC-KE-") for r in ws["forecast"])


@needs_warehouse
def test_missing_month_is_empty_not_zero(client):
    ws = client.get("/api/workspace?entity=KE&month=2030-01").json()
    assert ws["forecast"] == [] and ws["outlook"] is None and ws["empty_reason"]


@needs_warehouse
def test_scenario_zero_shift_matches_live_outlook(client):
    meta = client.get("/api/meta").json()
    month = meta["forecast_months"][-1]
    s = client.get(f"/api/scenario?entity=KE&month={month}&delta=0").json()
    ws = client.get(f"/api/workspace?entity=KE&month={month}").json()
    assert len(s["hours"]) == 24 and len(s["curve"]) == 7
    assert abs(s["summary"]["scen_mean_mw"] - ws["outlook"]["mean_mw"]) < 1.0   # same model, same weather
    hot = client.get(f"/api/scenario?entity=KE&month={month}&delta=3").json()
    assert all(h["temp_scen"] == round(h["temp_base"] + 3, 1) or abs(h["temp_scen"] - h["temp_base"] - 3) < 0.11
               for h in hot["hours"])
    assert client.get(f"/api/scenario?entity=KE&month={month}&delta=4").status_code == 400


@needs_index
def test_ask_returns_evidence(client):
    a = client.post("/api/ask", json={"question": "Compare next month with last year", "entity": "KE"}).json()
    assert a["status"] == "answered" and a["row_ids"] and a["citations"]
