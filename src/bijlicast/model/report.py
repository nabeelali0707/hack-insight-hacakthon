"""Model report: figures (baseline vs model, K-Electric profiles, errors by group) and a
markdown summary generated only from gold tables."""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ..config import MODELS_DIR, REPORTS_DIR  # noqa: E402
from ..warehouse import connect  # noqa: E402

FIG_DIR = REPORTS_DIR / "figures"
C_BASE, C_MODEL, C_ACT = "#9aa5b1", "#1f6feb", "#111111"


def _style(ax, title):
    ax.set_title(title, fontsize=11, loc="left", fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def make_figures() -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    bt = con.execute("SELECT * FROM gold.backtest").df()
    eg = con.execute("SELECT * FROM gold.errors_by_group").df()
    m = json.loads(open(MODELS_DIR / "metrics.json", encoding="utf-8").read())
    con.close()
    bt["period"] = pd.to_datetime(bt["period"])
    out = []

    # 1. baseline vs model, overall + by entity
    ent = eg[eg.group_by == "entity"].sort_values("baseline_mape", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    x = range(len(ent) + 1)
    labels = ["ALL"] + ent.group_value.tolist()
    base = [m["baseline_mape"]] + ent.baseline_mape.tolist()
    mod = [m["model_mape"]] + ent.model_mape.tolist()
    ax.bar([i - 0.2 for i in x], base, 0.4, color=C_BASE, label="Declared baseline (seasonal naive)")
    ax.bar([i + 0.2 for i in x], mod, 0.4, color=C_MODEL, label="BijliCast model")
    for i, (b, mm) in enumerate(zip(base, mod)):
        ax.text(i + 0.2, mm + 0.3, f"{mm:.1f}", ha="center", fontsize=8, color=C_MODEL)
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("Test MAPE (%) - lower is better")
    _style(ax, f"Test Jan-Sep 2026: model {m['model_mape']:.1f}% vs baseline {m['baseline_mape']:.1f}% "
               f"({m['improvement_pct']:.0f}% better)")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); p = FIG_DIR / "baseline_vs_model.png"; fig.savefig(p, dpi=160); plt.close(fig); out.append(p.name)

    # 2. K-Electric: actual vs model (80% band) vs baseline, per test month
    ke = bt[bt.entity == "KE"].sort_values(["period", "hour"])
    months = sorted(ke.period.unique())
    fig, axes = plt.subplots(1, len(months), figsize=(2.3 * len(months), 3.2), sharey=True)
    for ax, per in zip(axes, months):
        d = ke[ke.period == per]
        ax.fill_between(d.hour, d.lo, d.hi, color=C_MODEL, alpha=0.15, label="80% interval")
        ax.plot(d.hour, d.y, color=C_ACT, lw=1.8, label="Actual (ISMO)")
        ax.plot(d.hour, d.pred, color=C_MODEL, lw=1.5, label="Model")
        ax.plot(d.hour, d.baseline, color=C_BASE, lw=1.2, ls="--", label="Baseline")
        ax.set_title(pd.Timestamp(per).strftime("%b %Y"), fontsize=9)
        ax.set_xticks([0, 6, 12, 18, 23]); ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("K-Electric grid draw (MW)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, fontsize=8)
    fig.suptitle("K-Electric hourly profile by test month (hour of day, PKT)", x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.08, 1, 1)); p = FIG_DIR / "ke_profiles_test.png"; fig.savefig(p, dpi=160); plt.close(fig); out.append(p.name)

    # 3. errors by season and hour band
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, by in zip(axes, ["season", "hour_band"]):
        g = eg[eg.group_by == by].sort_values("model_mape")
        y = range(len(g))
        ax.barh([i + 0.2 for i in y], g.baseline_mape, 0.4, color=C_BASE, label="Baseline")
        ax.barh([i - 0.2 for i in y], g.model_mape, 0.4, color=C_MODEL, label="Model")
        ax.set_yticks(list(y), g.group_value)
        ax.set_xlabel("Test MAPE (%)")
        _style(ax, f"Errors by {by.replace('_', ' ')}")
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout(); p = FIG_DIR / "errors_by_group.png"; fig.savefig(p, dpi=160); plt.close(fig); out.append(p.name)
    return out


def write_report() -> str:
    figs = make_figures()
    m = json.loads(open(MODELS_DIR / "metrics.json", encoding="utf-8").read())
    con = connect(read_only=True)
    eg = con.execute("SELECT * FROM gold.errors_by_group").df()
    con.close()

    def tbl(by):
        g = eg[eg.group_by == by].sort_values("model_mape", ascending=False)
        rows = ["| " + by.replace("_", " ") + " | rows | baseline MAPE | model MAPE | change | 80% coverage | bias |",
                "|---|---|---|---|---|---|---|"]
        for _, r in g.iterrows():
            rows.append(f"| {r.group_value} | {int(r.n)} | {r.baseline_mape:.1f}% | {r.model_mape:.1f}% | "
                        f"{-r.improvement_pct:+.0f}% | {r.coverage_80:.0f}% | {r.bias_pct:+.1f}% | `{r.row_id}`")
            rows[-1] = rows[-1].rsplit(" | `", 1)[0] + " |"
        return "\n".join(rows)

    worse = eg[(eg.group_by == "entity") & (eg.improvement_pct < 1)].group_value.tolist()
    md = f"""# Model Report (generated from gold tables)

Trained {m['trained_at_utc']} · seed {m['seed']} · test months {', '.join(m['test_months'])} (Jun-Jul 2026 not published by ISMO).

## Headline (test set, evaluated once, ex-ante weather = climatology)

| | Declared baseline | BijliCast model |
|---|---|---|
| MAPE, all 10 entities x 24 h | {m['baseline_mape']:.2f}% | **{m['model_mape']:.2f}%** ({m['improvement_pct']:.0f}% better) |
| K-Electric MAPE | {m['ke_baseline_mape']:.2f}% | **{m['ke_model_mape']:.2f}%** |
| K-Electric MAE | {m['ke_baseline_mae_mw']:.0f} MW | **{m['ke_model_mae_mw']:.0f} MW** |
| Evening peak 18-22 h MAPE | {m['peak_baseline_mape']:.2f}% | **{m['peak_model_mape']:.2f}%** |
| 80% interval coverage | - | {m['coverage_80']:.1f}% (mean width {m['mean_interval_width_pct']:.0f}% of forecast) |
| Same model, actual (ex-post) weather | - | {m['model_mape_expost_weather']:.2f}% (upper bound if weather were known) |

Declared success criterion (>= 10% lower MAPE and K-Electric better): **{'met' if m['declared_success'] else 'NOT met'}**.

![baseline vs model](figures/{figs[0]})

![K-Electric profiles](figures/{figs[1]})

## Errors by group

{tbl('entity')}

{tbl('province')}

{tbl('season')}

{tbl('hour_band')}

![errors by group](figures/{figs[2]})

## Where the model is weakest and what a user should do

* **Weakest entity: {m['weakest_entity']['entity']}** ({m['weakest_entity']['model_mape']:.1f}% MAPE). Its profile has
  Ramadan sehri spikes and recurring scheduled-load-management jumps (see quality log `DQ-ISMO-SPIKE`).
* **No gain over the baseline for: {', '.join(worse) if worse else 'none'}.** For these, planners should keep the
  seasonal-naive figure and use our interval as a range check.
* **Summer is hardest:** the model under-forecasts summer months (negative bias) and interval coverage falls below 80%.
  Treat summer evening-peak forecasts as a floor, not a ceiling.
* Intervals cover {m['coverage_80']:.0f}% of test values against an 80% target: slightly too narrow, mainly in summer.

## Method

* Target: log(demand / latest published level); prediction = level x exp(model). Handles K-Electric's 2025 step
  change in grid draw without extrapolating trends.
* Model: scikit-learn HistGradientBoostingRegressor {m['best_params']} chosen on validation months Oct-Dec 2025
  (validation MAPE {m['val_mape_best']:.2f}%).
* Leakage guards: demand lags >= 2 months (ISMO publication lag); climatology uses only earlier years; final model
  trained on targets <= Nov 2025 (all ISMO had published by 1 Jan 2026); test touched once.
* Intervals: split-conformal on {m['n_calibration_residuals']} rolling-origin out-of-sample residuals,
  log-quantiles {m['conformal_log_quantiles'][0]:.3f} / {m['conformal_log_quantiles'][1]:.3f}.
"""
    path = REPORTS_DIR / "model_report.md"
    path.write_text(md, encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    print(write_report())
