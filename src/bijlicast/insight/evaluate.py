"""Golden question set for the Insight Agent (participant guide, chapter 9 "tests before the viva").

Questions are written by the team; expected outcomes are checked against gold tables at run
time, so nothing here is synthetic data. Results -> gold.golden_eval.
"""

from __future__ import annotations

import re

import pandas as pd

from ..warehouse import _write


def _num_in(text: str, value: float, fmt: str = "{:,.0f}") -> bool:
    return fmt.format(value) in text


def _check_actual_numbers(agent, a, ent, month) -> tuple[bool, str]:
    df = agent.con.execute("SELECT row_id, demand_mw FROM gold.demand_profile WHERE entity=? AND period=?",
                           [ent, pd.Timestamp(month).date()]).df()
    if df.empty:
        return False, "no gold rows"
    mean, peak, low = df.demand_mw.mean(), df.demand_mw.max(), df.demand_mw.min()
    ok = all(_num_in(a.text, v) for v in (mean, peak, low)) and set(df.row_id) <= set(a.row_ids)
    return ok, f"mean {mean:,.0f}, peak {peak:,.0f}, low {low:,.0f} in text and all 24 row IDs stored: {ok}"


def _check_forecast_numbers(agent, a, ent) -> tuple[bool, str]:
    ids = [r for r in a.row_ids if r.startswith(f"FC-{ent}-")]
    if not ids:
        return False, "no forecast rows cited"
    df = agent.con.execute(f"SELECT row_id, pred_mw FROM gold.forecast_outlook WHERE row_id IN ({','.join('?' * len(ids))})",
                           ids).df()
    ok = _num_in(a.text, df.pred_mw.max()) and _num_in(a.text, df.pred_mw.mean()) and len(df) == 24
    return ok, f"peak {df.pred_mw.max():,.0f} and mean {df.pred_mw.mean():,.0f} match {len(df)} cited rows: {ok}"


GOLDEN = [
    {"id": "G01", "q": "What are K-Electric's peak hours under Time of Use?", "expect": "answered",
     "check": lambda ag, a: (any(c["doc_id"] == "DOC-KETOU" for c in a.citations), "cites DOC-KETOU")},
    {"id": "G02", "q": "What will K-Electric's demand be in December 2027?", "expect": "dont_know",
     "check": lambda ag, a: ("current and next month" in a.text, "explains forecast horizon")},
    {"id": "G03", "q": "What is the electricity demand in Gilgit next month?", "expect": "dont_know",
     "check": lambda ag, a: ("no data for the place" in a.text, "explains coverage")},
    {"id": "G04", "q": "Why did K-Electric's demand fall in October 2025?", "expect": "corrected_premise",
     "check": lambda ag, a: ("does not support the premise" in a.text, "corrects false premise with data")},
    {"id": "G05", "q": "What was K-Electric's demand in September 2026?", "expect": "answered",
     "check": lambda ag, a: _check_actual_numbers(ag, a, "KE", "2026-09-01")},
    {"id": "G06", "q": "What was K-Electric's demand in June 2026?", "expect": "dont_know",
     "check": lambda ag, a: ("not published usable hourly data" in a.text, "explains publisher gap")},
    {"id": "G07", "q": "اگلے مہینے کراچی میں بجلی کی متوقع طلب کتنی ہے؟", "expect": "answered",
     "check": lambda ag, a: (a.lang == "ur" and re.search(r"[؀-ۿ]", a.text) is not None
                             and _check_forecast_numbers(ag, a, "KE")[0], "Urdu answer with matching numbers")},
    {"id": "G08", "q": "Who won the cricket world cup?", "expect": "dont_know",
     "check": lambda ag, a: (a.status == "dont_know", "refuses unsupported topic")},
    {"id": "G09", "q": "How accurate is the model for IESCO?", "expect": "answered",
     "check": lambda ag, a: ("does not beat the baseline" in a.text, "states honest weakness")},
    {"id": "G10", "q": "Which data was flagged as copied by the quality agent?", "expect": "answered",
     "check": lambda ag, a: ("DQ-ISMO-COPY" in a.text, "cites copy decisions")},
    {"id": "G11", "q": "What is K-Electric's expected demand next month?", "expect": "answered",
     "check": lambda ag, a: _check_forecast_numbers(ag, a, "KE")},
    {"id": "G12", "q": "What does NEPRA say about transmission and distribution losses in KE?", "expect": "answered",
     "check": lambda ag, a: (any(c["doc_id"] == "DOC-SOI24" for c in a.citations), "cites NEPRA report")},
]


def run_golden(agent=None) -> pd.DataFrame:
    own = agent is None
    if own:
        from .agent import InsightAgent
        agent = InsightAgent()
    rows = []
    for g in GOLDEN:
        a = agent.ask(g["q"])
        ok_check, detail = g["check"](agent, a)
        passed = (a.status == g["expect"]) and bool(ok_check)
        rows.append({"golden_id": g["id"], "question": g["q"], "expected_status": g["expect"], "status": a.status,
                     "check": detail, "passed": passed, "n_rows": len(a.row_ids),
                     "citations": ", ".join(c["doc_id"] + (f" p.{c['page']}" if c["page"] else "") for c in a.citations),
                     "answer": a.text, "asked_at_utc": a.asked_at_utc})
    df = pd.DataFrame(rows)
    _write(agent.con, "gold", "golden_eval", df)
    if own:
        agent.con.close()
    return df


if __name__ == "__main__":
    res = run_golden()
    print(res[["golden_id", "expected_status", "status", "passed", "check"]].to_string())
    print(f"\n{int(res.passed.sum())}/{len(res)} passed")
