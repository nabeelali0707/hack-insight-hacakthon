// English / Urdu interface text. Numbers stay in Western digits in both languages.
export const STR = {
  en: {
    skip: "Skip to content",
    rail_home: "Home", rail_analysis: "Analysis", rail_scenarios: "Scenarios", rail_data: "Data", rail_reports: "Reports",
    rail_settings: "Settings", scenarios_soon: "Scenarios: not available yet",
    tab_workspace: "Workspace", tab_forecasts: "Forecasts", tab_cost: "Cost lens", tab_quality: "Data quality",
    title: "Plan the month ahead", grid_draw: "National-grid draw", supply: "Grid supply",
    entity: "Entity", month: "Month", live: "Live data", snapshot: "snapshot", pkt: "PKT",
    chart_title: "Monthly hourly demand profile", chart_sub: "Typical hour of the month · MW · PKT",
    lg_forecast: "Forecast (mean)", lg_band: "80% prediction interval", lg_base: "Same month last year", lg_eve: "Evening window",
    lg_base_none: "Same month last year · not published",
    tip_forecast: "Forecast", tip_range: "80% range", tip_base: "Last year",
    table_alt: "Show the chart as a table", hour: "Hour", lo: "Lower (80%)", hi: "Upper (80%)",
    chart_note: "Average demand at each hour across the month - not tomorrow's forecast or a live reading.",
    outlook: "outlook", mean: "Monthly mean demand", peak: "Peak average hour", at: "at",
    eve_label: "Evening window · defined analysis period",
    peak_outside: "This month's forecast peak is at {h} PKT, outside the evening window.",
    peak_inside: "This month's forecast peak is at {h} PKT, inside the evening window.",
    basis: "Uses ISMO data published to {lag}; {cov} of the month's weather is observed or forecast.",
    explore: "Explore an hour", explore_sub: "Select a time to see key indicators",
    cost_title: "Peak Cost Lens", cost_sub: "Historical marginal-price exposure",
    cost_qty: "Average marginal price by hour · PKR/MWh",
    cost_foot: "Evening hours carried {share} of {ent}'s grid cost at marginal price.",
    perf_title: "Model performance", backtest: "Backtest",
    ke_mape: "KE MAPE", overall_mape: "Overall MAPE", base_mape: "Baseline MAPE",
    ke_mape_s: "K-Electric only", overall_s: "All 10 entities", base_s: "Same month last year",
    mape_help: "MAPE is the average size of the forecast miss as a percentage of actual demand - lower is better. KE MAPE covers K-Electric only; overall and baseline MAPE cover all 10 entities x 24 hours, so they are not directly comparable with KE MAPE.",
    conf_title: "Data confidence", review: "Review flagged data", view_details: "View details",
    fresh: "Source freshness", qual: "Quality review", drift: "Model drift",
    fresh_d: "ISMO {p} · {d} days since month end · weather {h} h old",
    qual_d: "{f} fixes · {fl} fills · {g} flags",
    last_ok: "Pipeline last succeeded {t} PKT", last_failed: "Latest pipeline run failed at {t} PKT - showing the last good data.",
    ask: "Ask BijliCast", ask_sub: "Get insights from your planning data", ask_ph: "Compare next month with last year…",
    sources: "Sources", send: "Send question",
    footer: "Monthly profiles, not individual-day forecasts · Planning information only",
    loading: "Loading…", err_load: "Could not load data: {e}", retry: "Try again",
    no_fc: "No forecast for this selection", quarantine: "The latest build failed the quality gate. You are seeing the last good data ({p}).",
    stale: "ISMO data is older than usual: the latest month ({p}) ended {d} days ago.",
    drawer_title: "Ask BijliCast", close: "Close", thinking: "Checking the gold tables and documents…",
    st_answered: "Answered", st_dont_know: "I don't know", st_corrected_premise: "Premise corrected",
    ev_sources: "Document sources", ev_rows: "Data rows used", ev_none: "No document cited.",
    ask_err: "The assistant could not answer: {e}",
    ctx: "Context",
    // other pages
    fc_title: "Forecasts by entity", fc_sub: "Mean and peak hourly demand for the selected month · MW",
    open_ws: "Open in workspace", peak_at: "peak", cov: "weather observed/forecast",
    history: "How this outlook changed", history_sub: "Each hourly run re-forecasts with fresher weather",
    run_at: "Generated (PKT)",
    cost_page: "Cost lens", cost_page_sub: "Historical ISMO marginal prices joined to {ent}'s hourly grid draw",
    period: "Historical month", price_chart: "Average marginal price by hour", cost_chart: "Cost of {ent}'s grid draw by hour at marginal price",
    pkr_m_h: "PKR million per hour", daily_cost: "Daily cost at marginal price", eve_cost: "Evening share of cost",
    eve_energy: "Evening share of energy", dear: "Dearest hours", cheap: "Cheapest hours", shift: "5% peak shift (estimate)",
    shift_note: "Estimate only - moving 5% of demand out of the 3 dearest hours, valued at that month's prices. Not a guaranteed saving.",
    monthly_cost: "Monthly cost summary", exposure: "Forecast-error exposure on test months",
    exposure_note: "Forecast miss (MWh) valued at the marginal price: money at risk from planning to the wrong number - not a saving that is banked automatically.",
    model_risk: "Model (PKR m/day)", base_risk: "Baseline (PKR m/day)", reduction: "Reduction (PKR m/day)",
    dq_title: "Data quality", dq_sub: "What the Data Quality Agent decided in the latest build",
    overall: "Overall", fixes: "Fixes", fills: "Fills", flags: "Flags", critical: "Critical", pending: "Pending review",
    src_fresh: "Source freshness", runs: "Pipeline runs", review_q: "Needs human review", decisions: "Decision log",
    all: "All", started: "Started (PKT)", duration: "Duration", status: "Status", quality: "Quality",
    check: "Check", action: "Action", rows: "Rows", reason: "Reason", drift_t: "Drift monitor", metric: "Metric", value: "Value",
    files: "Files", last_fetch: "Last fetched (PKT)",
    an_title: "Model analysis", an_sub: "Test months evaluated once against the declared baseline",
    by: "Errors by", model: "Model", baseline: "Baseline", change: "Change", coverage: "80% coverage", bias: "Bias",
    by_month: "{ent} error by test month",
    data_title: "Data sources", data_sub: "Every raw file, its publisher, fetch time and SHA-256 fingerprint",
    file: "File", source: "Source", fetched: "Fetched (UTC)", licence: "Licence",
    rep_title: "Reports", rep_sub: "Submission documents generated from the gold tables",
    set_title: "Settings", set_lang: "Interface language", set_about: "About this data",
    set_about_t: "The dashboard reads a read-only snapshot refreshed after every hourly pipeline run. Times are Pakistan Standard Time (PKT, UTC+5).",
    published: "Published data",
    static_mode: "This public page shows answers prepared by the BijliCast Insight Agent after the latest pipeline run. Live free-text questions run on the BijliCast server (see the GitHub repository).",
    static_none: "I don't know. This public page only has prepared answers, and none matches this question closely enough. Pick one of the suggested questions above, or run BijliCast locally to ask anything.",
    static_404: "No exported data exists for this selection yet.",
    prepared_note: "Prepared answer to “{q}” · generated {t} PKT",
    try_these: "Prepared questions",
  },
  ur: {
    skip: "مواد پر جائیں",
    rail_home: "ہوم", rail_analysis: "تجزیہ", rail_scenarios: "منظرنامے", rail_data: "ڈیٹا", rail_reports: "رپورٹس",
    rail_settings: "ترتیبات", scenarios_soon: "منظرنامے: ابھی دستیاب نہیں",
    tab_workspace: "ورک اسپیس", tab_forecasts: "پیشگوئیاں", tab_cost: "لاگت کا جائزہ", tab_quality: "ڈیٹا کا معیار",
    title: "اگلے مہینے کی منصوبہ بندی", grid_draw: "قومی گرڈ سے لی گئی بجلی", supply: "گرڈ سپلائی",
    entity: "ادارہ", month: "مہینہ", live: "تازہ ڈیٹا", snapshot: "اسنیپ شاٹ", pkt: "PKT",
    chart_title: "ماہانہ گھنٹہ وار طلب", chart_sub: "مہینے کا عام گھنٹہ · میگاواٹ · پاکستانی وقت",
    lg_forecast: "پیشگوئی (اوسط)", lg_band: "80% پیشگوئی کی حد", lg_base: "پچھلے سال کا یہی مہینہ", lg_eve: "شام کے اوقات",
    lg_base_none: "پچھلے سال کا یہی مہینہ · شائع نہیں ہوا",
    tip_forecast: "پیشگوئی", tip_range: "80% حد", tip_base: "پچھلا سال",
    table_alt: "چارٹ کو جدول کی صورت میں دیکھیں", hour: "گھنٹہ", lo: "کم از کم (80%)", hi: "زیادہ سے زیادہ (80%)",
    chart_note: "پورے مہینے میں ہر گھنٹے کی اوسط طلب - یہ کل کی پیشگوئی یا براہِ راست ریڈنگ نہیں۔",
    outlook: "کا جائزہ", mean: "ماہانہ اوسط طلب", peak: "سب سے زیادہ طلب والا گھنٹہ", at: "بوقت",
    eve_label: "شام کے اوقات · مقررہ تجزیاتی مدت",
    peak_outside: "اس مہینے کا متوقع پیک {h} بجے ہے، شام کے اوقات سے باہر۔",
    peak_inside: "اس مہینے کا متوقع پیک {h} بجے ہے، شام کے اوقات کے اندر۔",
    basis: "{lag} تک شائع شدہ آئی ایس ایم او ڈیٹا؛ مہینے کے موسم کا {cov} حصہ مشاہدہ یا پیشگوئی ہے۔",
    explore: "کسی گھنٹے کا جائزہ لیں", explore_sub: "اہم اعداد دیکھنے کے لیے وقت منتخب کریں",
    cost_title: "پیک لاگت کا جائزہ", cost_sub: "ماضی کی مارجنل قیمت",
    cost_qty: "گھنٹہ وار اوسط مارجنل قیمت · روپے فی میگاواٹ آور",
    cost_foot: "شام کے اوقات میں {ent} کی گرڈ لاگت کا {share} حصہ تھا۔",
    perf_title: "ماڈل کی کارکردگی", backtest: "بیک ٹیسٹ",
    ke_mape: "کے ای غلطی", overall_mape: "مجموعی غلطی", base_mape: "بیس لائن غلطی",
    ke_mape_s: "صرف کے-الیکٹرک", overall_s: "تمام دس ادارے", base_s: "پچھلے سال کا یہی مہینہ",
    mape_help: "MAPE پیشگوئی کی اوسط غلطی ہے، اصل طلب کے فیصد میں - کم بہتر ہے۔ کے ای غلطی صرف کے-الیکٹرک کی ہے؛ مجموعی اور بیس لائن غلطی تمام دس اداروں کی ہے، اس لیے ان کا براہِ راست موازنہ نہیں۔",
    conf_title: "ڈیٹا پر اعتماد", review: "نشان زد ڈیٹا دیکھیں", view_details: "تفصیل دیکھیں",
    fresh: "ذرائع کی تازگی", qual: "معیار کی جانچ", drift: "ماڈل ڈرفٹ",
    fresh_d: "آئی ایس ایم او {p} · مہینہ ختم ہوئے {d} دن · موسم {h} گھنٹے پرانا",
    qual_d: "{f} درستیاں · {fl} خانہ پُری · {g} نشاندہیاں",
    last_ok: "پائپ لائن آخری بار کامیاب: {t} PKT", last_failed: "تازہ ترین رن {t} PKT پر ناکام رہا - آخری درست ڈیٹا دکھایا جا رہا ہے۔",
    ask: "بجلی کاسٹ سے پوچھیں", ask_sub: "اپنے منصوبہ بندی ڈیٹا سے معلومات حاصل کریں", ask_ph: "اگلے مہینے کا پچھلے سال سے موازنہ کریں…",
    sources: "ذرائع", send: "سوال بھیجیں",
    footer: "ماہانہ پروفائل، روزانہ پیشگوئی نہیں · صرف منصوبہ بندی کی معلومات",
    loading: "لوڈ ہو رہا ہے…", err_load: "ڈیٹا لوڈ نہیں ہو سکا: {e}", retry: "دوبارہ کوشش کریں",
    no_fc: "اس انتخاب کے لیے کوئی پیشگوئی نہیں", quarantine: "تازہ ترین بلڈ معیار کی جانچ میں ناکام رہی۔ آخری درست ڈیٹا ({p}) دکھایا جا رہا ہے۔",
    stale: "آئی ایس ایم او ڈیٹا معمول سے پرانا ہے: تازہ ترین مہینہ ({p}) {d} دن پہلے ختم ہوا۔",
    drawer_title: "بجلی کاسٹ سے پوچھیں", close: "بند کریں", thinking: "گولڈ ٹیبلز اور دستاویزات دیکھی جا رہی ہیں…",
    st_answered: "جواب دیا", st_dont_know: "معلوم نہیں", st_corrected_premise: "مفروضہ درست کیا",
    ev_sources: "دستاویزی ذرائع", ev_rows: "استعمال شدہ ڈیٹا قطاریں", ev_none: "کوئی دستاویز حوالہ نہیں۔",
    ask_err: "جواب نہیں دیا جا سکا: {e}",
    ctx: "سیاق",
    fc_title: "اداروں کی پیشگوئیاں", fc_sub: "منتخب مہینے کی اوسط اور زیادہ سے زیادہ گھنٹہ وار طلب · میگاواٹ",
    open_ws: "ورک اسپیس میں کھولیں", peak_at: "پیک", cov: "موسم مشاہدہ/پیشگوئی",
    history: "یہ اندازہ کیسے بدلا", history_sub: "ہر گھنٹے نئے موسم کے ساتھ دوبارہ پیشگوئی",
    run_at: "وقت (PKT)",
    cost_page: "لاگت کا جائزہ", cost_page_sub: "آئی ایس ایم او کی ماضی کی مارجنل قیمتیں اور {ent} کی گھنٹہ وار گرڈ طلب",
    period: "ماضی کا مہینہ", price_chart: "گھنٹہ وار اوسط مارجنل قیمت", cost_chart: "{ent} کی گرڈ بجلی کی گھنٹہ وار لاگت",
    pkr_m_h: "ملین روپے فی گھنٹہ", daily_cost: "روزانہ لاگت", eve_cost: "لاگت میں شام کا حصہ",
    eve_energy: "توانائی میں شام کا حصہ", dear: "مہنگے ترین گھنٹے", cheap: "سستے ترین گھنٹے", shift: "5% پیک منتقلی (تخمینہ)",
    shift_note: "صرف تخمینہ - تین مہنگے ترین گھنٹوں سے 5% طلب منتقل کرنے کی قیمت، اسی مہینے کی قیمتوں پر۔ یقینی بچت نہیں۔",
    monthly_cost: "ماہانہ لاگت کا خلاصہ", exposure: "ٹیسٹ مہینوں میں پیشگوئی کی غلطی کا خطرہ",
    exposure_note: "پیشگوئی کی غلطی (میگاواٹ آور) مارجنل قیمت پر: غلط منصوبہ بندی سے خطرے میں رقم - خودکار بچت نہیں۔",
    model_risk: "ماڈل (ملین روپے/دن)", base_risk: "بیس لائن (ملین روپے/دن)", reduction: "کمی (ملین روپے/دن)",
    dq_title: "ڈیٹا کا معیار", dq_sub: "تازہ ترین بلڈ میں ڈیٹا کوالٹی ایجنٹ کے فیصلے",
    overall: "مجموعی", fixes: "درستیاں", fills: "خانہ پُری", flags: "نشاندہیاں", critical: "سنگین", pending: "جائزہ باقی",
    src_fresh: "ذرائع کی تازگی", runs: "پائپ لائن رن", review_q: "انسانی جائزہ درکار", decisions: "فیصلوں کا ریکارڈ",
    all: "سب", started: "آغاز (PKT)", duration: "دورانیہ", status: "حالت", quality: "معیار",
    check: "جانچ", action: "عمل", rows: "قطاریں", reason: "وجہ", drift_t: "ڈرفٹ مانیٹر", metric: "پیمانہ", value: "قدر",
    files: "فائلیں", last_fetch: "آخری بار حاصل (PKT)",
    an_title: "ماڈل کا تجزیہ", an_sub: "ٹیسٹ مہینے، اعلان شدہ بیس لائن کے مقابلے میں",
    by: "غلطی بلحاظ", model: "ماڈل", baseline: "بیس لائن", change: "تبدیلی", coverage: "80% کوریج", bias: "جھکاؤ",
    by_month: "{ent} کی ٹیسٹ مہینوں میں غلطی",
    data_title: "ڈیٹا کے ذرائع", data_sub: "ہر خام فائل، اس کا ناشر، حاصل کرنے کا وقت اور SHA-256",
    file: "فائل", source: "ذریعہ", fetched: "حاصل (UTC)", licence: "لائسنس",
    rep_title: "رپورٹس", rep_sub: "گولڈ ٹیبلز سے تیار شدہ دستاویزات",
    set_title: "ترتیبات", set_lang: "زبان", set_about: "اس ڈیٹا کے بارے میں",
    set_about_t: "ڈیش بورڈ ایک ریڈ اونلی اسنیپ شاٹ پڑھتا ہے جو ہر گھنٹے کی پائپ لائن کے بعد تازہ ہوتا ہے۔ اوقات پاکستانی وقت (UTC+5) میں ہیں۔",
    published: "شائع شدہ ڈیٹا",
    static_mode: "یہ عوامی صفحہ تازہ ترین پائپ لائن رن کے بعد بجلی کاسٹ انسائٹ ایجنٹ کے تیار کردہ جوابات دکھاتا ہے۔ کوئی بھی سوال پوچھنے کے لیے بجلی کاسٹ سرور درکار ہے (گٹ ہب ریپوزٹری دیکھیں)۔",
    static_none: "مجھے معلوم نہیں۔ اس عوامی صفحے پر صرف تیار شدہ جوابات ہیں اور کوئی بھی اس سوال سے کافی مطابقت نہیں رکھتا۔ اوپر دیے گئے سوالات میں سے کوئی منتخب کریں۔",
    static_404: "اس انتخاب کے لیے ابھی کوئی ڈیٹا موجود نہیں۔",
    prepared_note: "“{q}” کا تیار شدہ جواب · {t} PKT",
    try_these: "تیار شدہ سوالات",
  },
};

const MONTHS = {
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
  ur: ["جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون", "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"],
};
const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function makeT(lang) {
  const d = STR[lang] || STR.en;
  return (key, vars = {}) => {
    let s = d[key] ?? STR.en[key] ?? key;
    for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
    return s;
  };
}

export function monthName(ym, lang, short = false) {
  if (!ym) return "-";
  const [y, m] = ym.split("-").map(Number);
  if (short && lang !== "ur") return `${MONTHS_SHORT[m - 1]} ${y}`;
  return `${MONTHS[lang === "ur" ? "ur" : "en"][m - 1]} ${y}`;
}

const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fmt = {
  n0: (v) => (v == null || Number.isNaN(v) ? "-" : nf0.format(v)),
  n1: (v) => (v == null || Number.isNaN(v) ? "-" : nf1.format(v)),
  n2: (v) => (v == null || Number.isNaN(v) ? "-" : nf2.format(v)),
  pct: (v, d = 1) => (v == null ? "-" : `${v.toFixed(d)}%`),
  hh: (h) => `${String(h).padStart(2, "0")}:00`,
  h2: (h) => String(h).padStart(2, "0"),
};

// UTC ISO -> "21 Oct, 00:34" in PKT (UTC+5, no DST)
export function pkt(iso, withDate = true) {
  if (!iso) return "-";
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (Number.isNaN(t.getTime())) return iso;
  const p = new Date(t.getTime() + 5 * 3600 * 1000);
  const hh = String(p.getUTCHours()).padStart(2, "0"), mm = String(p.getUTCMinutes()).padStart(2, "0");
  // wrapped in Unicode directional isolates so the date stays readable inside Urdu (RTL) text
  return "⁦" + (withDate ? `${p.getUTCDate()} ${MONTHS_SHORT[p.getUTCMonth()]}, ${hh}:${mm}` : `${hh}:${mm}`) + "⁩";
}
