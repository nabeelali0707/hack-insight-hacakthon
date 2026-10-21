"""BijliCast web API + static frontend.

    uvicorn bijlicast.api:app --port 8000      (or: python run.py web)

The browser never opens DuckDB: every endpoint reads the read-only serving snapshot
(data/serve/warehouse.duckdb, refreshed after each pipeline run) and returns JSON that keeps
row IDs and source metadata for evidence views. Missing data is returned as null with a
reason, never as zero.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DOCS_DIR, REPORTS_DIR, ROOT
from .serving import snapshot_path

WEB_DIR = ROOT / "web"
EVENING = list(range(18, 23))  # 18-22 PKT, the defined evening analysis window

@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=lambda: _get_retriever(), daemon=True).start()  # embedding model warms up in the background
    yield


app = FastAPI(title="BijliCast API", version="1.0", lifespan=lifespan)


@contextmanager
def db():
    last = None
    for _ in range(6):
        try:
            con = duckdb.connect(str(snapshot_path()), read_only=True)
            break
        except duckdb.Error as exc:  # snapshot being replaced this instant
            last = exc
            time.sleep(0.25)
    else:
        raise HTTPException(503, f"Data snapshot unavailable: {last}")
    try:
        yield con
    finally:
        con.close()


def rows(con, sql: str, params=()) -> list[dict]:
    df = con.execute(sql, list(params)).df()
    return json.loads(df.to_json(orient="records", date_format="iso"))


def one(con, sql: str, params=()) -> dict | None:
    r = rows(con, sql, params)
    return r[0] if r else None


def _month(s: str | None) -> pd.Timestamp | None:
    return pd.Timestamp(s + "-01") if s and len(s) == 7 else (pd.Timestamp(s) if s else None)


def _has_table(con, schema: str, name: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=? AND table_name=?",
                            [schema, name]).fetchone()[0])


# ---------------------------------------------------------------------------- meta
@app.get("/api/meta")
def meta():
    with db() as con:
        ents = rows(con, "SELECT code, name, city, province FROM gold.entity")
        order = ["KE", "LESCO", "FESCO", "GEPCO", "IESCO", "MEPCO", "PESCO", "QESCO", "HESCO", "SEPCO"]
        ents.sort(key=lambda e: order.index(e["code"]) if e["code"] in order else 99)
        months = [r["m"] for r in rows(con, "SELECT DISTINCT strftime(period, '%Y-%m') m FROM gold.forecast_outlook ORDER BY 1")]
        gen = con.execute("SELECT max(generated_at_utc) FROM gold.forecast_outlook").fetchone()[0]
        status = one(con, "SELECT overall, built_at_utc, run_id FROM quality.status")
    now = pd.Timestamp.now(tz="Asia/Karachi")
    nxt = (now + pd.DateOffset(months=1)).strftime("%Y-%m")
    snap = snapshot_path()
    return {"entities": ents, "forecast_months": months,
            "default_entity": "KE", "default_month": nxt if nxt in months else (months[-1] if months else None),
            "forecast_generated_at_utc": gen, "quality": status, "mode": "live",
            "snapshot_utc": datetime.fromtimestamp(snap.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


# ---------------------------------------------------------------------------- workspace
@app.get("/api/workspace")
def workspace(entity: str = "KE", month: str | None = None):
    with db() as con:
        if not month:
            month = con.execute("SELECT strftime(max(period), '%Y-%m') FROM gold.forecast_outlook").fetchone()[0]
        m = _month(month)
        fc = rows(con, """SELECT row_id, hour, round(pred_mw,1) pred, round(lo_mw,1) lo, round(hi_mw,1) hi,
                                 weather_coverage, strftime(lag_period, '%Y-%m') lag_period, generated_at_utc, model_version
                          FROM gold.forecast_outlook WHERE entity=? AND period=? ORDER BY hour""", (entity, m.date()))
        ly = m - pd.DateOffset(years=1)
        base = rows(con, """SELECT row_id, hour_pkt AS hour, round(demand_mw,1) AS value FROM gold.demand_profile
                            WHERE entity=? AND period=? ORDER BY hour_pkt""", (entity, ly.date()))
        ent = one(con, "SELECT code, name, city, province FROM gold.entity WHERE code=?", (entity,))
    if not fc:
        return {"entity": ent, "month": month, "forecast": [], "baseline": [], "outlook": None,
                "empty_reason": f"No forecast for {entity} in {month}. BijliCast forecasts only the current and next month."}
    preds = [r["pred"] for r in fc]
    peak = max(fc, key=lambda r: r["pred"])
    eve = [r["pred"] for r in fc if r["hour"] in EVENING]
    return {
        "entity": ent, "month": month,
        "forecast": fc,
        "baseline": base,
        "baseline_period": ly.strftime("%Y-%m"),
        "baseline_reason": None if len(base) == 24 else
        f"ISMO has no usable hourly profile for {ly:%B %Y}, so last year's line is not shown.",
        "outlook": {
            "mean_mw": round(sum(preds) / len(preds), 1), "peak_mw": peak["pred"], "peak_hour": peak["hour"],
            "peak_lo": peak["lo"], "peak_hi": peak["hi"], "peak_row_id": peak["row_id"],
            "evening_mean_mw": round(sum(eve) / len(eve), 1), "evening_hours": [18, 22],
            "peak_in_evening": peak["hour"] in EVENING,
            "lag_period": fc[0]["lag_period"], "weather_coverage": fc[0]["weather_coverage"],
            "generated_at_utc": fc[0]["generated_at_utc"], "model_version": fc[0]["model_version"],
        },
    }


# ---------------------------------------------------------------------------- forecasts (all entities)
@app.get("/api/forecasts")
def forecasts(month: str | None = None):
    with db() as con:
        if not month:
            month = con.execute("SELECT strftime(max(period), '%Y-%m') FROM gold.forecast_outlook").fetchone()[0]
        m = _month(month)
        fc = con.execute("""SELECT f.entity, e.name, e.province, f.hour, f.pred_mw, f.lo_mw, f.hi_mw, f.weather_coverage,
                                   strftime(f.lag_period, '%Y-%m') lag_period
                            FROM gold.forecast_outlook f JOIN gold.entity e ON e.code=f.entity
                            WHERE f.period=? ORDER BY f.entity, f.hour""", [m.date()]).df()
    out = []
    for ent, g in fc.groupby("entity", sort=False):
        pk = g.loc[g.pred_mw.idxmax()]
        out.append({"entity": ent, "name": g.name.iloc[0], "province": g.province.iloc[0],
                    "mean_mw": round(g.pred_mw.mean(), 1), "peak_mw": round(pk.pred_mw, 1), "peak_hour": int(pk.hour),
                    "peak_lo": round(pk.lo_mw, 1), "peak_hi": round(pk.hi_mw, 1),
                    "weather_coverage": float(g.weather_coverage.iloc[0]), "lag_period": g.lag_period.iloc[0],
                    "profile": [round(v, 1) for v in g.pred_mw], "lo": [round(v, 1) for v in g.lo_mw],
                    "hi": [round(v, 1) for v in g.hi_mw]})
    order = ["KE", "LESCO", "FESCO", "GEPCO", "IESCO", "MEPCO", "PESCO", "QESCO", "HESCO", "SEPCO"]
    out.sort(key=lambda r: order.index(r["entity"]) if r["entity"] in order else 99)
    return {"month": month, "entities": out}


@app.get("/api/scenario")
def scenario_ep(entity: str = "KE", month: str | None = None, delta: float = 3.0):
    from .model.scenario import ALLOWED, scenario
    if delta not in ALLOWED:
        raise HTTPException(400, f"delta must be one of {list(ALLOWED)}")
    if not month:
        with db() as con:
            month = con.execute("SELECT strftime(max(period), '%Y-%m') FROM gold.forecast_outlook").fetchone()[0]
    return scenario(entity, month, delta, with_curve=True)


@app.get("/api/forecast_history")
def forecast_history(entity: str = "KE", month: str | None = None):
    with db() as con:
        if not _has_table(con, "gold", "forecast_history"):
            return {"entity": entity, "month": month, "snapshots": []}
        m = _month(month) if month else pd.Timestamp(con.execute("SELECT max(period) FROM gold.forecast_outlook").fetchone()[0])
        snaps = rows(con, """SELECT generated_at_utc, round(avg(pred_mw),1) mean_mw, round(max(pred_mw),1) peak_mw,
                                    any_value(weather_coverage) weather_coverage
                             FROM gold.forecast_history WHERE entity=? AND period=? GROUP BY generated_at_utc
                             ORDER BY generated_at_utc""", (entity, m.date()))
    return {"entity": entity, "month": m.strftime("%Y-%m"), "snapshots": snaps}


# ---------------------------------------------------------------------------- cost lens
@app.get("/api/cost")
def cost(entity: str = "KE", period: str | None = None):
    with db() as con:
        periods = [r["p"] for r in rows(con, """SELECT DISTINCT strftime(p.period, '%Y-%m') p FROM gold.price_month_hour p
                                                JOIN gold.demand_profile d ON d.period=p.period AND d.entity=?
                                                ORDER BY 1""", (entity,))]
        if not periods:
            return {"entity": entity, "periods": [], "empty_reason": "No month has both ISMO hourly prices and demand for this entity."}
        period = period if period in periods else periods[-1]
        pm = _month(period)
        hourly = rows(con, """SELECT p.hour_pkt AS hour, p.row_id price_row_id, round(p.avg_price_rs_kwh*1000, 0) price_pkr_mwh,
                                     p.n_hours, d.row_id demand_row_id, round(d.demand_mw,1) demand_mw,
                                     round(d.demand_mw * p.avg_price_rs_kwh * 1000 / 1e6, 3) cost_pkr_m_per_hour
                              FROM gold.price_month_hour p
                              JOIN gold.demand_profile d ON d.period=p.period AND d.hour_pkt=p.hour_pkt AND d.entity=?
                              WHERE p.period=? ORDER BY p.hour_pkt""", (entity, pm.date()))
        summary = one(con, "SELECT * FROM gold.peak_cost WHERE entity=? AND period=?", (entity, pm.date()))
        monthly = rows(con, """SELECT row_id, strftime(period, '%Y-%m') period, daily_cost_rs_m, weighted_price_rs_kwh,
                                      evening_peak_energy_share_pct, evening_peak_cost_share_pct, dearest_hours,
                                      cheapest_hours, shift_pct, shift_saving_rs_m_per_month
                               FROM gold.peak_cost WHERE entity=? ORDER BY period""", (entity,))
        exposure = rows(con, """SELECT row_id, strftime(period, '%Y-%m') period, model_risk_rs_m_per_day,
                                       baseline_risk_rs_m_per_day, risk_reduction_rs_m_per_day
                                FROM gold.error_cost WHERE entity=? ORDER BY period""", (entity,))
    return {"entity": entity, "periods": periods, "period": period, "hourly": hourly, "summary": summary,
            "monthly": monthly, "exposure": exposure, "evening_hours": EVENING}


# ---------------------------------------------------------------------------- performance
@app.get("/api/performance")
def performance(entity: str = "KE"):
    with db() as con:
        mm = one(con, "SELECT * FROM gold.model_metrics")
        groups = rows(con, "SELECT * FROM gold.errors_by_group ORDER BY group_by, model_mape DESC")
        by_month = rows(con, """SELECT strftime(period, '%Y-%m') period, round(avg(abs(pred-y)/y)*100,2) model_mape,
                                       round(avg(abs(baseline-y)/y)*100,2) baseline_mape, count(*) n
                                FROM gold.backtest WHERE entity=? GROUP BY 1 ORDER BY 1""", (entity,))
    if mm:
        for k in ("test_months", "best_params", "weakest_entity", "conformal_log_quantiles"):
            if isinstance(mm.get(k), str):
                try:
                    mm[k] = json.loads(mm[k])
                except json.JSONDecodeError:
                    pass
    return {"metrics": mm, "groups": groups, "by_month": by_month, "entity": entity,
            "baseline_definition": "Same month last year, same hour (fallback: latest month already published, at least 2 months back)"}


# ---------------------------------------------------------------------------- data confidence / quality
@app.get("/api/confidence")
def confidence(entity: str = "KE"):
    with db() as con:
        status = one(con, "SELECT * FROM quality.status")
        pending = rows(con, """SELECT decision_id, check_id, entity, period, severity, reason, review_status
                               FROM quality.review_queue WHERE review_status LIKE 'pending%' ORDER BY decided_at_utc DESC""")
        drift = rows(con, "SELECT row_id, entity, metric, value, status, detail, checked_at_utc FROM gold.drift_status ORDER BY entity")
        runs = rows(con, "SELECT * FROM ops.pipeline_runs ORDER BY started_at_utc DESC LIMIT 1") if _has_table(con, "ops", "pipeline_runs") else []
        last_ok = one(con, "SELECT * FROM ops.pipeline_runs WHERE status='success' ORDER BY started_at_utc DESC LIMIT 1") \
            if _has_table(con, "ops", "pipeline_runs") else None
        sources = rows(con, """SELECT source, count(*) files, max(fetched_at_utc) last_fetched_utc, sum(bytes) bytes
                               FROM raw.manifest GROUP BY source ORDER BY source""")
    rank = {"STABLE": 0, "WATCH": 1, "DRIFT": 2}
    ent_drift = [d for d in drift if d["entity"] == entity]
    worst = max(drift, key=lambda d: rank.get(d["status"], 0)) if drift else None
    if status:  # ages are recomputed NOW: the build-time values go stale if the pipeline stops
        now = pd.Timestamp.now(tz="UTC")
        month_end = (pd.Timestamp(status["ismo_latest_period"] + "-01") + pd.offsets.MonthEnd(0)).tz_localize("UTC")
        status["ismo_age_days"] = int((now - month_end).days)
        status["ismo_stale"] = status["ismo_age_days"] > 50
        if status.get("live_snapshot_utc"):
            age_h = (now - pd.Timestamp(status["live_snapshot_utc"])).total_seconds() / 3600
            status["live_age_hours"] = round(age_h, 1)
            status["live_stale"] = age_h > 2
    fresh = "RED" if status and status["ismo_stale"] and status.get("live_stale") else (
        "AMBER" if status and (status["ismo_stale"] or status.get("live_stale")) else "GREEN")
    drift_level = {0: "GREEN", 1: "AMBER", 2: "RED"}[max((rank.get(d["status"], 0) for d in ent_drift), default=0)]
    return {"status": status, "freshness_level": fresh, "pending_review": pending, "drift": drift,
            "entity_drift": ent_drift, "drift_level": drift_level, "worst_drift": worst,
            "last_run": runs[0] if runs else None, "last_success": last_ok, "sources": sources}


@app.get("/api/quality")
def quality(action: str | None = None, run: str = "latest"):
    with db() as con:
        rid = con.execute("SELECT max(run_id) FROM quality.quality_log").fetchone()[0] if run == "latest" else run
        sql = """SELECT decision_id, check_id, tool, rule, table_name, entity, period, action, rows_affected, severity,
                        reason, needs_review, review_status, evidence
                 FROM quality.quality_log WHERE run_id=?"""
        params = [rid]
        if action:
            sql += " AND action=?"
            params.append(action.upper())
        decisions = rows(con, sql + " ORDER BY decision_id", params)
        counts = rows(con, "SELECT action, count(*) n FROM quality.quality_log WHERE run_id=? GROUP BY action", (rid,))
    return {"run_id": rid, "counts": {c["action"]: c["n"] for c in counts}, "decisions": decisions}


@app.get("/api/runs")
def runs(limit: int = 48):
    with db() as con:
        if not _has_table(con, "ops", "pipeline_runs"):
            return {"runs": []}
        r = rows(con, "SELECT * FROM ops.pipeline_runs ORDER BY started_at_utc DESC LIMIT ?", (limit,))
    for x in r:
        for k in ("timings", "decisions", "summary"):
            try:
                x[k] = json.loads(x[k]) if isinstance(x[k], str) else x[k]
            except json.JSONDecodeError:
                pass
    return {"runs": r}


@app.get("/api/sources")
def sources():
    with db() as con:
        files = rows(con, """SELECT file_id, source, title, period, query, fetched_at_utc, substr(sha256,1,12) sha256_12,
                                   bytes, licence, immutable FROM raw.manifest ORDER BY source, file_id""")
    return {"files": files}


@app.get("/api/briefs")
def briefs(lang: str = "en"):
    with db() as con:
        if not _has_table(con, "gold", "briefs"):
            return {"briefs": []}
        b = rows(con, "SELECT * FROM gold.briefs WHERE lang=? ORDER BY brief_id", (lang,))
    for x in b:
        x["row_ids"] = json.loads(x["row_ids"])
        x["citations"] = json.loads(x["citations"])
    return {"briefs": b}


# ---------------------------------------------------------------------------- Insight Agent
_retriever = None
_retriever_lock = threading.Lock()


def _get_retriever():
    global _retriever
    with _retriever_lock:
        if _retriever is None:
            from .insight.index import Retriever
            _retriever = Retriever()
        return _retriever


class AskBody(BaseModel):
    question: str
    lang: str | None = None
    entity: str | None = None
    month: str | None = None


@app.post("/api/ask")
def ask(body: AskBody):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "Type a question first.")
    if len(q) > 500:
        raise HTTPException(400, "Questions are limited to 500 characters.")
    from .insight.agent import InsightAgent
    with db() as con:
        agent = InsightAgent(retriever=_get_retriever(), con=con)
        a = agent.ask(q, lang=body.lang, entity=body.entity, month=_month(body.month) if body.month else None)
    return {"question": a.question, "lang": a.lang, "intent": a.intent, "status": a.status, "text": a.text,
            "row_ids": a.row_ids, "citations": a.citations, "entity": a.entity, "month": a.month,
            "llm_used": a.llm_used, "asked_at_utc": a.asked_at_utc}


# ---------------------------------------------------------------------------- files + frontend
ALLOWED_DOCS = {"Summary.pdf", "datasetproposal.pdf", "business_model.md", "optimization_log.md",
                "problem_analysis.md", "baseline_declaration.md"}
ALLOWED_REPORTS = {"model_report.md", "quality_log_latest.csv", "errors_by_group.csv", "prefect_runs.csv"}


@app.get("/files/docs/{name}")
def doc_file(name: str):
    if name not in ALLOWED_DOCS or not (DOCS_DIR / name).exists():
        raise HTTPException(404, "Document not found")
    return FileResponse(DOCS_DIR / name)


@app.get("/files/reports/{name:path}")
def report_file(name: str):
    p = (REPORTS_DIR / name).resolve()
    ok = (name in ALLOWED_REPORTS or (name.startswith("figures/") and name.endswith(".png"))) and \
        str(p).startswith(str(REPORTS_DIR.resolve())) and p.exists()
    if not ok:
        raise HTTPException(404, "Report not found")
    return FileResponse(p)


@app.get("/api/health")
def health():
    return JSONResponse({"ok": True, "snapshot": str(snapshot_path().name)})


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
