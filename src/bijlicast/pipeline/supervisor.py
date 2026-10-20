"""Supervisor agent: coordinates the other agents every hour and makes the go/no-go calls.

  1. Fetch    - new live weather snapshot; registry files not yet on disk (Source Scout);
                SHA-verified reload of everything else (incremental, OPT-10).
  2. Gate     - Data Quality Agent runs inside the build; RED => quarantine, gold keeps the
                last good version, and the supervisor STOPS publishing downstream outputs.
  3. Drift    - drift monitor; a new ISMO month or level drift => "retrain recommended",
                which is a risky change and goes to the human review queue (never automatic).
  4. Forecast - refresh the live outlook (current + next month) and the Peak Cost Lens.
  5. Insight  - regenerate standard briefs (English + Urdu) and re-run the golden question
                set; a failing golden check is logged as a regression.
  6. Record   - ops.pipeline_runs row: status, step timings, decisions (dashboard "last run").
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from ..warehouse import _write, build, connect

BRIEF_QUESTIONS = [
    ("KE-OUTLOOK-THIS-EN", "What is K-Electric's expected demand this month?", "en"),
    ("KE-OUTLOOK-NEXT-EN", "What is K-Electric's expected demand next month?", "en"),
    ("KE-OUTLOOK-NEXT-UR", "اگلے مہینے کراچی میں بجلی کی متوقع طلب کتنی ہے؟", "ur"),
    ("KE-PEAKCOST-EN", "How much would K-Electric save by shifting peak demand?", "en"),
    ("KE-PEAKCOST-UR", "کے الیکٹرک پیک اوقات سے طلب منتقل کر کے کتنی بچت کر سکتا ہے؟", "ur"),
    ("KE-ACCURACY-EN", "How accurate is the model for K-Electric compared with the baseline?", "en"),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def step_fetch_and_build(run_id: str) -> dict:
    return build(run_id=run_id, fetch=True, include_forecast=True)


def step_drift() -> dict:
    from ..quality.drift import run as drift_run
    dr = drift_run()
    con = connect()
    latest = con.execute("SELECT max(period) FROM gold.demand_profile").fetchone()[0]
    con.close()
    from ..model.train import FINAL_TRAIN_END
    new_months = (pd.Timestamp(latest).to_period("M") - FINAL_TRAIN_END.to_period("M")).n
    drifted = dr[dr.status == "DRIFT"]
    return {"n_drift": int(len(drifted)), "n_watch": int((dr.status == "WATCH").sum()),
            "months_since_training": int(new_months),
            "retrain_recommended": bool(len(drifted) or new_months >= 6)}


def step_forecast_and_cost() -> dict:
    from ..insight.costlens import run as cost_run
    from ..model.forecast import run as fc_run
    fc = fc_run()
    cost_run()
    ke = fc[fc.entity == "KE"]
    return {"forecast_rows": int(len(fc)),
            "ke_next_peak_mw": float(ke[ke.period == ke.period.max()].pred_mw.max()) if len(ke) else None}


def step_insight() -> dict:
    from ..insight.agent import InsightAgent, log_answers
    from ..insight.evaluate import run_golden
    agent = InsightAgent()
    try:
        answers = [agent.ask(q, lang) for _, q, lang in BRIEF_QUESTIONS]
        briefs = pd.DataFrame([{"brief_id": bid, "lang": lang, "question": a.question, "status": a.status,
                                "text": a.text, "row_ids": json.dumps(a.row_ids), "citations": json.dumps(a.citations),
                                "generated_at_utc": a.asked_at_utc}
                               for (bid, _, lang), a in zip(BRIEF_QUESTIONS, answers)])
        golden = run_golden(agent)
        log_answers(answers, agent.con)
        _write(agent.con, "gold", "briefs", briefs)
    finally:
        agent.con.close()
    return {"briefs": int(len(briefs)), "golden_passed": int(golden["passed"].sum()),
            "golden_total": int(len(golden))}


def queue_for_review(run_id: str, kind: str, reason: str, evidence: dict) -> None:
    con = connect()
    row = pd.DataFrame([{"decision_id": f"{run_id}-SUP", "run_id": run_id, "decided_at_utc": _now(),
                         "check_id": kind, "tool": "supervisor", "rule": "Model replacement needs human approval",
                         "table_name": "model", "entity": None, "period": None, "action": "FLAG", "rows_affected": 0,
                         "severity": "warn", "reason": reason, "needs_review": True,
                         "review_status": "pending human review", "evidence": json.dumps(evidence)}])
    con.register("_r", row)
    con.execute("INSERT INTO quality.review_queue SELECT * FROM _r")
    con.unregister("_r")
    con.close()


def run_once(run_id: str | None = None, steps=None) -> dict:
    """One supervised pipeline run. `steps` lets Prefect wrap each step as a task."""
    steps = steps or {"fetch_build": step_fetch_and_build, "drift": step_drift,
                      "forecast": step_forecast_and_cost, "insight": step_insight}
    run_id = run_id or datetime.now(timezone.utc).strftime("run%Y%m%dT%H%M%SZ")
    started = _now()
    rec = {"run_id": run_id, "started_at_utc": started, "status": "running", "decisions": [], "timings": {}}

    def timed(name, fn, *a):
        t = time.time()
        out = fn(*a)
        rec["timings"][name] = round(time.time() - t, 2)
        return out

    try:
        b = timed("fetch_build", steps["fetch_build"], run_id)
        rec["quality"] = b["status"]["overall"]
        rec["fetch"] = b["fetch"]
        if not b["status"]["published"]:
            rec["status"] = "quarantined"
            rec["decisions"].append("Quality gate RED: build quarantined; gold keeps the last good version; "
                                    "downstream steps skipped.")
        else:
            d = timed("drift", steps["drift"])
            rec["drift"] = d
            if d["retrain_recommended"]:
                queue_for_review(run_id, "SUP-RETRAIN", "Retraining recommended (drift or >= 6 new ISMO months); "
                                 "a human must approve replacing the evaluated model.", d)
                rec["decisions"].append("Retrain recommended -> queued for human approval (not automatic).")
            rec["forecast"] = timed("forecast", steps["forecast"])
            rec["insight"] = timed("insight", steps["insight"])
            if rec["insight"]["golden_passed"] < rec["insight"]["golden_total"]:
                rec["decisions"].append("Golden question regression detected - see gold.golden_eval.")
            rec["status"] = "success"
    except Exception as exc:
        rec["status"] = "failed"
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["finished_at_utc"] = _now()
    _record(rec)
    if rec["status"] == "failed":
        raise RuntimeError(rec["error"])
    return rec


def _record(rec: dict) -> None:
    con = connect()
    con.execute("CREATE SCHEMA IF NOT EXISTS ops")
    row = pd.DataFrame([{"run_id": rec["run_id"], "started_at_utc": rec["started_at_utc"],
                         "finished_at_utc": rec["finished_at_utc"], "status": rec["status"],
                         "quality": rec.get("quality"), "timings": json.dumps(rec["timings"]),
                         "decisions": json.dumps(rec["decisions"]), "summary": json.dumps(
                             {k: rec.get(k) for k in ("fetch", "drift", "forecast", "insight", "error")}, default=str)}])
    con.register("_r", row)
    con.execute("CREATE TABLE IF NOT EXISTS ops.pipeline_runs AS SELECT * FROM _r WHERE 1=0")
    con.execute("INSERT INTO ops.pipeline_runs SELECT * FROM _r")
    con.unregister("_r")
    con.close()


if __name__ == "__main__":
    print(json.dumps(run_once(), indent=1, default=str))
