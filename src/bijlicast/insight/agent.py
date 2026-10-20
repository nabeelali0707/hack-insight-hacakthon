"""BijliCast Insight Agent (RAG) - cited answers for K-Electric and DISCO planners.

Hard rules (participant guide, chapter 9):
  1. No number from the LLM: every number is read from a gold table by code and the answer
     stores the row IDs it used.
  2. No claim without a source: recommendations cite a trusted document and page.
  3. "I don't know" when the tables or documents do not support an answer, saying what is missing.

Flow: parse (language, entity, month, intent) -> tools (SQL on gold tables) -> premise check ->
retrieval (official documents) -> deterministic bilingual draft with placeholders -> optional
LLM wording (insight/wording.py, number-guarded) -> log to gold.insight_log.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd

from ..warehouse import connect
from . import wording

ENTITY_TERMS = {
    "KE": ["k-electric", "k electric", "kelectric", "kesc", "karachi", "کراچی", "کے الیکٹرک", "کے-الیکٹرک"],
    "LESCO": ["lesco", "lahore", "لاہور", "لیسکو"],
    "FESCO": ["fesco", "faisalabad", "فیصل آباد", "فیسکو"],
    "GEPCO": ["gepco", "gujranwala", "گوجرانوالہ", "گیپکو"],
    "IESCO": ["iesco", "islamabad", "rawalpindi", "اسلام آباد", "راولپنڈی", "آئیسکو"],
    "MEPCO": ["mepco", "multan", "ملتان", "میپکو"],
    "PESCO": ["pesco", "peshawar", "پشاور", "پیسکو"],
    "QESCO": ["qesco", "quetta", "کوئٹہ", "کیسکو"],
    "HESCO": ["hesco", "hyderabad", "حیدرآباد", "حیسکو"],
    "SEPCO": ["sepco", "sukkur", "سکھر", "سیپکو"],
}
NAMES = {"KE": ("K-Electric (Karachi)", "کے الیکٹرک (کراچی)")}
UNCOVERED = ["tesco", "gilgit", "skardu", "muzaffarabad", "azad kashmir", "ajk", "gwadar", "chitral",
             "گلگت", "سکردو", "مظفرآباد", "گوادر"]
MONTHS_EN = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], start=1)}
MONTHS_EN.update({k[:3]: v for k, v in list(MONTHS_EN.items())})
MONTHS_UR = {"جنوری": 1, "فروری": 2, "مارچ": 3, "اپریل": 4, "مئی": 5, "جون": 6, "جولائی": 7, "اگست": 8,
             "ستمبر": 9, "اکتوبر": 10, "نومبر": 11, "دسمبر": 12}
UR_MONTH_NAME = {v: k for k, v in MONTHS_UR.items()}
URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

INTENT_WORDS = {
    "peak_cost": ["cost", "saving", "save", "shift", "marginal price", "expensive", "cheap", "rupee", " rs",
                  "price", "لاگت", "بچت", "مہنگ", "قیمت", "سستا"],
    "accuracy": ["accura", "error", "mape", "baseline", "how good", "reliab", "weakest", "worst", "beat",
                 "trust", "درست", "غلطی", "بیس لائن"],
    "quality": ["quality", "flag", "missing", "stale", "copied", "duplicate", "gap", "data problem",
                "کوالٹی", "معیار", "غائب"],
    "drift": ["drift", "unusual", "out of range", "abnormal", "غیر معمولی"],
    "forecast": ["forecast", "expect", "outlook", "predict", "will ", "next month", "coming", "this month",
                 "پیشگوئی", "متوقع", "اندازہ", "اگلے", "آنے والے", "اس مہینے"],
    "actual": ["actual", "recorded", "was ", "were ", "history", "historical", "how much did", "last month",
               "fall", "drop", "rise", "increase", "decrease", "jump", "تھی", "تھا", "پچھلے"],
}
DOC_HINTS = ["peak hour", "peak time", "tariff", "time of use", "tou", "net meter", "loss", "load shed",
             "recovery", "igcep", "nepra", "ismo", "helpline", "complain", "fca", "fuel cost", "ctbcm",
             "transmission", "generation capacity", "پیک", "ٹیرف", "لوڈ شیڈنگ", "نیٹ میٹرنگ"]
FALL = re.compile(r"\b(fall|fell|drop|dropped|decreas|declin|lower|down)\w*|کم", re.I)
RISE = re.compile(r"\b(rise|rose|increas|jump|higher|spike|grew|grow|up)\w*|زیادہ|بڑھ", re.I)

T = {
    "forecast": {
        "en": "{name}: the expected grid demand for {month} averages {mean} MW. It peaks at about {peak} MW "
              "around {ph} PKT ({p80} range {lo}-{hi} MW) and is lowest around {mh} ({mn} MW). {rows}",
        "ur": "{name}: {month} کے لیے متوقع گرڈ طلب اوسطاً {mean} میگاواٹ ہے۔ سب سے زیادہ طلب تقریباً {peak} میگاواٹ "
              "{ph} بجے کے قریب (پاکستانی وقت) متوقع ہے ({p80} حد: {lo} سے {hi} میگاواٹ)، اور سب سے کم {mh} بجے ({mn} میگاواٹ)۔ {rows}",
    },
    "forecast_basis": {
        "en": "Basis: ISMO data published up to {lag}; {cov} of the month's weather comes from observations and "
              "forecasts, the rest from climatology. {rows}",
        "ur": "بنیاد: آئی ایس ایم او کا {lag} تک شائع شدہ ڈیٹا؛ مہینے کے موسم کا {cov} حصہ مشاہدات اور پیشگوئی سے، باقی "
              "اوسط موسم سے لیا گیا ہے۔ {rows}",
    },
    "actual": {
        "en": "{name}: in {month}, ISMO recorded an average grid demand of {mean} MW, peaking at {peak} MW around "
              "{ph} PKT and lowest at {mn} MW around {mh}. {rows}",
        "ur": "{name}: {month} میں آئی ایس ایم او کے مطابق اوسط گرڈ طلب {mean} میگاواٹ رہی، سب سے زیادہ {peak} میگاواٹ "
              "{ph} بجے کے قریب اور سب سے کم {mn} میگاواٹ {mh} بجے۔ {rows}",
    },
    "change": {
        "en": "Compared with {prev} ({pmean} MW), that is a change of {chg}. {rows}",
        "ur": "{prev} ({pmean} میگاواٹ) کے مقابلے میں یہ {chg} کی تبدیلی ہے۔ {rows}",
    },
    "premise_false": {
        "en": "The data does not support the premise of the question: {name}'s average demand did not {claimed} "
              "in {month}; it {actual_dir} by {chg} versus {prev}. {rows}",
        "ur": "ڈیٹا سوال کے مفروضے کی تائید نہیں کرتا: {month} میں {name} کی اوسط طلب {claimed_ur} نہیں ہوئی بلکہ "
              "{prev} کے مقابلے میں {chg} {actual_dir_ur}۔ {rows}",
    },
    "peak_cost": {
        "en": "{name}, {month}: at ISMO's hourly marginal prices an average day of grid supply costs about Rs {cost} "
              "million. The evening peak (6-10 PM) uses {eshare} of the energy but {cshare} of the cost. The dearest "
              "hours are {dear} PKT (Rs {dp}/kWh) and the cheapest are {cheap} (Rs {cp}/kWh). Moving {sp} of demand "
              "out of the dearest hours would save about Rs {sm} million a month. {rows}",
        "ur": "{name}، {month}: آئی ایس ایم او کی گھنٹہ وار مارجنل قیمت پر ایک اوسط دن کی گرڈ بجلی تقریباً {cost} ملین روپے "
              "کی ہے۔ شام کے پیک اوقات میں توانائی کا {eshare} حصہ مگر لاگت کا {cshare} حصہ خرچ ہوتا ہے۔ سب سے مہنگے گھنٹے "
              "{dear} ({dp} روپے فی یونٹ) اور سب سے سستے {cheap} ({cp} روپے فی یونٹ) ہیں۔ مہنگے گھنٹوں سے {sp} طلب منتقل "
              "کرنے سے ماہانہ تقریباً {sm} ملین روپے کی بچت ہو سکتی ہے۔ {rows}",
    },
    "accuracy": {
        "en": "On the untouched test months ({months}), the model's error for {name} is {m} MAPE versus {b} for the "
              "declared baseline (same month last year), and {cov} of actual values fell inside the {p80} interval. "
              "Across all ten entities the error is {mall} versus {ball}. {rows}",
        "ur": "ٹیسٹ مہینوں ({months}) میں {name} کے لیے ماڈل کی غلطی {m} ہے جبکہ اعلان شدہ بیس لائن (پچھلے سال کا یہی مہینہ) کی "
              "غلطی {b} تھی؛ {cov} اصل قدریں {p80} حد کے اندر رہیں۔ تمام دس اداروں میں غلطی {mall} بمقابلہ {ball} ہے۔ {rows}",
    },
    "accuracy_weak": {
        "en": "For {name} the model does not beat the baseline, so planners should keep the seasonal figure and use "
              "our range only as a check.",
        "ur": "{name} کے لیے ماڈل بیس لائن سے بہتر نہیں، اس لیے منصوبہ ساز موسمی تخمینہ ہی استعمال کریں اور ہماری حد کو صرف جانچ کے لیے دیکھیں۔",
    },
    "quality": {
        "en": "Data quality for {scope}: the Data Quality Agent's latest run made {nfix} fixes, {nfill} fills and "
              "{nflag} flags (overall status {status}). Most relevant decisions: {items}",
        "ur": "{scope} کے ڈیٹا کا معیار: ڈیٹا کوالٹی ایجنٹ کے تازہ ترین رن میں {nfix} درستیاں، {nfill} خانہ پُری اور {nflag} "
              "نشاندہیاں ہوئیں (مجموعی حالت {status})۔ اہم فیصلے: {items}",
    },
    "drift": {
        "en": "Drift check for {name}: {items}",
        "ur": "{name} کے لیے ڈرفٹ جانچ: {items}",
    },
    "tou": {
        "en": "Recommendation: the forecast peak falls inside K-Electric's Time-of-Use peak window, so target "
              "demand-response and conservation messages there. K-Electric publishes the window as: {quote}",
        "ur": "تجویز: متوقع پیک کے-الیکٹرک کے پیک اوقات کے اندر ہے، اس لیے طلب کم کرنے اور بچت کے پیغامات انہی اوقات میں "
              "دیں۔ کے-الیکٹرک کے مطابق پیک اوقات یہ ہیں: {quote}",
    },
    "tou_off": {
        "en": "Recommendation: K-Electric's grid-draw peak ({ph}) falls outside its Time-of-Use peak window, so "
              "customer ToU messaging alone will not shave it. Plan night-time grid procurement for this peak, and "
              "keep demand-response messages for the evening window K-Electric publishes as: {quote}",
        "ur": "تجویز: کے-الیکٹرک کی گرڈ سے بجلی لینے کا پیک ({ph}) اس کے پیک اوقات سے باہر ہے، اس لیے صرف صارفین کے پیک "
              "اوقات کے پیغامات سے یہ کم نہیں ہوگا۔ رات کے وقت گرڈ سے خریداری کی منصوبہ بندی کریں، اور طلب کم کرنے کے "
              "پیغامات شام کے ان اوقات کے لیے رکھیں: {quote}",
    },
    "docs": {
        "en": "From the official documents: {quotes}",
        "ur": "سرکاری دستاویزات کے مطابق (انگریزی اقتباس): {quotes}",
    },
    "dont_know": {
        "en": "I don't know. {why}",
        "ur": "مجھے معلوم نہیں۔ {why}",
    },
    "footer": {
        "en": "This is planning information, not an official ISMO/NEPRA forecast or dispatch instruction. For outages "
              "and load-shedding schedules contact K-Electric (118) or your DISCO.",
        "ur": "یہ منصوبہ بندی کی معلومات ہیں، آئی ایس ایم او/نیپرا کی سرکاری پیشگوئی یا ہدایت نہیں۔ بجلی کی بندش اور لوڈ شیڈنگ "
              "کے لیے کے-الیکٹرک (ایک ایک آٹھ) یا اپنی ڈسکو سے رابطہ کریں۔",
    },
}


@dataclass
class Answer:
    question: str
    lang: str
    intent: str
    status: str                      # answered | dont_know | corrected_premise
    text: str
    row_ids: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    entity: str | None = None
    month: str | None = None
    llm_used: bool = False
    ask_id: str = ""
    asked_at_utc: str = ""


class Draft:
    """Builds answer text in which every digit is a placeholder filled by code."""

    def __init__(self):
        self.parts: list[str] = []
        self.vals: dict[str, str] = {}
        self.n = self.r = 0
        self.row_ids: list[str] = []
        self.citations: list[dict] = []

    def num(self, v, fmt: str = "{:,.0f}") -> str:
        self.n += 1
        key = "{{N%d}}" % self.n
        self.vals[key] = fmt.format(v) if not isinstance(v, str) else v
        return key

    def ref(self, label: str) -> str:
        self.r += 1
        key = "{{R%d}}" % self.r
        self.vals[key] = label
        return key

    def rows(self, ids: list[str]) -> str:
        ids = [i for i in ids if i]
        self.row_ids += ids
        if not ids:
            return ""
        shown = ids if len(ids) <= 3 else ids[:2] + [f"... +{len(ids) - 2} more"]
        return self.ref("[rows: " + ", ".join(shown) + "]")

    def cite(self, chunk) -> str:
        page = f" p.{int(chunk['page'])}" if pd.notna(chunk.get("page")) else ""
        label = f"{chunk['doc_id']}{page}"
        self.citations.append({"doc_id": chunk["doc_id"], "page": None if not page else int(chunk["page"]),
                               "section": chunk.get("section") or "", "title": chunk["title"],
                               "publisher": chunk["publisher"], "url": chunk["url"], "chunk_id": chunk["chunk_id"]})
        return label

    def add(self, s: str) -> None:
        if s:
            self.parts.append(s)

    def text(self) -> str:
        return "\n\n".join(self.parts)

    def render(self, s: str) -> str:
        for k in sorted(self.vals, key=len, reverse=True):
            s = s.replace(k, self.vals[k])
        return s


def _lang(q: str) -> str:
    return "ur" if re.search(r"[؀-ۿ]", q) else "en"


def _entity(q: str) -> str | None:
    ql = f" {q.lower()} "
    for code, terms in ENTITY_TERMS.items():
        for t in terms:
            if re.search(r"[؀-ۿ]", t):
                if t in q:
                    return code
            elif re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", ql):
                return code
    if re.search(r"(?<![a-z])ke(?![a-z])", ql):
        return "KE"
    return None


def _month(q: str, today: pd.Timestamp) -> pd.Timestamp | None:
    ql = q.lower().translate(URDU_DIGITS)
    this = pd.Timestamp(today.year, today.month, 1)
    if re.search(r"next month|اگلے مہینے|آئندہ مہینے", ql):
        return this + pd.DateOffset(months=1)
    if re.search(r"this month|current month|اس مہینے|رواں مہینے", ql):
        return this
    if re.search(r"last month|previous month|پچھلے مہینے|گزشتہ مہینے", ql):
        return this - pd.DateOffset(months=1)
    year = re.search(r"\b(20\d\d)\b", ql)
    mon = None
    for name, i in sorted(MONTHS_EN.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{name}\b", ql):
            mon = i
            break
    if mon is None:
        for name, i in MONTHS_UR.items():
            if name in q:
                mon = i
                break
    if mon is None:
        return None
    y = int(year.group(1)) if year else (today.year if mon <= today.month + 1 else today.year - 1)
    return pd.Timestamp(y, mon, 1)


def _intent(q: str, month: pd.Timestamp | None, today: pd.Timestamp) -> str:
    ql = f" {q.lower()} "
    scores = {k: sum(w in ql or w in q for w in ws) for k, ws in INTENT_WORDS.items()}
    if FALL.search(q) or RISE.search(q):
        scores["actual"] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        if any(h in ql or h in q for h in DOC_HINTS):
            return "docs"
        if month is not None:
            return "forecast" if month >= pd.Timestamp(today.year, today.month, 1) else "actual"
        return "docs"
    if best in ("forecast", "actual") and month is not None:
        return "forecast" if month >= pd.Timestamp(today.year, today.month, 1) else "actual"
    return best


def _name(code: str, lang: str) -> str:
    if code in NAMES:
        return NAMES[code][0 if lang == "en" else 1]
    return code


def _month_label(d: Draft, m: pd.Timestamp, lang: str) -> str:
    return (m.strftime("%B ") if lang == "en" else UR_MONTH_NAME[m.month] + " ") + d.num(m.year, "{}")


def _hours(d: Draft, hours: str) -> str:
    return ", ".join(d.num(int(h), "{:02d}:00") for h in str(hours).split(","))


class InsightAgent:
    def __init__(self, retriever=None, today: pd.Timestamp | None = None):
        self.con = connect(read_only=True)
        self.today = today or pd.Timestamp.now(tz="Asia/Karachi").tz_localize(None)
        if retriever is None:
            from .index import Retriever
            retriever = Retriever()
        self.ret = retriever

    # ------------------------------------------------------------------ tools (gold tables only)
    def _df(self, sql, params=()):
        return self.con.execute(sql, list(params)).df()

    def tool_forecast(self, ent, m):
        return self._df("""SELECT row_id, hour, pred_mw, lo_mw, hi_mw, weather_coverage, lag_period
                           FROM gold.forecast_outlook WHERE entity=? AND period=? ORDER BY hour""", (ent, m.date()))

    def tool_actual(self, ent, m):
        return self._df("""SELECT row_id, hour_pkt AS hour, demand_mw FROM gold.demand_profile
                           WHERE entity=? AND period=? ORDER BY hour_pkt""", (ent, m.date()))

    def tool_prev_month(self, ent, m):
        return self._df("""SELECT period, avg(demand_mw) AS mean_mw, min(row_id) AS first_row
                           FROM gold.demand_profile WHERE entity=? AND period<? GROUP BY period
                           ORDER BY period DESC LIMIT 1""", (ent, m.date()))

    def tool_peak_cost(self, ent, m):
        df = self._df("SELECT * FROM gold.peak_cost WHERE entity=? AND period<=? ORDER BY period DESC LIMIT 1",
                      (ent, (m or self.today).date()))
        return df

    def tool_accuracy(self, ent):
        g = self._df("SELECT * FROM gold.errors_by_group WHERE group_by='entity' AND group_value=?", (ent,))
        mm = self._df("SELECT * FROM gold.model_metrics")
        return g, mm

    def tool_quality(self, ent, m):
        run = self.con.execute("SELECT max(run_id) FROM quality.quality_log").fetchone()[0]
        q = self._df("""SELECT decision_id, check_id, action, entity, period, rows_affected, reason
                        FROM quality.quality_log WHERE run_id=? AND action IN ('FIX','FILL','FLAG')""", (run,))
        st = self._df("SELECT * FROM quality.status")
        if ent:
            q = q[(q.entity.fillna("").str.contains(ent)) | q.entity.isna()]
        if m is not None:
            mk = m.strftime("%Y-%m")
            hit = q[(q.period == mk) | q.reason.str.contains(mk, regex=False)]
            q = hit if len(hit) else q
        sev = {"DQ-ISMO-COPY": 0, "DQ-ISMO-STALE": 1, "DQ-ISMO-GAPS": 2, "DQ-SRC-MISSING": 3}
        q = q.assign(_o=q.check_id.map(sev).fillna(9)).sort_values(["_o", "decision_id"])
        return q, st

    def tool_drift(self, ent):
        return self._df("SELECT * FROM gold.drift_status WHERE entity=?", (ent,))

    def _missing_month_reason(self, m):
        df = self._df("""SELECT decision_id, reason FROM quality.quality_log WHERE check_id='DQ-ISMO-GAPS'
                         ORDER BY decided_at_utc DESC LIMIT 1""")
        if len(df) and m.strftime("%Y-%m") in df.reason.iloc[0]:
            return df.decision_id.iloc[0]
        return None

    # ------------------------------------------------------------------ answer builders
    def _tou(self, d: Draft, lang: str, peak_hour: int | None = None):
        hits = self.ret.search("Time of Use ToU peak time April October off-peak hours", k=1, doc_ids=["DOC-KETOU"])
        if hits.empty:
            return
        txt = hits.iloc[0]["text"]
        m = re.search(r"Time of Use \(ToU\).{0,160}?Remaining 20 Hours", txt, re.S)
        quote = d.ref(f'"{(m.group(0) if m else txt[:220]).replace(chr(10), " ")}" [{d.cite(hits.iloc[0])}]')
        if peak_hour is None or 18 <= peak_hour <= 22:
            d.add(T["tou"][lang].format(quote=quote))
        else:
            d.add(T["tou_off"][lang].format(ph=d.num(peak_hour, "{:02d}:00"), quote=quote))

    def _forecast(self, d, ent, m, lang):
        fc = self.tool_forecast(ent, m)
        if fc.empty:
            have = self._df("SELECT DISTINCT period FROM gold.forecast_outlook ORDER BY 1")["period"]
            months = " and ".join(pd.Timestamp(p).strftime("%B %Y") for p in have)
            return self._dont_know(d, lang, f"BijliCast only forecasts the current and next month ({months}). "
                                   "For other months see ISMO's IGCEP plan (DOC-IGCEP) for long-term demand scenarios.")
        pk, mn = fc.loc[fc.pred_mw.idxmax()], fc.loc[fc.pred_mw.idxmin()]
        d.add(T["forecast"][lang].format(
            name=_name(ent, lang), month=_month_label(d, m, lang), mean=d.num(fc.pred_mw.mean()),
            peak=d.num(pk.pred_mw), ph=d.num(int(pk.hour), "{:02d}:00"), p80=d.num(80, "{}%"),
            lo=d.num(pk.lo_mw), hi=d.num(pk.hi_mw), mh=d.num(int(mn.hour), "{:02d}:00"), mn=d.num(mn.pred_mw),
            rows=d.rows([pk.row_id, mn.row_id] + [r for r in fc.row_id if r not in (pk.row_id, mn.row_id)])))
        d.add(T["forecast_basis"][lang].format(
            lag=_month_label(d, pd.Timestamp(fc.lag_period.iloc[0]), lang),
            cov=d.num(float(fc.weather_coverage.iloc[0]) * 100, "{:.0f}%"), rows=""))
        if ent == "KE":
            self._tou(d, lang, int(pk.hour))
        return "answered"

    def _actual(self, d, ent, m, lang, q):
        a = self.tool_actual(ent, m)
        if a.empty:
            dec = self._missing_month_reason(m)
            why = (f"ISMO has not published usable hourly data for {m:%B %Y} (broken link, not published, or a copied "
                   f"month - see quality decision {dec})." if dec else
                   f"There is no published ISMO hourly data for {ent} in {m:%B %Y}.")
            if m >= pd.Timestamp(self.today.year, self.today.month, 1) - pd.DateOffset(months=1):
                why += " ISMO publishes each month about 15 days after it ends."
            return self._dont_know(d, lang, why)
        mean = a.demand_mw.mean()
        pk, mn = a.loc[a.demand_mw.idxmax()], a.loc[a.demand_mw.idxmin()]
        prev = self.tool_prev_month(ent, m)
        status = "answered"
        if len(prev):
            chg = mean / prev.mean_mw.iloc[0] - 1
            claimed_fall, claimed_rise = bool(FALL.search(q)), bool(RISE.search(q))
            contradicts = (claimed_fall and chg > 0.01) or (claimed_rise and chg < -0.01)
            if contradicts:
                status = "corrected_premise"
                d.add(T["premise_false"][lang].format(
                    name=_name(ent, lang), claimed="fall" if claimed_fall else "rise",
                    claimed_ur="کم" if claimed_fall else "زیادہ", month=_month_label(d, m, lang),
                    actual_dir="rose" if chg > 0 else "fell", actual_dir_ur="بڑھی" if chg > 0 else "کم ہوئی",
                    chg=d.num(abs(chg) * 100, "{:.1f}%"), prev=_month_label(d, pd.Timestamp(prev.period.iloc[0]), lang),
                    rows=d.rows(list(a.row_id[:1]) + [prev.first_row.iloc[0]])))
        d.add(T["actual"][lang].format(
            name=_name(ent, lang), month=_month_label(d, m, lang), mean=d.num(mean), peak=d.num(pk.demand_mw),
            ph=d.num(int(pk.hour), "{:02d}:00"), mn=d.num(mn.demand_mw), mh=d.num(int(mn.hour), "{:02d}:00"),
            rows=d.rows([pk.row_id, mn.row_id] + [r for r in a.row_id if r not in (pk.row_id, mn.row_id)])))
        if len(prev) and status == "answered":
            chg = mean / prev.mean_mw.iloc[0] - 1
            d.add(T["change"][lang].format(prev=_month_label(d, pd.Timestamp(prev.period.iloc[0]), lang),
                                           pmean=d.num(prev.mean_mw.iloc[0]), chg=d.num(chg * 100, "{:+.1f}%"),
                                           rows=d.rows([prev.first_row.iloc[0]])))
        return status

    def _peak_cost(self, d, ent, m, lang):
        pc = self.tool_peak_cost(ent, m)
        if pc.empty:
            return self._dont_know(d, lang, f"No hourly price and demand data overlap for {ent} up to that month "
                                            "(ISMO hourly prices start in July 2024).")
        r = pc.iloc[0]
        d.add(T["peak_cost"][lang].format(
            name=_name(ent, lang), month=_month_label(d, pd.Timestamp(r.period), lang), cost=d.num(r.daily_cost_rs_m),
            eshare=d.num(r.evening_peak_energy_share_pct, "{:.0f}%"), cshare=d.num(r.evening_peak_cost_share_pct, "{:.0f}%"),
            dear=_hours(d, r.dearest_hours), dp=d.num(r.dearest_price_rs_kwh, "{:.1f}"), cheap=_hours(d, r.cheapest_hours),
            cp=d.num(r.cheapest_price_rs_kwh, "{:.1f}"), sp=d.num(r.shift_pct, "{:.0f}%"),
            sm=d.num(r.shift_saving_rs_m_per_month, "{:,.0f}"), rows=d.rows([r.row_id])))
        if m is not None and pd.Timestamp(r.period) != m:
            d.add(("(Latest month with both ISMO prices and demand: " if lang == "en" else
                   "(قیمت اور طلب دونوں کے ساتھ تازہ ترین مہینہ: ") + _month_label(d, pd.Timestamp(r.period), lang) + ")")
        d.add("Marginal price is ISMO's system cost of the last unit in each hour - an indicator, not K-Electric's tariff."
              if lang == "en" else "مارجنل قیمت ہر گھنٹے میں سسٹم کی آخری یونٹ کی لاگت ہے - یہ اشارہ ہے، کے-الیکٹرک کا ٹیرف نہیں۔")
        if ent == "KE":
            self._tou(d, lang)
        return "answered"

    def _accuracy(self, d, ent, lang):
        ent = ent or "KE"
        g, mm = self.tool_accuracy(ent)
        if g.empty or mm.empty:
            return self._dont_know(d, lang, "The model has not been evaluated yet (run `make model`).")
        r, m = g.iloc[0], mm.iloc[0]
        months = json.loads(m.test_months)
        d.add(T["accuracy"][lang].format(
            months=d.ref(", ".join(months)), name=_name(ent, lang), m=d.num(r.model_mape, "{:.1f}%"),
            b=d.num(r.baseline_mape, "{:.1f}%"), cov=d.num(r.coverage_80, "{:.0f}%"), p80=d.num(80, "{}%"),
            mall=d.num(m.model_mape, "{:.1f}%"), ball=d.num(m.baseline_mape, "{:.1f}%"),
            rows=d.rows([r.row_id, "MM-LATEST"])))
        if r.improvement_pct < 1:
            d.add(T["accuracy_weak"][lang].format(name=_name(ent, lang)))
        hits = self.ret.search("baseline seasonal naive same month last year declared", k=1, doc_ids=["DOC-BC-BASELINE"])
        if len(hits):
            d.add(("Baseline definition: " if lang == "en" else "بیس لائن کی تعریف: ") + d.ref(f"[{d.cite(hits.iloc[0])}]"))
        return "answered"

    def _quality(self, d, ent, m, lang):
        q, st = self.tool_quality(ent, m)
        s = st.iloc[0]
        items = "; ".join(d.ref(f"{r.decision_id} {r.action} {r.check_id}: {r.reason[:160]}") for r in q.head(3).itertuples())
        scope = (_name(ent, lang) if ent else ("all entities" if lang == "en" else "تمام ادارے")) + \
                ((", " + _month_label(d, m, lang)) if m is not None else "")
        d.add(T["quality"][lang].format(scope=scope, nfix=d.num(s.n_fix), nfill=d.num(s.n_fill), nflag=d.num(s.n_flag),
                                        status=s.overall, items=items or "-"))
        d.row_ids += list(q.head(3).decision_id)
        return "answered"

    def _drift(self, d, ent, lang):
        ent = ent or "KE"
        dr = self.tool_drift(ent)
        if dr.empty:
            return self._dont_know(d, lang, "The drift monitor has not run yet.")
        items = "; ".join(f"{r.metric} = " + d.num(r.value, "{:.2f}") + f" ({r.status}) " + d.ref(f"[{r.row_id}]")
                          for r in dr.itertuples())
        d.row_ids += list(dr.row_id)
        d.add(T["drift"][lang].format(name=_name(ent, lang), items=items))
        return "answered"

    def _docs(self, d, q, lang):
        hits = self.ret.search(q, k=4, kinds=("official",))
        good = hits[(hits.dense >= 0.45) | ((hits.dense >= 0.35) & (hits.bm25 >= 0.5))]
        if good.empty:
            best = f"{hits.dense.max():.2f}" if len(hits) else "n/a"
            return self._dont_know(d, lang, "None of the trusted documents (NEPRA State of Industry 2024, ISMO IGCEP "
                                            "2025-35, K-Electric tariff page) or BijliCast's gold tables cover this "
                                            f"question (best match similarity {best} is below the threshold). Please ask "
                                            "NEPRA, ISMO or K-Electric directly.")
        quotes = []
        top = good.iloc[0]["score"]
        for i, (_, h) in enumerate(good.head(2).iterrows()):
            sent = re.sub(r"\s+", " ", _best_sentences(h["text"], q)).strip()
            prose = sum(ch.isdigit() for ch in sent) / max(len(sent), 1) < 0.08 and "TABLE" not in sent.upper()[:200]
            if i > 0 and (h["score"] < 0.9 * top or not prose):
                break   # second passage only if nearly as relevant and readable prose
            quotes.append(d.ref(f'"{sent}" [{d.cite(h)}]'))
        d.add(T["docs"][lang].format(quotes=" ".join(quotes)))
        return "answered"

    def _dont_know(self, d, lang, why):
        d.add(T["dont_know"][lang].format(why=d.ref(why)))
        return "dont_know"

    # ------------------------------------------------------------------ entry point
    def ask(self, question: str, lang: str | None = None) -> Answer:
        q = question.strip()
        lang = lang or _lang(q)
        d = Draft()
        ql = q.lower()
        ent, month = _entity(q), _month(q, self.today)
        intent = _intent(q, month, self.today)
        if any(u in ql or u in q for u in UNCOVERED):
            status = self._dont_know(d, lang, "BijliCast covers K-Electric and the nine DISCOs that ISMO reports "
                                              "(LESCO, FESCO, GEPCO, IESCO, MEPCO, PESCO, QESCO, HESCO, SEPCO); there is no "
                                              "data for the place you asked about.")
            intent = "out_of_scope"
        elif intent == "forecast":
            status = self._forecast(d, ent or "KE", month or pd.Timestamp(self.today.year, self.today.month, 1), lang) \
                if (ent or month) else self._docs(d, q, lang)
        elif intent == "actual":
            status = self._actual(d, ent or "KE", month, lang, q) if month is not None else \
                self._dont_know(d, lang, "Please name a month (for example 'September 2026') so I can read the ISMO profile.")
        elif intent == "peak_cost":
            status = self._peak_cost(d, ent or "KE", month, lang)
        elif intent == "accuracy":
            status = self._accuracy(d, ent, lang)
        elif intent == "quality":
            status = self._quality(d, ent, month, lang)
        elif intent == "drift":
            status = self._drift(d, ent, lang)
        else:
            status = self._docs(d, q, lang)
        if status != "dont_know":
            d.add(T["footer"][lang])
        draft = d.text()
        polished, used = wording.polish(draft, lang)
        ans = Answer(question=q, lang=lang, intent=intent, status=status, text=d.render(polished),
                     row_ids=list(dict.fromkeys(d.row_ids)), citations=d.citations, entity=ent,
                     month=month.strftime("%Y-%m") if month is not None else None, llm_used=used,
                     ask_id=uuid.uuid4().hex[:12], asked_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return ans


def _best_sentences(text: str, q: str, max_chars: int = 320) -> str:
    from .index import tokenize
    qt = set(tokenize(q))
    sents = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    scored = sorted(sents, key=lambda s: -len(qt & set(tokenize(s))))
    out = ""
    for s in scored:
        if len(out) + len(s) > max_chars:
            break
        out += (" " if out else "") + s
    return out or text[:max_chars]


def log_answers(answers: list[Answer]) -> None:
    """Append answers to gold.insight_log (needs a writable connection)."""
    con = connect()
    df = pd.DataFrame([{**asdict(a), "row_ids": json.dumps(a.row_ids), "citations": json.dumps(a.citations)}
                       for a in answers])
    con.register("_a", df)
    con.execute("CREATE SCHEMA IF NOT EXISTS gold")
    con.execute("CREATE TABLE IF NOT EXISTS gold.insight_log AS SELECT * FROM _a WHERE 1=0")
    con.execute("INSERT INTO gold.insight_log SELECT * FROM _a")
    con.close()


if __name__ == "__main__":
    import sys

    agent = InsightAgent()
    a = agent.ask(" ".join(sys.argv[1:]) or "What is K-Electric's expected demand next month?")
    agent.con.close()
    print(a.text)
    print("\nstatus:", a.status, "| intent:", a.intent, "| rows:", len(a.row_ids), "| citations:",
          [c["doc_id"] + (f" p.{c['page']}" if c["page"] else "") for c in a.citations])
