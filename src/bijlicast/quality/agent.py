"""The Data Quality Agent.

It is not a fixed script of checks. For every table it:
  1. runs tools (pandera schemas, gap / duplicate / unit-basis / spike / freshness detectors),
  2. decides one action per finding: FIX (safe, certain, reversible), FILL (estimate, marked)
     or FLAG (keep as is and warn),
  3. explains the decision (rule, reason, rows affected, evidence),
  4. logs it with a timestamp (quality_log), and
  5. sends risky decisions (dropping or replacing whole publisher files) to a human review
     queue; config/approvals.yaml records who approved them.

The policy, in the guide's words: certain corrections are fixed, short gaps in smooth hourly
series are filled and marked, long gaps and unconfirmable values are flagged, never guessed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR, ENTITY_ORDER, PKT_OFFSET_HOURS
from . import schemas

MAX_FILL_GAP_HOURS = 3          # weather: fill gaps up to 3 h (smooth series), flag longer
CONSISTENCY_TOL = 0.10          # hourly profile vs reported daily energy
SPIKE_RATIO = 0.5               # hour-to-hour jump > 50% of the month's median
STALE_ISMO_DAYS = 50            # ISMO publishes ~15 days after month end
STALE_LIVE_HOURS = 2


@dataclass
class Decision:
    check_id: str
    tool: str
    rule: str
    table_name: str
    action: str                  # FIX | FILL | FLAG | PASS
    rows_affected: int
    reason: str
    entity: str | None = None
    period: str | None = None
    severity: str = "info"       # info | warn | critical
    needs_review: bool = False
    evidence: dict = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DataQualityAgent:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.decisions: list[Decision] = []
        with open(CONFIG_DIR / "calendar.yaml", encoding="utf-8") as fh:
            self.calendar = yaml.safe_load(fh)
        approvals_path = CONFIG_DIR / "approvals.yaml"
        self.approvals = {}
        if approvals_path.exists():
            with open(approvals_path, encoding="utf-8") as fh:
                for a in (yaml.safe_load(fh) or {}).get("approvals", []):
                    self.approvals[(a["check_id"], a.get("key", ""))] = a

    # ------------------------------------------------------------------ logging
    def decide(self, **kw) -> Decision:
        d = Decision(**kw)
        self.decisions.append(d)
        return d

    def log_frame(self) -> pd.DataFrame:
        rows = []
        for i, d in enumerate(self.decisions, start=1):
            r = asdict(d)
            r["evidence"] = json.dumps(d.evidence, default=str)
            key = f"{d.entity or ''}|{d.period or ''}"
            appr = self.approvals.get((d.check_id, key))
            r["review_status"] = ("approved by " + appr["by"]) if (d.needs_review and appr) else (
                "pending human review" if d.needs_review else "auto")
            r["decision_id"] = f"{self.run_id}-{i:04d}"
            r["run_id"] = self.run_id
            r["decided_at_utc"] = _now()
            rows.append(r)
        cols = ["decision_id", "run_id", "decided_at_utc", "check_id", "tool", "rule", "table_name",
                "entity", "period", "action", "rows_affected", "severity", "reason", "needs_review",
                "review_status", "evidence"]
        return pd.DataFrame(rows, columns=cols)

    def _in_ramadan(self, period: pd.Timestamp) -> bool:
        start, end = period, period + pd.offsets.MonthEnd(0)
        for r in self.calendar["ramadan"]:
            if pd.Timestamp(r["start"]) <= end and pd.Timestamp(r["end"]) >= start:
                return True
        return False

    # ------------------------------------------------------------------ fetch
    def review_fetch(self, fetch_results: list) -> None:
        for r in fetch_results:
            if r.status == "failed":
                self.decide(
                    check_id="DQ-SRC-MISSING", tool="http_fetch", rule="Every registered source file must be retrievable",
                    table_name="raw", action="FLAG", rows_affected=0, severity="warn", period=r.file_id,
                    reason=f"Publisher link is broken ({r.detail.split(' for url')[0]}). The month is treated as missing; "
                           "nothing is imputed for it.", evidence={"file_id": r.file_id, "error": r.detail})
            elif r.status == "changed":
                imm = "immutable" in r.detail
                self.decide(
                    check_id="DQ-SRC-CHANGED", tool="sha256_manifest", rule="Raw file SHA-256 must match manifest.csv",
                    table_name="raw", action="FLAG", rows_affected=0, severity="critical" if imm else "info",
                    needs_review=imm, period=r.file_id,
                    reason=("Publisher replaced a file we had already used; the new version is used and the "
                            "old hash is kept in git history." if imm else "Revisable source updated (expected)."),
                    evidence={"file_id": r.file_id, "detail": r.detail})

    # ------------------------------------------------------------------ ISMO
    def review_ismo(self, staged: list[dict]) -> dict[str, pd.DataFrame]:
        """staged: [{file_id, period, published, title, tables: {...}}] -> cleaned tables."""
        # 1. aggregation basis: a monthly table must hold monthly averages
        monthly = []
        for s in staged:
            energy = s["tables"].get("energy")
            label = str(energy["avg_label"].iloc[0]) if energy is not None and len(energy) else ""
            single_day = label.lower().startswith("grand total") or "28-02-23" in s["title"]
            if single_day:
                n = sum(len(t) for t in s["tables"].values())
                self.decide(
                    check_id="DQ-ISMO-AGG", tool="aggregation_detector", table_name="ismo_profile",
                    rule="Monthly profile tables must contain monthly averages",
                    action="FLAG", rows_affected=n, severity="warn", needs_review=True,
                    period=s["period"], entity=None,
                    reason=f"'{s['title']}' is a one-day snapshot (column '{label}', integer MWh) rather than a "
                           "monthly average. Kept in raw, excluded from monthly cleaned/gold tables.",
                    evidence={"file_id": s["file_id"], "avg_label": label})
            else:
                monthly.append(s)

        # 2. duplicate uploads for the same month: keep ISMO's latest upload
        by_period: dict[str, list[dict]] = {}
        for s in monthly:
            by_period.setdefault(s["period"], []).append(s)
        kept = []
        for period, files in sorted(by_period.items()):
            files = sorted(files, key=lambda s: (s["published"], s["file_id"]))
            keep = files[-1]
            kept.append(keep)
            for dup in files[:-1]:
                same = _same_tables(dup["tables"], keep["tables"])
                self.decide(
                    check_id="DQ-ISMO-DUP", tool="duplicate_detector", table_name="ismo_profile",
                    rule="One publication per month; ISMO's latest upload supersedes earlier ones",
                    action="FIX", rows_affected=sum(len(t) for t in dup["tables"].values()),
                    severity="info" if same else "warn", needs_review=not same, period=period,
                    reason=(f"Duplicate upload {dup['file_id']} is identical to {keep['file_id']}; dropped."
                            if same else f"Upload {dup['file_id']} differs from later upload {keep['file_id']}; "
                            "the later one is treated as ISMO's correction."),
                    evidence={"dropped": dup["file_id"], "kept": keep["file_id"], "identical": same})

        profiles, energies, nationals, genmixes = [], [], [], []
        for s in kept:
            t = s["tables"]
            period_ts = pd.Timestamp(s["period"] + "-01")
            if "profile" not in t:
                self.decide(
                    check_id="DQ-ISMO-NOPROFILE", tool="sheet_inventory", table_name="ismo_profile",
                    rule="Each monthly workbook should contain hourly demand sheets",
                    action="FLAG", rows_affected=0, severity="warn", period=s["period"],
                    reason="ISMO published only monthly energy for this month (no KE-Demand / DISCOs Demand sheets). "
                           "A whole month of hourly data is a long gap: flagged, not imputed.",
                    evidence={"file_id": s["file_id"], "sheets": list(t)})
            else:
                p = t["profile"].copy()
                p["period"] = period_ts
                p["published"] = s["published"]
                profiles.append(p)
            if "energy" in t:
                e = t["energy"].copy()
                e["period"] = period_ts
                energies.append(self._fix_energy_basis(e, s))
            if "national" in t:
                n = t["national"].copy(); n["period"] = period_ts; nationals.append(n)
            if "genmix" in t:
                g = t["genmix"].copy(); g["period"] = period_ts; genmixes.append(g)

        profile = pd.concat(profiles, ignore_index=True) if profiles else pd.DataFrame()
        energy = pd.concat(energies, ignore_index=True) if energies else pd.DataFrame()
        profile["demand_mw"] = pd.to_numeric(profile["demand_mw"], errors="coerce").astype(float)
        profile["dq_flags"] = ""
        profile["exclude"] = False
        energy["dq_flags"] = ""
        energy["exclude"] = False

        profile = self._check_profile_completeness(profile)
        profile = self._check_copied_profiles(profile)
        energy = self._check_stale_energy(energy)
        profile = self._check_profile_vs_energy(profile, energy)
        profile = self._check_spikes(profile)
        profile = self._check_missing_months(profile)

        fails = schemas.run_schema(schemas.profile_schema, profile[["entity", "period", "hour", "demand_mw"]])
        bad_idx = {int(f["index"]) for f in fails if f["index"] not in ("None", "nan")}
        self.decide(
            check_id="DQ-ISMO-SCHEMA", tool="pandera:profile_schema", table_name="ismo_profile",
            rule="entity known; hour 0-23; 0 < demand_mw < 15,000; unique (entity, period, hour)",
            action="FLAG" if fails else "PASS", rows_affected=len(bad_idx), severity="critical" if fails else "info",
            reason=(f"{len(fails)} schema failures; offending rows excluded from gold." if fails
                    else "All rows pass the profile schema."),
            evidence={"failures": fails[:20]})
        profile.loc[list(bad_idx), "exclude"] = True

        fails_e = schemas.run_schema(schemas.energy_schema, energy[["entity", "period", "avg_daily_mwh"]])
        self.decide(
            check_id="DQ-ISMO-ENERGY-SCHEMA", tool="pandera:energy_schema", table_name="ismo_energy",
            rule="0 < average daily MWh < 400,000; unique (entity, period)",
            action="FLAG" if fails_e else "PASS", rows_affected=len(fails_e),
            reason=f"{len(fails_e)} failures." if fails_e else "All rows pass the energy schema.",
            evidence={"failures": fails_e[:20]})

        national = pd.concat(nationals, ignore_index=True) if nationals else pd.DataFrame()
        genmix = pd.concat(genmixes, ignore_index=True) if genmixes else pd.DataFrame()
        if not national.empty:
            national["national_demand_mw"] = pd.to_numeric(national["national_demand_mw"], errors="coerce")
            national["marginal_cost"] = pd.to_numeric(national["marginal_cost"], errors="coerce")
        return {"profile": profile, "energy": energy, "national": national, "genmix": genmix}

    def _fix_energy_basis(self, e: pd.DataFrame, s: dict) -> pd.DataFrame:
        """'Total Energy (GWh)' is a daily figure in most files but a monthly total in some.
        Detect the basis from the ratio to 'Avg' (MWh/day) and standardise."""
        e = e.copy()
        e["avg_daily_mwh"] = pd.to_numeric(e["avg_mwh"], errors="coerce").astype(float)
        tot = pd.to_numeric(e["total_energy_gwh"], errors="coerce").astype(float)
        days = pd.Timestamp(s["period"] + "-01").days_in_month
        ratio = float(np.nanmedian(tot * 1000 / e["avg_daily_mwh"]))
        if abs(ratio - days) < 1.5:
            self.decide(
                check_id="DQ-ISMO-UNIT", tool="unit_basis_detector", table_name="ismo_energy",
                rule="Energy columns must share one basis (GWh per day)",
                action="FIX", rows_affected=len(e), severity="info", period=s["period"],
                reason=f"'Total Energy (GWh)' is a monthly total here (ratio to daily average = {ratio:.1f} ~ {days} days); "
                       "converted to GWh/day. Certain and reversible.",
                evidence={"file_id": s["file_id"], "ratio": round(ratio, 2), "days": days})
        elif abs(ratio - 1) > 0.05:
            self.decide(
                check_id="DQ-ISMO-UNIT", tool="unit_basis_detector", table_name="ismo_energy",
                rule="Energy columns must share one basis (GWh per day)", action="FLAG",
                rows_affected=len(e), severity="warn", period=s["period"],
                reason=f"Unexpected Total/Avg ratio {ratio:.2f}; reported total ignored, daily average kept.",
                evidence={"file_id": s["file_id"], "ratio": round(ratio, 2)})
        e["energy_daily_gwh"] = e["avg_daily_mwh"] / 1000
        e["energy_month_gwh"] = e["avg_daily_mwh"] * days / 1000
        e["share"] = pd.to_numeric(e["share"], errors="coerce").astype(float)
        return e[["file_id", "period", "entity", "avg_daily_mwh", "energy_daily_gwh", "energy_month_gwh", "share"]]

    def _check_profile_completeness(self, p: pd.DataFrame) -> pd.DataFrame:
        counts = p.groupby(["entity", "period"])["hour"].nunique()
        incomplete = counts[counts != 24]
        for (ent, per), n in incomplete.items():
            idx = (p.entity == ent) & (p.period == per)
            p.loc[idx, "dq_flags"] += "DQ-ISMO-HOURS;"
            self.decide(
                check_id="DQ-ISMO-HOURS", tool="completeness_check", table_name="ismo_profile",
                rule="Each entity-month profile must have 24 hours", action="FLAG", rows_affected=int(idx.sum()),
                severity="warn", entity=ent, period=per.strftime("%Y-%m"),
                reason=f"Only {n} of 24 hours present; missing hours are not filled.", evidence={"hours": int(n)})
        if incomplete.empty:
            self.decide(check_id="DQ-ISMO-HOURS", tool="completeness_check", table_name="ismo_profile",
                        rule="Each entity-month profile must have 24 hours", action="PASS", rows_affected=0,
                        reason=f"All {len(counts)} entity-months have 24 hours.")
        return p

    def _check_copied_profiles(self, p: pd.DataFrame) -> pd.DataFrame:
        """A publisher sometimes re-uploads last month's numbers under a new month. Identical
        24-hour profiles in consecutive months are not a real month: the later copy is excluded."""
        wide = p.pivot_table(index=["entity", "period"], columns="hour", values="demand_mw")
        periods = sorted(p["period"].unique())
        consecutive = [(a, b) for a, b in zip(periods, periods[1:]) if b == a + pd.offsets.MonthBegin(1)]
        for a, b in consecutive:
            copied = []
            for ent in p["entity"].unique():
                if (ent, a) in wide.index and (ent, b) in wide.index:
                    if np.allclose(wide.loc[(ent, a)].values, wide.loc[(ent, b)].values, rtol=0, atol=1e-6):
                        copied.append(ent)
            if not copied:
                continue
            idx = p.period.eq(b) & p.entity.isin(copied)
            p.loc[idx, "exclude"] = True
            p.loc[idx, "dq_flags"] += "DQ-ISMO-COPY;"
            whole = len(copied) == p.loc[p.period == b, "entity"].nunique()
            self.decide(
                check_id="DQ-ISMO-COPY", tool="copy_detector", table_name="ismo_profile",
                rule="A month's 24-hour profile must not be byte-identical to the previous month's",
                action="FLAG", rows_affected=int(idx.sum()), severity="warn", needs_review=True,
                entity=None if whole else ",".join(copied), period=b.strftime("%Y-%m"),
                reason=(f"All {len(copied)} entities' {b:%b %Y} profiles are identical to {a:%b %Y}: a re-upload of the "
                        f"previous month, not new data. {b:%b %Y} is excluded from gold (kept in cleaned)."
                        if whole else f"{', '.join(copied)} profile for {b:%b %Y} repeats {a:%b %Y} exactly; "
                        "that entity-month is excluded from gold."),
                evidence={"copied_from": a.strftime("%Y-%m"), "entities": copied})
        return p

    def _check_stale_energy(self, e: pd.DataFrame) -> pd.DataFrame:
        """Monthly energy repeated exactly from the previous month (for all entities = copied month;
        for one entity while others change = value the publisher forgot to update)."""
        e = e.sort_values(["entity", "period"]).reset_index(drop=True)
        # an exact float repeat of ANY earlier month for the same entity is a copy, not a coincidence
        same = e.assign(_v=e["avg_daily_mwh"].round(6)).duplicated(["entity", "_v"], keep="first")
        for per, g in e[same].groupby("period"):
            n_all = int((e.period == per).sum())
            idx = same & e.period.eq(per)
            e.loc[idx, ["exclude"]] = True
            e.loc[idx, "dq_flags"] += "DQ-ISMO-STALE;"
            whole = int(idx.sum()) >= n_all - 1
            ents = sorted(g["entity"])
            self.decide(
                check_id="DQ-ISMO-STALE", tool="stale_value_detector", table_name="ismo_energy",
                rule="Monthly energy should not exactly repeat an earlier month's value",
                action="FLAG", rows_affected=int(idx.sum()), severity="warn", needs_review=whole,
                entity=None if whole else ",".join(ents), period=per.strftime("%Y-%m"),
                reason=(f"Monthly energy for all entities in {per:%b %Y} repeats an earlier month exactly: copied table. "
                        "Excluded from gold." if whole else
                        f"{', '.join(ents)} energy in {per:%b %Y} exactly repeats an earlier month while other entities "
                        "changed: a value the publisher did not update. Excluded from gold; the hourly profile is trusted."),
                evidence={"entities": ents})
        return e

    def _check_profile_vs_energy(self, p: pd.DataFrame, e: pd.DataFrame) -> pd.DataFrame:
        if e.empty:
            return p
        mean_mw = p[~p.exclude].groupby(["entity", "period"])["demand_mw"].mean().rename("mean_mw").reset_index()
        m = mean_mw.merge(e[["entity", "period", "avg_daily_mwh", "exclude"]], on=["entity", "period"], how="inner")
        m["ratio"] = m["mean_mw"] * 24 / m["avg_daily_mwh"]
        bad = m[(m["ratio"] - 1).abs() > CONSISTENCY_TOL]
        for _, r in bad.iterrows():
            idx = (p.entity == r.entity) & (p.period == r.period)
            explained = bool(r.exclude)
            p.loc[idx, "dq_flags"] += "DQ-ISMO-CONSIST-EXPLAINED;" if explained else "DQ-ISMO-CONSIST;"
            self.decide(
                check_id="DQ-ISMO-CONSIST", tool="cross_sheet_consistency", table_name="ismo_profile",
                rule=f"Hourly profile x 24 h should match reported daily energy within {CONSISTENCY_TOL:.0%}",
                action="FLAG", rows_affected=int(idx.sum()), severity="info" if explained else "warn", entity=r.entity,
                period=r.period.strftime("%Y-%m"),
                reason=(f"Profile implies {r.mean_mw * 24:,.0f} MWh/day vs {r.avg_daily_mwh:,.0f} reported (ratio {r.ratio:.2f}). "
                        + ("Explained: the energy figure is a stale repeat (DQ-ISMO-STALE), so the profile is kept as the "
                           "trusted value." if explained else
                           "Cannot tell which sheet is right, so both are kept and flagged.")),
                evidence={"ratio": round(float(r.ratio), 3), "energy_stale": explained})
        self.decide(
            check_id="DQ-ISMO-CONSIST-SUMMARY", tool="cross_sheet_consistency", table_name="ismo_profile",
            rule="Profile vs energy agreement", action="PASS" if bad.empty else "FLAG",
            rows_affected=int(len(bad) * 24), severity="info",
            reason=f"{len(m) - len(bad)} of {len(m)} entity-months agree within {CONSISTENCY_TOL:.0%}; "
                   f"median ratio {m['ratio'].median():.3f}.",
            evidence={"median_ratio": round(float(m['ratio'].median()), 4), "n": int(len(m))})
        return p

    def _check_spikes(self, p: pd.DataFrame) -> pd.DataFrame:
        """Detect sharp hour-to-hour jumps, then try to *explain* them before flagging:
        Ramadan sehri (02-06 PKT) / iftar (17-19 PKT) windows, or a recurring structural
        pattern (same entity, same hours, >= 3 months: scheduled load management)."""
        p = p.sort_values(["entity", "period", "hour"]).reset_index(drop=True)
        found = []
        for (ent, per), g in p[~p.exclude].groupby(["entity", "period"]):
            if len(g) < 24:
                continue
            jumps = g["demand_mw"].diff().abs() / g["demand_mw"].median()
            spikes = g.index[jumps > SPIKE_RATIO]
            if len(spikes):
                found.append((ent, per, spikes, sorted(int(p.loc[i, "hour"]) for i in spikes), float(jumps.max())))
        recurring: dict[tuple[str, int], int] = {}
        for ent, _, _, hours, _ in found:
            for h in hours:
                recurring[(ent, h)] = recurring.get((ent, h), 0) + 1
        for ent, per, spikes, hours, jmax in found:
            ramadan_hours = [h for h in hours if self._in_ramadan(per) and (2 <= h <= 6 or 17 <= h <= 19)]
            rec_hours = [h for h in hours if recurring[(ent, h)] >= 3]
            unexplained = [h for h in hours if h not in ramadan_hours and h not in rec_hours]
            p.loc[spikes, "dq_flags"] += "DQ-ISMO-SPIKE;"
            parts = []
            if ramadan_hours:
                parts.append(f"hours {ramadan_hours} fall in Ramadan sehri/iftar windows")
            if rec_hours:
                parts.append(f"hours {rec_hours} recur in >= 3 months for {ent} (structural, e.g. scheduled load management)")
            if unexplained:
                parts.append(f"hours {unexplained} unexplained")
            self.decide(
                check_id="DQ-ISMO-SPIKE", tool="robust_spike_detector", table_name="ismo_profile",
                rule=f"Hour-to-hour change above {SPIKE_RATIO:.0%} of the month's median demand",
                action="FLAG", rows_affected=len(spikes), severity="warn" if unexplained else "info",
                entity=ent, period=per.strftime("%Y-%m"),
                reason="Jumps kept (not smoothed): " + "; ".join(parts) + ".",
                evidence={"hours": hours, "max_jump_ratio": round(jmax, 3), "ramadan_hours": ramadan_hours,
                          "recurring_hours": rec_hours})
        return p

    def _check_missing_months(self, p: pd.DataFrame) -> pd.DataFrame:
        have = sorted(p.loc[~p.exclude, "period"].unique())
        full = pd.date_range(have[0], have[-1], freq="MS")
        missing = [d.strftime("%Y-%m") for d in full if d not in set(have)]
        self.decide(
            check_id="DQ-ISMO-GAPS", tool="calendar_gap_detector", table_name="ismo_profile",
            rule="Monthly series should be continuous", action="FLAG" if missing else "PASS",
            rows_affected=len(missing) * len(ENTITY_ORDER) * 24, severity="warn" if missing else "info",
            reason=(f"{len(missing)} months have no usable hourly profile (not published, broken link, or a copied "
                    f"month): {', '.join(missing)}. Long gaps are not imputed; the model and baseline skip them."
                    if missing else "No missing months."),
            evidence={"missing_months": missing, "usable_months": len(have)})
        return p

    # ------------------------------------------------------------------ price
    def review_price(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["date_pkt"] = pd.to_datetime(df["date_pkt"]).dt.normalize()
        df["hour_pkt"] = pd.to_numeric(df["hour_pkt"], errors="coerce").astype("Int64")
        df["price_rs_kwh"] = pd.to_numeric(df["price_rs_kwh"], errors="coerce")
        n0 = len(df)
        df = df.dropna(subset=["date_pkt", "hour_pkt"])
        dups = df.duplicated(["date_pkt", "hour_pkt"], keep="last")
        if dups.any():
            self.decide(check_id="DQ-PRICE-DUP", tool="duplicate_detector", table_name="price_hourly",
                        rule="One price per PKT date-hour", action="FIX", rows_affected=int(dups.sum()),
                        reason="Repeated date-hour rows; the last occurrence is kept.")
        df = df[~dups]
        df["ts_utc"] = (df["date_pkt"] + pd.to_timedelta(df["hour_pkt"].astype(int), unit="h")
                        - pd.Timedelta(hours=PKT_OFFSET_HOURS)).dt.tz_localize("UTC")
        self.decide(check_id="DQ-PRICE-TZ", tool="timezone_normaliser", table_name="price_hourly",
                    rule="Store timestamps in UTC; convert to PKT only for display", action="FIX",
                    rows_affected=len(df), reason="ISMO hours are PKT (UTC+5, hour-beginning); converted to UTC.",
                    evidence={"rows_in": n0})
        full = pd.date_range(df["ts_utc"].min(), df["ts_utc"].max(), freq="h")
        missing = full.difference(df["ts_utc"])
        self.decide(check_id="DQ-PRICE-GAPS", tool="calendar_gap_detector", table_name="price_hourly",
                    rule="Hourly price series should be continuous", action="FLAG" if len(missing) else "PASS",
                    rows_affected=len(missing), severity="warn" if len(missing) else "info",
                    reason=(f"{len(missing)} hours missing; prices are not smooth, so gaps are flagged, not filled."
                            if len(missing) else "No missing hours."),
                    evidence={"first_missing": [str(x) for x in missing[:10]]})
        df["dq_flags"] = ""
        neg = df["price_rs_kwh"] < 0
        med = df["price_rs_kwh"].median()
        mad = (df["price_rs_kwh"] - med).abs().median() or 1.0
        outl = ((df["price_rs_kwh"] - med).abs() / (1.4826 * mad)) > 8
        df.loc[neg, "dq_flags"] += "DQ-PRICE-NEG;"
        df.loc[outl, "dq_flags"] += "DQ-PRICE-OUTLIER;"
        self.decide(check_id="DQ-PRICE-RANGE", tool="robust_zscore", table_name="price_hourly",
                    rule="Price >= 0; robust z-score <= 8", action="FLAG" if (neg.any() or outl.any()) else "PASS",
                    rows_affected=int(neg.sum() + outl.sum()),
                    reason=f"{int(neg.sum())} negative and {int(outl.sum())} extreme prices kept but flagged "
                           "(cannot be confirmed as errors).",
                    evidence={"median": round(float(med), 2), "max": round(float(df['price_rs_kwh'].max()), 2)})
        # regime shift ISMO itself reports (Middle East fuel crisis from Feb 2026)
        pre = df[df["date_pkt"] < "2026-02-01"]["price_rs_kwh"].dropna()
        post = df[df["date_pkt"] >= "2026-02-01"]["price_rs_kwh"].dropna()
        if len(pre) and len(post):
            shift = post.mean() / pre.mean() - 1
            self.decide(check_id="DQ-PRICE-DRIFT", tool="distribution_shift_test", table_name="price_hourly",
                        rule="Flag mean shifts > 15% between regimes", action="FLAG" if abs(shift) > 0.15 else "PASS",
                        rows_affected=len(post) if abs(shift) > 0.15 else 0, severity="warn" if abs(shift) > 0.15 else "info",
                        reason=f"Mean price from Feb 2026 is {shift:+.0%} vs before; ISMO attributes this to Middle East "
                               "fuel-supply disruption. Cost estimates are reported per regime.",
                        evidence={"pre_mean": round(float(pre.mean()), 2), "post_mean": round(float(post.mean()), 2)})
        fails = schemas.run_schema(schemas.price_schema, df[["ts_utc", "hour_pkt", "price_rs_kwh"]])
        if fails:
            self.decide(check_id="DQ-PRICE-SCHEMA", tool="pandera:price_schema", table_name="price_hourly",
                        rule="Price schema", action="FLAG", rows_affected=len(fails), severity="warn",
                        reason=f"{len(fails)} schema failures.", evidence={"failures": fails[:10]})
        return df[["file_id", "ts_utc", "date_pkt", "hour_pkt", "price_rs_kwh", "dq_flags"]].reset_index(drop=True)

    # ------------------------------------------------------------------ weather
    def review_weather(self, df: pd.DataFrame, table_name: str = "weather_hourly") -> pd.DataFrame:
        value_cols = ["temp_c", "rh_pct", "dewpoint_c", "apparent_c", "precip_mm", "cloud_pct", "wind_kmh", "swrad_wm2"]
        out = []
        for ent, g in df.groupby("entity", sort=False):
            g = g.sort_values("ts_utc")
            dups = g.duplicated(["ts_utc"], keep="last")
            if dups.any():
                self.decide(check_id="DQ-WX-DUP", tool="duplicate_detector", table_name=table_name, entity=ent,
                            rule="One record per entity-hour", action="FIX", rows_affected=int(dups.sum()),
                            reason="Duplicate timestamps; last kept.")
                g = g[~dups]
            # Kelvin guard: an obvious unit error with a known conversion is fixed
            kelvin = g["temp_c"] > 150
            if kelvin.any():
                g.loc[kelvin, ["temp_c", "dewpoint_c", "apparent_c"]] -= 273.15
                self.decide(check_id="DQ-WX-UNIT", tool="unit_check", table_name=table_name, entity=ent,
                            rule="Temperatures in deg C", action="FIX", rows_affected=int(kelvin.sum()),
                            reason="Values in Kelvin converted to deg C (known conversion).")
            g = g.set_index("ts_utc")
            full = pd.date_range(g.index.min(), g.index.max(), freq="h", tz="UTC")
            g = g.reindex(full)
            g.index.name = "ts_utc"
            g["entity"] = ent
            g["file_id"] = g["file_id"].ffill().bfill()
            g["is_filled"] = False
            g["dq_flags"] = ""
            for col in value_cols:
                isna = g[col].isna()
                if not isna.any():
                    continue
                run_id = (isna != isna.shift()).cumsum()
                run_len = isna.groupby(run_id).transform("sum")
                short = isna & (run_len <= MAX_FILL_GAP_HOURS)
                long_ = isna & (run_len > MAX_FILL_GAP_HOURS)
                if short.any():
                    filled = g[col].interpolate(limit_area="inside")
                    g.loc[short, col] = filled[short]   # only short gaps; long gaps stay missing
                    g.loc[short & g[col].notna(), "is_filled"] = True
                    self.decide(check_id="DQ-WX-FILL", tool="gap_detector", table_name=table_name, entity=ent,
                                rule=f"Gaps <= {MAX_FILL_GAP_HOURS} h in smooth hourly series", action="FILL",
                                rows_affected=int(short.sum()),
                                reason=f"{col}: short gaps linearly interpolated and marked is_filled=True.")
                if long_.any():
                    g.loc[long_, "dq_flags"] += f"DQ-WX-GAP:{col};"
                    self.decide(check_id="DQ-WX-GAP", tool="gap_detector", table_name=table_name, entity=ent,
                                rule=f"Gaps > {MAX_FILL_GAP_HOURS} h", action="FLAG", rows_affected=int(long_.sum()),
                                severity="warn", reason=f"{col}: long gaps kept as missing (never zero).")
            out.append(g.reset_index())
        res = pd.concat(out, ignore_index=True)
        fails = schemas.run_schema(schemas.weather_schema, res[["entity", "ts_utc"] + value_cols])
        bad_idx = {int(f["index"]) for f in fails if f["index"] not in ("None", "nan")}
        if bad_idx:
            res.loc[list(bad_idx), "dq_flags"] += "DQ-WX-RANGE;"
        self.decide(check_id="DQ-WX-SCHEMA", tool="pandera:weather_schema", table_name=table_name,
                    rule="Physical ranges (temp -40..60 C, RH 0..100%, radiation 0..1400 W/m2, ...)",
                    action="FLAG" if fails else "PASS", rows_affected=len(bad_idx),
                    severity="warn" if fails else "info",
                    reason=(f"{len(fails)} out-of-range values flagged." if fails else
                            f"All {len(res):,} entity-hours within physical ranges."),
                    evidence={"failures": fails[:10]})
        return res

    # ------------------------------------------------------------------ documents
    def review_documents(self, entries: dict) -> None:
        """Trusted RAG documents must exist and be what they claim to be (PDF magic bytes / HTML)."""
        from ..config import ROOT
        docs = [e for e in entries.values() if e.source == "document"]
        bad = []
        for e in docs:
            p = ROOT / e.local_path
            head = p.read_bytes()[:512] if p.exists() else b""
            ok = head.startswith(b"%PDF") if e.local_path.endswith(".pdf") else b"<html" in head.lower() or b"<!doctype" in head.lower()
            if not ok:
                bad.append(e.file_id)
        self.decide(check_id="DQ-DOC-VALID", tool="file_signature_check", table_name="documents",
                    rule="Each trusted document must exist and match its declared type", action="FLAG" if bad else "PASS",
                    rows_affected=len(bad), severity="warn" if bad else "info",
                    reason=(f"Invalid or missing documents: {bad}; they are left out of the index." if bad else
                            f"All {len(docs)} trusted documents present and valid."), evidence={"bad": bad})

    # ------------------------------------------------------------------ freshness
    def review_freshness(self, latest_ismo_period: pd.Timestamp, live_snapshot_utc: pd.Timestamp | None,
                         now: pd.Timestamp | None = None) -> dict:
        now = now or pd.Timestamp.now(tz="UTC")
        month_end = (latest_ismo_period + pd.offsets.MonthEnd(0)).tz_localize("UTC")
        age_days = (now - month_end).days
        stale = age_days > STALE_ISMO_DAYS
        self.decide(check_id="DQ-FRESH-ISMO", tool="freshness_check", table_name="ismo_profile",
                    rule=f"Latest ISMO month should end < {STALE_ISMO_DAYS} days ago", action="FLAG" if stale else "PASS",
                    rows_affected=0, severity="warn" if stale else "info",
                    reason=f"Latest ISMO month {latest_ismo_period:%Y-%m} ended {age_days} days ago"
                           + (" - stale; dashboard must show it." if stale else " - within ISMO's normal publication lag."),
                    evidence={"age_days": age_days})
        status = {"ismo_latest_period": latest_ismo_period.strftime("%Y-%m"), "ismo_age_days": age_days, "ismo_stale": stale}
        if live_snapshot_utc is not None:
            age_h = (now - live_snapshot_utc).total_seconds() / 3600
            late = age_h > STALE_LIVE_HOURS
            self.decide(check_id="DQ-FRESH-LIVE", tool="freshness_check", table_name="weather_live",
                        rule=f"Live weather snapshot younger than {STALE_LIVE_HOURS} h", action="FLAG" if late else "PASS",
                        rows_affected=0, severity="warn" if late else "info",
                        reason=f"Latest snapshot is {age_h:.1f} h old.", evidence={"age_hours": round(age_h, 2)})
            status.update({"live_snapshot_utc": str(live_snapshot_utc), "live_age_hours": round(age_h, 2), "live_stale": late})
        return status


def _same_tables(a: dict, b: dict) -> bool:
    if set(a) != set(b):
        return False
    for k in a:
        x = a[k].drop(columns=["file_id", "period"], errors="ignore").reset_index(drop=True)
        y = b[k].drop(columns=["file_id", "period"], errors="ignore").reset_index(drop=True)
        if x.shape != y.shape or not x.equals(y):
            return False
    return True
