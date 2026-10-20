"""Baseline rule, leakage guard, number guard, and Insight Agent behaviour on real gold tables."""

import pandas as pd
import pytest

from bijlicast.insight import wording
from bijlicast.insight.agent import Draft
from bijlicast.model.baseline import seasonal_naive
from bijlicast.model.features import MIN_LAG

from conftest import needs_index, needs_warehouse


def test_baseline_uses_last_year_then_latest_published_fallback():
    # hand-made TEST FIXTURE
    prof = pd.DataFrame({"entity": "KE", "period": pd.to_datetime(["2025-01-01", "2025-11-01"]).repeat(24),
                         "hour": list(range(24)) * 2, "demand_mw": [100.0] * 24 + [200.0] * 24})
    t = pd.DataFrame({"entity": ["KE", "KE"], "period": pd.to_datetime(["2026-01-01", "2026-02-01"]), "hour": [5, 5]})
    b = seasonal_naive(prof, t)
    assert b.baseline.tolist() == [100.0, 200.0]          # Jan: last year; Feb: fallback to Nov (<= m-2)
    assert b.baseline_source.iloc[1].startswith("fallback")


def test_number_guard_rejects_llm_digits(monkeypatch):
    monkeypatch.setenv("BIJLICAST_LLM", "anthropic")

    class Fake:
        class beta:
            class messages:
                @staticmethod
                def create(**kw):
                    class R:
                        stop_reason = "end_turn"
                        content = [type("B", (), {"type": "text", "text": "Demand is 9999 MW {{N1}} {{R1}}"})()]
                    return R()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: Fake())
    draft = "Demand averages {{N1}} MW {{R1}}"
    text, used = wording.polish(draft, "en")
    assert text == draft and used is False


def test_draft_has_no_raw_digits_outside_placeholders():
    d = Draft()
    s = f"peak {d.num(2846.4)} MW at {d.num(2, '{:02d}:00')} {d.rows(['FC-KE-202611-02'])}"
    assert not any(ch.isdigit() for ch in wording.PLACEHOLDER.sub("", s))
    assert "2,846" in d.render(s) and "FC-KE-202611-02" in d.render(s)


@needs_warehouse
def test_no_leakage_lags_respect_publication_delay():
    from bijlicast.model.features import build_panel, load_inputs
    from bijlicast.warehouse import connect
    con = connect(read_only=True)
    prof, wx = load_inputs(con)
    con.close()
    p = build_panel(prof, wx, weather_mode="climatology")
    gap = (p.period.dt.year - p.lag_period.dt.year) * 12 + (p.period.dt.month - p.lag_period.dt.month)
    assert (gap >= MIN_LAG).all()


@needs_index
def test_golden_questions_all_pass():
    from bijlicast.insight.evaluate import run_golden
    res = run_golden()
    failed = res[~res.passed]
    assert failed.empty, failed[["golden_id", "status", "check"]].to_string()
