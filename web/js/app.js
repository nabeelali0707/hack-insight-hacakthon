import { icons } from "./icons.js";
import { makeT, monthName, fmt, pkt } from "./i18n.js";
import { demandChart, barChart, sparkline } from "./charts.js";

// ------------------------------------------------------------------ state
const store = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
const state = {
  lang: store.get("bc.lang", "en"),
  entity: store.get("bc.entity", "KE"),
  month: null,
  hour: null,
  meta: null,
  vis: { forecast: true, band: true, baseline: true, evening: true },
  thread: [],
  dqFilter: "",
  costPeriod: null,
  ws: null,
};
let t = makeT(state.lang);
const view = document.getElementById("view");
const EVENING = [18, 22];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Static mode (free Hugging Face static Space): the same views read JSON files exported by
// `python -m bijlicast.static_export` instead of the live API.
const STATIC = !!window.BIJLICAST_STATIC;
function staticPath(path) {
  const u = new URL(path, location.href), p = u.pathname.split("/api/")[1], q = u.searchParams;
  const files = {
    meta: () => "data/meta.json",
    workspace: () => `data/workspace/${q.get("entity")}_${q.get("month")}.json`,
    forecasts: () => `data/forecasts/${q.get("month")}.json`,
    forecast_history: () => `data/history/${q.get("entity")}_${q.get("month")}.json`,
    cost: () => `data/cost/${q.get("entity")}_${q.get("period") || "latest"}.json`,
    performance: () => `data/performance/${q.get("entity") || "KE"}.json`,
    confidence: () => `data/confidence/${q.get("entity") || "KE"}.json`,
    quality: () => "data/quality.json",
    runs: () => "data/runs.json",
    sources: () => "data/sources.json",
    briefs: () => `data/briefs_${q.get("lang") || "en"}.json`,
    scenario: () => `data/scenario/${q.get("entity")}_${q.get("month")}_${q.get("delta")}.json`,
  };
  return files[p] ? files[p]() : null;
}
let prepared = null;
const toks = (s) => new Set((s.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter((w) => w.length > 1));
async function staticAsk({ question, lang }) {
  prepared = prepared || (await (await fetch("data/prepared_answers.json", { cache: "no-cache" })).json());
  const qt = toks(question);
  let best = null, score = 0;
  for (const a of prepared.answers) {
    const at = toks(a.question);
    let s = [...qt].filter((w) => at.has(w)).length / Math.max(qt.size, 1);
    if (a.lang === lang) s += 0.05;
    if (s > score) { score = s; best = a; }
  }
  if (!best || score < 0.4) {
    return { question, lang, status: "dont_know", prepared: true, row_ids: [], citations: [], asked_at_utc: prepared.generated_at_utc,
      text: t("static_none") };
  }
  return { ...best, prepared: true, matched_question: best.question };
}
// Source ages are recomputed in the browser, so a stale export shows as stale.
function freshen(conf) {
  const st = conf?.status;
  if (!st) return conf;
  const [y, m] = st.ismo_latest_period.split("-").map(Number);
  st.ismo_age_days = Math.floor((Date.now() - Date.UTC(y, m, 0)) / 86400000);
  st.ismo_stale = st.ismo_age_days > 50;
  if (st.live_snapshot_utc) {
    const ts = Date.parse(String(st.live_snapshot_utc).replace(" ", "T"));
    st.live_age_hours = +((Date.now() - ts) / 3600000).toFixed(1);
    st.live_stale = st.live_age_hours > 2;
  }
  conf.freshness_level = st.ismo_stale && st.live_stale ? "RED" : (st.ismo_stale || st.live_stale ? "AMBER" : "GREEN");
  return conf;
}

async function api(path, opts) {
  if (STATIC) {
    if (path.startsWith("/api/ask")) return staticAsk(JSON.parse(opts.body));
    const file = staticPath(path);
    const r = await fetch(file, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status === 404 ? t("static_404") : `HTTP ${r.status}`);
    const data = await r.json();
    const action = new URL(path, location.href).searchParams.get("action");
    if (path.startsWith("/api/quality") && action) data.decisions = data.decisions.filter((d) => d.action === action);
    if (path.startsWith("/api/confidence")) return freshen(data);
    return data;
  }
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg || `HTTP ${r.status}`);
  }
  const data = await r.json();
  return path.startsWith("/api/confidence") ? freshen(data) : data;
}
const entName = (code) => state.meta?.entities.find((e) => e.code === code)?.name || code;
const entShort = (code) => (code === "KE" ? "K-Electric" : code);

// ------------------------------------------------------------------ routing
const HOME_TABS = ["workspace", "forecasts", "cost", "quality"];
function route() { return (location.hash.replace(/^#\/?/, "").split("?")[0]) || "workspace"; }

function renderShell() {
  const r = route();
  const area = HOME_TABS.includes(r) ? "home" : r;
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ur" ? "rtl" : "ltr";
  const railItem = (key, href, icon, label) =>
    `<a href="${href}" ${area === key ? 'aria-current="page"' : ""}>${icons[icon]}<span>${label}</span></a>`;
  document.getElementById("rail").innerHTML =
    railItem("home", "#/workspace", "home", t("rail_home")) +
    railItem("analysis", "#/analysis", "analysis", t("rail_analysis")) +
    railItem("scenarios", "#/scenarios", "scenarios", t("rail_scenarios")) +
    railItem("data", "#/data", "data", t("rail_data")) +
    railItem("reports", "#/reports", "reports", t("rail_reports")) +
    `<div class="spacer"></div>` +
    railItem("settings", "#/settings", "settings", t("rail_settings"));
  const tabs = document.getElementById("tabs");
  if (area === "home") {
    const tab = (k, label) => `<a href="#/${k}" ${r === k ? 'aria-current="page"' : ""}>${label}</a>`;
    tabs.innerHTML = tab("workspace", t("tab_workspace")) + tab("forecasts", t("tab_forecasts")) + tab("cost", t("tab_cost")) + tab("quality", t("tab_quality"));
  } else {
    const names = { analysis: "rail_analysis", scenarios: "rail_scenarios", data: "rail_data", reports: "rail_reports", settings: "rail_settings" };
    tabs.innerHTML = `<span class="area-title" style="align-self:center">${t(names[area] || "rail_home")}</span>`;
  }
  document.querySelectorAll(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
  document.title = `BijliCast - ${t(HOME_TABS.includes(r) ? "tab_" + r : "rail_" + r)}`;
}

async function render() {
  renderShell();
  const r = route();
  const views = { workspace: viewWorkspace, forecasts: viewForecasts, cost: viewCost, quality: viewQuality,
    analysis: viewAnalysis, scenarios: viewScenarios, data: viewData, reports: viewReports, settings: viewSettings };
  try {
    if (!state.meta) state.meta = await api("/api/meta");
    if (!state.month || !state.meta.forecast_months.includes(state.month)) state.month = state.meta.default_month;
    if (!state.meta.entities.some((e) => e.code === state.entity)) state.entity = state.meta.default_entity;
    await (views[r] || viewWorkspace)();
  } catch (e) {
    view.innerHTML = errorBox(e);
    view.querySelector("[data-retry]")?.addEventListener("click", () => { state.meta = null; render(); });
  }
}
const errorBox = (e) => `<div class="card"><div class="empty"><b>${esc(t("err_load", { e: e.message }))}</b>
  <button class="btn" data-retry type="button">${t("retry")}</button></div></div>`;
const skel = (h) => `<div class="skel" style="height:${h}px"></div>`;

// ------------------------------------------------------------------ shared bits
function filtersHTML({ months = true } = {}) {
  const ents = state.meta.entities.map((e) => `<option value="${e.code}" ${e.code === state.entity ? "selected" : ""}>${esc(e.code === "KE" ? "K-Electric" : `${e.code} · ${e.city}`)}</option>`).join("");
  const mos = state.meta.forecast_months.map((m) => `<option value="${m}" ${m === state.month ? "selected" : ""}>${monthName(m, state.lang)}</option>`).join("");
  return `<div class="filters">
    <div class="field"><label for="f-entity">${t("entity")}</label><select id="f-entity" class="select">${ents}</select></div>
    ${months ? `<div class="field"><label for="f-month">${t("month")}</label><select id="f-month" class="select">${mos}</select></div>` : ""}
    <div class="data-note"><span class="dot ${state.meta.quality?.overall === "RED" ? "red" : ""}"></span>${STATIC ? t("published") : t("live")} · ${t("snapshot")} ${pkt(state.meta.snapshot_utc)} ${t("pkt")}</div>
  </div>`;
}
function bindFilters(onChange) {
  view.querySelector("#f-entity")?.addEventListener("change", (e) => { state.entity = e.target.value; store.set("bc.entity", state.entity); state.hour = null; onChange(); });
  view.querySelector("#f-month")?.addEventListener("change", (e) => { state.month = e.target.value; state.hour = null; onChange(); });
}
const pill = (level, text) => `<span class="pill ${esc(level)}">${esc(text ?? level)}</span>`;
const info = (text) => `<span class="info"><button type="button" aria-label="${esc(text)}">${icons.info}</button><span class="pop" role="tooltip">${esc(text)}</span></span>`;

function banners(conf) {
  const out = [];
  const st = conf?.status;
  if (st && st.published === false) out.push(`<div class="banner bad" role="status">${icons.warn}<span>${esc(t("quarantine", { p: monthName(st.ismo_latest_period, state.lang) }))}</span></div>`);
  if (st?.ismo_stale) out.push(`<div class="banner warn" role="status">${icons.warn}<span>${esc(t("stale", { p: monthName(st.ismo_latest_period, state.lang), d: st.ismo_age_days }))}</span></div>`);
  if (conf?.last_run && conf.last_run.status === "failed") out.push(`<div class="banner bad" role="status">${icons.warn}<span>${esc(t("last_failed", { t: pkt(conf.last_run.started_at_utc) }))}</span></div>`);
  return out.join("");
}

// ------------------------------------------------------------------ WORKSPACE
async function viewWorkspace() {
  const sub = state.entity === "KE" ? `K-Electric · ${t("grid_draw")}` : `${entName(state.entity)} · ${t("supply")}`;
  view.innerHTML = `
    <div class="page-head"><div><h1>${t("title")}</h1><div class="sub">${esc(sub)}</div></div>${filtersHTML()}</div>
    <div id="banners"></div>
    <div class="row-main">
      <section class="card" aria-labelledby="ch-title">
        <div class="card-head"><div><h2 id="ch-title">${t("chart_title")}</h2><div class="card-sub">${t("chart_sub")}</div></div><div class="legend" id="legend"></div></div>
        <div id="chart" class="chart" style="margin-top:10px">${skel(290)}</div>
        <div class="chart-note" id="chart-note"></div>
        <details class="table-alt" id="tbl"></details>
      </section>
      <aside class="card outlook" id="outlook" aria-live="polite">${skel(260)}</aside>
    </div>
    <section class="card explorer" aria-labelledby="ex-title">
      <div class="intro"><h3 id="ex-title">${t("explore")}</h3><div class="card-sub">${t("explore_sub")}</div></div>
      <div class="hours-wrap"><div class="hours" id="hours" role="radiogroup" aria-label="${t("explore")}"></div><div class="callout" id="callout" hidden></div></div>
    </section>
    <div class="row-three">
      <section class="card" id="c-cost" aria-labelledby="cc-t">${skel(220)}</section>
      <section class="card" id="c-perf" aria-labelledby="cp-t">${skel(220)}</section>
      <section class="card" id="c-conf" aria-labelledby="cf-t">${skel(220)}</section>
    </div>
    ${composerHTML()}
    <div class="foot">${t("footer")}</div>`;
  bindFilters(() => viewWorkspace());
  bindComposer();

  const [ws, perf, conf, cost] = await Promise.all([
    api(`/api/workspace?entity=${state.entity}&month=${state.month}`),
    api(`/api/performance?entity=${state.entity}`).catch((e) => ({ error: e })),
    api(`/api/confidence?entity=${state.entity}`).catch((e) => ({ error: e })),
    api(`/api/cost?entity=${state.entity}`).catch((e) => ({ error: e })),
  ]);
  state.ws = ws;
  view.querySelector("#banners").innerHTML = banners(conf);
  renderMain(ws);
  renderCostCard(cost);
  renderPerfCard(perf);
  renderConfCard(conf);
}

function renderMain(ws) {
  const chart = view.querySelector("#chart"), legend = view.querySelector("#legend");
  if (!ws.forecast.length) {
    chart.innerHTML = `<div class="empty"><b>${t("no_fc")}</b>${esc(ws.empty_reason || "")}</div>`;
    view.querySelector("#outlook").innerHTML = `<h2>${monthName(state.month, state.lang)}</h2><div class="l">${t("no_fc")}</div>`;
    view.querySelector("#hours").innerHTML = "";
    return;
  }
  const hasBase = ws.baseline.length === 24;
  if (!hasBase) state.vis.baseline = false;
  const lg = (k, sw, label, disabled = false) =>
    `<button type="button" data-k="${k}" aria-pressed="${state.vis[k]}" ${disabled ? "disabled" : ""}><span class="sw ${sw}"></span>${label}</button>`;
  legend.innerHTML = lg("forecast", "sw-line", t("lg_forecast")) + lg("band", "sw-band", t("lg_band")) +
    (hasBase ? lg("baseline", "sw-dash", `${t("lg_base")} (${monthName(ws.baseline_period, state.lang, true)})`) : lg("baseline", "sw-dash", t("lg_base_none"), true)) +
    lg("evening", "sw-eve", t("lg_eve"));
  legend.querySelectorAll("button:not([disabled])").forEach((b) => b.addEventListener("click", () => {
    state.vis[b.dataset.k] = !state.vis[b.dataset.k];
    b.setAttribute("aria-pressed", state.vis[b.dataset.k]);
    drawMainChart();
  }));
  view.querySelector("#chart-note").textContent = (hasBase ? "" : (ws.baseline_reason || "") + " ") + t("chart_note");

  const o = ws.outlook;
  if (state.hour == null) state.hour = o.peak_hour;
  const monthOnly = monthName(state.month, state.lang).split(" ")[0];
  view.querySelector("#outlook").innerHTML = `
    <h2>${state.lang === "ur" ? `${monthOnly} ${t("outlook")}` : `${monthOnly} ${t("outlook")}`}</h2>
    <div class="m"><div class="v">${fmt.n0(o.mean_mw)}<small>MW</small></div><div class="l">${t("mean")}</div></div>
    <div class="m"><div class="v">${fmt.n0(o.peak_mw)}<small>MW</small></div><div class="l">${t("peak")} · ${fmt.hh(o.peak_hour)} PKT</div></div>
    <div class="m"><div class="v">18-22<small>PKT</small></div><div class="l">${t("eve_label")}</div></div>
    <div class="o-foot">${esc(t(o.peak_in_evening ? "peak_inside" : "peak_outside", { h: fmt.hh(o.peak_hour) }))}<br>
      ${esc(t("basis", { lag: monthName(o.lag_period, state.lang), cov: fmt.pct(o.weather_coverage * 100, 0) }))}</div>`;

  const tbl = view.querySelector("#tbl");
  tbl.innerHTML = `<summary>${t("table_alt")}</summary><div class="tbl-wrap"><table class="data"><thead><tr><th>${t("hour")}</th>
    <th class="r">${t("lg_forecast")}</th><th class="r">${t("lo")}</th><th class="r">${t("hi")}</th><th class="r">${t("lg_base")}</th><th>Row ID</th></tr></thead><tbody>
    ${ws.forecast.map((d) => { const b = ws.baseline.find((r) => r.hour === d.hour);
      return `<tr><td>${fmt.hh(d.hour)}</td><td class="r">${fmt.n0(d.pred)}</td><td class="r">${fmt.n0(d.lo)}</td><td class="r">${fmt.n0(d.hi)}</td><td class="r">${b ? fmt.n0(b.value) : "-"}</td><td class="mono">${d.row_id}</td></tr>`; }).join("")}
    </tbody></table></div>`;

  view.querySelector("#hours").innerHTML = ws.forecast.map((d) =>
    `<button type="button" role="radio" data-h="${d.hour}" class="${d.hour >= EVENING[0] && d.hour <= EVENING[1] ? "eve" : ""}"
      aria-checked="${d.hour === state.hour}" tabindex="${d.hour === state.hour ? 0 : -1}" aria-label="${fmt.hh(d.hour)} PKT">${fmt.h2(d.hour)}</button>`).join("");
  const hours = view.querySelector("#hours");
  hours.addEventListener("click", (e) => { const b = e.target.closest("button[data-h]"); if (b) setHour(+b.dataset.h, true); });
  hours.addEventListener("keydown", (e) => {
    const k = { ArrowRight: 1, ArrowLeft: -1, Home: -99, End: 99 }[e.key];
    if (k == null) return;
    e.preventDefault();
    const dir = document.documentElement.dir === "rtl" && Math.abs(k) === 1 ? 1 : 1;
    setHour(Math.min(23, Math.max(0, state.hour + k * dir)), true);
  });
  drawMainChart();
  updateExplorer();
}

function drawMainChart() {
  const ws = state.ws;
  demandChart(view.querySelector("#chart"), {
    forecast: ws.forecast, baseline: ws.baseline, visible: state.vis, evening: EVENING, selected: state.hour, t,
    onSelect: (h) => setHour(h, false),
  });
}
function setHour(h, focusChip) {
  state.hour = h;
  drawMainChart();
  updateExplorer(focusChip);
}
function updateExplorer(focusChip = false) {
  const ws = state.ws, hours = view.querySelector("#hours"), call = view.querySelector("#callout");
  if (!ws?.forecast.length || !hours) return;
  hours.querySelectorAll("button").forEach((b) => {
    const on = +b.dataset.h === state.hour;
    b.setAttribute("aria-checked", on); b.tabIndex = on ? 0 : -1;
    if (on && focusChip) b.focus({ preventScroll: true });
  });
  const d = ws.forecast[state.hour], b = ws.baseline.find((r) => r.hour === state.hour);
  call.innerHTML = `<div>${fmt.hh(state.hour)} PKT · ${t("tip_forecast")} <b>${fmt.n0(d.pred)} MW</b></div>
    <div class="muted">${t("tip_range")} ${fmt.n0(d.lo)}-${fmt.n0(d.hi)} MW${b ? ` · ${t("tip_base")} ${fmt.n0(b.value)} MW` : ""}</div>`;
  const btn = hours.querySelector(`button[data-h="${state.hour}"]`);
  const wrap = view.querySelector(".hours-wrap");
  call.hidden = false;
  const center = btn.offsetLeft + btn.offsetWidth / 2;
  const half = call.offsetWidth / 2;
  const min = (wrap.scrollLeft || 0) + half + 2, max = (wrap.scrollLeft || 0) + wrap.clientWidth - half - 2;
  const placed = Math.min(Math.max(center, min), Math.max(min, max));
  call.style.left = `${placed}px`;
  call.style.setProperty("--shift", `${center - placed}px`);   // keep the arrow on the chosen hour
  if (focusChip) btn.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function renderCostCard(cost) {
  const box = view.querySelector("#c-cost");
  if (cost.error || !cost.hourly?.length) {
    box.innerHTML = `<h3 id="cc-t">${t("cost_title")}</h3><div class="card-sub">${t("cost_sub")}</div>
      <div class="empty">${esc(cost.error?.message || cost.empty_reason || "")}</div>`;
    return;
  }
  const s = cost.summary;
  box.innerHTML = `<h3 id="cc-t">${t("cost_title")}</h3><div class="card-sub">${t("cost_sub")}</div>
    <div class="period" style="margin-top:8px">${t("cost_qty")} · <b>${monthName(cost.period, state.lang)}</b> · ISMO</div>
    <div id="cost-bars" class="chart" style="margin-top:4px"></div>
    <div class="period">${s ? esc(t("cost_foot", { share: fmt.pct(s.evening_peak_cost_share_pct, 0), ent: entShort(state.entity) })) : ""}</div>
    <a class="link-more" href="#/cost">${t("view_details")} ${icons.arrow.replace("<svg", '<svg width="14" height="14"')}</a>`;
  barChart(box.querySelector("#cost-bars"), {
    values: cost.hourly.map((d) => ({ hour: d.hour, v: d.price_pkr_mwh, row_id: d.price_row_id })),
    highlight: EVENING, height: 150, fmtV: (v) => `${fmt.n0(v)} PKR/MWh`, axisFmt: (v) => fmt.n0(v),
  });
}

function renderPerfCard(perf) {
  const box = view.querySelector("#c-perf");
  const m = perf.metrics;
  if (perf.error || !m) { box.innerHTML = `<h3 id="cp-t">${t("perf_title")}</h3><div class="empty">${esc(perf.error?.message || "")}</div>`; return; }
  const months = m.test_months || [];
  const span = months.length ? `${monthName(months[0], state.lang, true)}-${monthName(months[months.length - 1], state.lang, true)}` : "";
  box.innerHTML = `<div class="card-head"><h3 id="cp-t">${t("perf_title")} ${info(t("mape_help"))}</h3>
      <span class="period">${t("backtest")} · ${esc(span)} (${months.length})</span></div>
    <div class="trio">
      <div><div class="k">${t("ke_mape")}</div><div class="stat blue">${fmt.pct(m.ke_model_mape, 2)}</div><div class="s">${t("ke_mape_s")}</div></div>
      <div><div class="k">${t("overall_mape")}</div><div class="stat">${fmt.pct(m.model_mape, 2)}</div><div class="s">${t("overall_s")}</div></div>
      <div><div class="k">${t("base_mape")}</div><div class="stat">${fmt.pct(m.baseline_mape, 2)}</div><div class="s">${t("base_s")}</div></div>
    </div>
    <div class="period" style="margin-top:14px">${state.lang === "ur" ? "" : `KE baseline ${fmt.pct(m.ke_baseline_mape, 2)} · lower is better`}</div>
    <a class="link-more" href="#/analysis">${t("view_details")} ${icons.arrow.replace("<svg", '<svg width="14" height="14"')}</a>`;
}

function renderConfCard(conf) {
  const box = view.querySelector("#c-conf");
  if (conf.error || !conf.status) { box.innerHTML = `<h3 id="cf-t">${t("conf_title")}</h3><div class="empty">${esc(conf.error?.message || "")}</div>`; return; }
  const st = conf.status, n = conf.pending_review.length;
  const worst = conf.entity_drift.sort((a, b) => ({ DRIFT: 2, WATCH: 1, STABLE: 0 }[b.status] - { DRIFT: 2, WATCH: 1, STABLE: 0 }[a.status]))[0];
  const row = (icon, title, desc, level, href) => `<a class="conf-row" href="${href}">
      <span class="ic">${icons[icon]}</span><span><span class="t">${title}</span><br><span class="d">${esc(desc)}</span></span>
      ${pill(level)}<span class="chev">${icons.chevron.replace("<svg", '<svg width="16" height="16"')}</span></a>`;
  box.innerHTML = `<div class="card-head"><h3 id="cf-t">${t("conf_title")}</h3>
      ${n ? `<a class="badge-warn" href="#/quality">${icons.warn}${t("review")} (${n})</a>` : ""}</div>
    <div style="margin-top:6px">
      ${row("db", t("fresh"), t("fresh_d", { p: monthName(st.ismo_latest_period, state.lang, true), d: st.ismo_age_days, h: fmt.n1(st.live_age_hours) }), conf.freshness_level, "#/quality")}
      ${row("search", t("qual"), t("qual_d", { f: st.n_fix, fl: st.n_fill, g: st.n_flag }), st.overall, "#/quality")}
      ${row("trend", t("drift"), worst ? `${entShort(worst.entity)}: ${worst.detail}` : "-", conf.drift_level, "#/quality")}
    </div>
    <div class="run-line">${conf.last_success ? esc(t("last_ok", { t: pkt(conf.last_success.finished_at_utc) })) : ""}</div>
    <a class="link-more" href="#/quality">${t("view_details")} ${icons.arrow.replace("<svg", '<svg width="14" height="14"')}</a>`;
}

// ------------------------------------------------------------------ composer + drawer
function composerHTML() {
  return `<section class="card composer" aria-label="${t("ask")}">
    <div class="who">${icons.sparkle}<div><b>${t("ask")}</b><span>${t("ask_sub")}</span></div></div>
    <form id="ask-form" autocomplete="off">
      <label class="sr-only" for="ask-in">${t("ask")}</label>
      <input id="ask-in" name="q" maxlength="500" placeholder="${esc(t("ask_ph"))}">
      <div class="chips"><span>${t("sources")}:</span><span class="chip">ISMO</span><span class="chip">NEPRA</span><span class="chip">ERA5</span></div>
      <button class="send" type="submit" aria-label="${t("send")}">${icons.send}</button>
    </form></section>`;
}
function bindComposer() {
  view.querySelector("#ask-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = e.target.q.value.trim() || t("ask_ph").replace("…", "");
    e.target.q.value = "";
    ask(q);
  });
}

function openDrawer() {
  const root = document.getElementById("drawer-root");
  if (root.innerHTML) { renderThread(); return; }
  root.innerHTML = `<div class="scrim" data-close></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dr-t">
      <header><h2 id="dr-t">${icons.sparkle}${t("drawer_title")}</h2><button class="icon-btn" type="button" data-close aria-label="${t("close")}">${icons.close}</button></header>
      <div class="ctx" id="ctx"></div>
      <div class="thread" id="thread"></div>
      <form id="dr-form" autocomplete="off"><label class="sr-only" for="dr-in">${t("ask")}</label>
        <input id="dr-in" name="q" maxlength="500" placeholder="${esc(t("ask_ph"))}">
        <button class="send" type="submit" aria-label="${t("send")}">${icons.send}</button></form>
    </aside>`;
  root.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeDrawer));
  root.querySelector("#dr-form").addEventListener("submit", (e) => { e.preventDefault(); const q = e.target.q.value.trim(); if (q) { e.target.q.value = ""; ask(q); } });
  document.addEventListener("keydown", escClose);
  renderThread();
  root.querySelector("#dr-in").focus();
  if (STATIC && !prepared) {
    fetch("data/prepared_answers.json", { cache: "no-cache" }).then((r) => r.json()).then((p) => { prepared = p; renderThread(); }).catch(() => {});
  }
}
function escClose(e) { if (e.key === "Escape") closeDrawer(); }
function closeDrawer() {
  document.getElementById("drawer-root").innerHTML = "";
  document.removeEventListener("keydown", escClose);
  view.querySelector("#ask-in")?.focus();
}
function docHref(url) {
  if (!url) return null;
  if (/^https?:/.test(url)) return url;
  if (url.startsWith("docs/")) return `files/docs/${url.slice(5)}`;
  if (url.startsWith("reports/")) return `files/reports/${url.slice(8)}`;
  return null;
}
function renderThread() {
  const ctx = document.getElementById("ctx"), th = document.getElementById("thread");
  if (!ctx) return;
  ctx.innerHTML = `<span>${t("ctx")}:</span><span class="chip">${esc(entShort(state.entity))}</span><span class="chip">${monthName(state.month, state.lang)}</span><span class="chip">${state.lang === "ur" ? "اردو" : "English"}</span>`;
  const suggestions = STATIC && prepared ? `<div class="ev"><h4>${t("try_these")}</h4><div class="filter-chips">${prepared.answers
    .filter((a) => a.lang === state.lang && a.featured).slice(0, 8)
    .map((a) => `<button type="button" data-suggest="${esc(a.question)}">${esc(a.question)}</button>`).join("")}</div></div>` : "";
  th.innerHTML = (STATIC ? `<div class="banner warn">${icons.info}<span>${t("static_mode")}</span></div>${suggestions}` : "") + state.thread.map((m) => {
    const q = `<div class="q" dir="auto">${esc(m.q)}</div>`;
    if (m.loading) return q + `<div class="a">${skel(14)}<div style="height:8px"></div>${skel(14)}<div class="period" style="margin-top:8px">${t("thinking")}</div></div>`;
    if (m.error) return q + `<div class="a"><div class="banner bad">${icons.warn}<span>${esc(t("ask_err", { e: m.error }))}</span></div></div>`;
    const a = m.ans, rtl = a.lang === "ur";
    const paras = (a.prepared && a.matched_question ? `<p class="period">${esc(t("prepared_note", { q: a.matched_question, t: pkt(a.asked_at_utc) }))}</p>` : "") +
      a.text.split(/\n\s*\n/).map((p) => `<p>${esc(p)}</p>`).join("");
    const cites = a.citations.length ? `<ul>${a.citations.map((c) => {
      const href = docHref(c.url);
      const label = `${esc(c.title)}${c.page ? ` · p.${c.page}` : ""}`;
      return `<li>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${label}</a>` : label} <span class="period">${esc(c.publisher)} · ${esc(c.doc_id)}</span></li>`;
    }).join("")}</ul>` : `<div class="period">${t("ev_none")}</div>`;
    const rows = a.row_ids.length ? `<details><summary>${t("ev_rows")} (${a.row_ids.length})</summary><div class="rids">${a.row_ids.map((r) => `<code>${esc(r)}</code>`).join("")}</div></details>` : "";
    return q + `<div class="a"><div class="a-head">${pill(a.status, t("st_" + a.status))}<span class="period">${pkt(a.asked_at_utc, false)} PKT</span></div>
      <div class="a-body" dir="${rtl ? "rtl" : "ltr"}">${paras}</div>
      <div class="ev"><h4>${t("ev_sources")}</h4>${cites}${rows}</div></div>`;
  }).join("");
  th.querySelectorAll("[data-suggest]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.suggest)));
  th.scrollTop = th.scrollHeight;
}
async function ask(q) {
  const item = { q, loading: true };
  state.thread.push(item);
  openDrawer();
  renderThread();
  try {
    item.ans = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, lang: /[؀-ۿ]/.test(q) ? "ur" : state.lang, entity: state.entity, month: state.month }) });
  } catch (e) { item.error = e.message; }
  item.loading = false;
  renderThread();
}

// ------------------------------------------------------------------ FORECASTS
async function viewForecasts() {
  view.innerHTML = `<div class="page-head"><div><h1>${t("fc_title")}</h1><div class="sub">${t("fc_sub")}</div></div>${filtersHTML()}</div>
    <div class="grid-cards" id="fc-grid">${skel(170).repeat(4)}</div>
    <section class="card"><h2>${t("history")}</h2><div class="card-sub">${t("history_sub")}</div><div id="hist" style="margin-top:10px">${skel(80)}</div></section>
    <div class="foot">${t("footer")}</div>`;
  bindFilters(() => viewForecasts());
  const [fc, hist] = await Promise.all([api(`/api/forecasts?month=${state.month}`), api(`/api/forecast_history?entity=${state.entity}&month=${state.month}`)]);
  const grid = view.querySelector("#fc-grid");
  grid.innerHTML = fc.entities.map((e) => `<article class="card ent-card">
      <div class="card-head"><div><h3>${esc(e.entity === "KE" ? "K-Electric" : e.entity)}</h3><div class="card-sub">${esc(e.name)} · ${esc(e.province)}</div></div></div>
      <div class="stat num">${fmt.n0(e.mean_mw)} <small style="font-size:14px">MW</small></div>
      <div class="s">${t("peak_at")} ${fmt.n0(e.peak_mw)} MW · ${fmt.hh(e.peak_hour)} PKT · ${fmt.pct(e.weather_coverage * 100, 0)} ${t("cov")}</div>
      <div class="chart" data-spark="${e.entity}" style="margin-top:8px"></div>
      <button class="btn" type="button" data-open="${e.entity}">${t("open_ws")}</button></article>`).join("") ||
    `<div class="card"><div class="empty"><b>${t("no_fc")}</b></div></div>`;
  fc.entities.forEach((e) => sparkline(grid.querySelector(`[data-spark="${e.entity}"]`), { values: e.profile, lo: e.lo, hi: e.hi }));
  grid.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => { state.entity = b.dataset.open; store.set("bc.entity", state.entity); state.hour = null; location.hash = "#/workspace"; }));
  view.querySelector("#hist").innerHTML = hist.snapshots.length ? `<div class="tbl-wrap"><table class="data"><thead><tr><th>${t("run_at")}</th>
      <th class="r">${t("mean")} (MW)</th><th class="r">${t("peak")} (MW)</th><th class="r">${t("cov")}</th></tr></thead><tbody>
      ${hist.snapshots.slice().reverse().map((s) => `<tr><td>${pkt(s.generated_at_utc)}</td><td class="r">${fmt.n0(s.mean_mw)}</td><td class="r">${fmt.n0(s.peak_mw)}</td><td class="r">${fmt.pct(s.weather_coverage * 100, 0)}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty">-</div>`;
}

// ------------------------------------------------------------------ COST LENS
async function viewCost() {
  view.innerHTML = `<div class="page-head"><div><h1>${t("cost_page")}</h1><div class="sub">${esc(t("cost_page_sub", { ent: entShort(state.entity) }))}</div></div>${filtersHTML({ months: false })}</div>
    <div id="cost-body">${skel(300)}</div><div class="foot">${t("footer")}</div>`;
  bindFilters(() => { state.costPeriod = null; viewCost(); });
  const c = await api(`/api/cost?entity=${state.entity}${state.costPeriod ? `&period=${state.costPeriod}` : ""}`);
  const body = view.querySelector("#cost-body");
  if (!c.hourly?.length) { body.innerHTML = `<div class="card"><div class="empty"><b>${esc(c.empty_reason || "")}</b></div></div>`; return; }
  state.costPeriod = c.period;
  const s = c.summary;
  const hrs = (v) => String(v || "").split(",").map((h) => fmt.hh(+h)).join(", ");
  body.innerHTML = `
    <div class="field" style="max-width:240px"><label for="f-period">${t("period")}</label><select id="f-period" class="select">
      ${c.periods.slice().reverse().map((p) => `<option value="${p}" ${p === c.period ? "selected" : ""}>${monthName(p, state.lang)}</option>`).join("")}</select></div>
    <div class="row-two" style="margin-top:12px">
      <section class="card"><h2>${t("price_chart")}</h2><div class="card-sub">PKR/MWh · ${monthName(c.period, state.lang)} · ISMO</div><div id="b1" class="chart" style="margin-top:10px"></div></section>
      <section class="card"><h2>${esc(t("cost_chart", { ent: entShort(state.entity) }))}</h2><div class="card-sub">${t("pkr_m_h")} · ${monthName(c.period, state.lang)}</div><div id="b2" class="chart" style="margin-top:10px"></div></section>
    </div>
    ${s ? `<section class="card" style="margin-top:16px"><h2>${monthName(c.period, state.lang)} · <span class="mono">${esc(s.row_id)}</span></h2>
      <div class="tiles">
        <div class="tile"><div class="k">${t("daily_cost")}</div><div class="stat">PKR ${fmt.n0(s.daily_cost_rs_m)}m</div></div>
        <div class="tile"><div class="k">${t("eve_energy")}</div><div class="stat">${fmt.pct(s.evening_peak_energy_share_pct, 0)}</div></div>
        <div class="tile"><div class="k">${t("eve_cost")}</div><div class="stat">${fmt.pct(s.evening_peak_cost_share_pct, 0)}</div></div>
        <div class="tile"><div class="k">${t("dear")}</div><div class="stat" style="font-size:16px">${hrs(s.dearest_hours)}</div><div class="s">${fmt.n0(s.dearest_price_rs_kwh * 1000)} PKR/MWh</div></div>
        <div class="tile"><div class="k">${t("cheap")}</div><div class="stat" style="font-size:16px">${hrs(s.cheapest_hours)}</div><div class="s">${fmt.n0(s.cheapest_price_rs_kwh * 1000)} PKR/MWh</div></div>
        <div class="tile"><div class="k">${t("shift")}</div><div class="stat">PKR ${fmt.n0(s.shift_saving_rs_m_per_month)}m</div><div class="s">/ month</div></div>
      </div><p class="reason">${t("shift_note")}</p></section>` : ""}
    <div class="row-two" style="margin-top:16px">
      <section class="card"><h2>${t("monthly_cost")}</h2><div class="tbl-wrap scroll-y" style="margin-top:10px"><table class="data"><thead><tr><th>${t("month")}</th>
        <th class="r">${t("daily_cost")} (PKR m)</th><th class="r">${t("eve_cost")}</th><th class="r">${t("shift")} (PKR m)</th><th>Row ID</th></tr></thead><tbody>
        ${c.monthly.slice().reverse().map((r) => `<tr><td>${monthName(r.period, state.lang, true)}</td><td class="r">${fmt.n0(r.daily_cost_rs_m)}</td><td class="r">${fmt.pct(r.evening_peak_cost_share_pct, 0)}</td><td class="r">${fmt.n0(r.shift_saving_rs_m_per_month)}</td><td class="mono">${r.row_id}</td></tr>`).join("")}
      </tbody></table></div></section>
      <section class="card"><h2>${t("exposure")}</h2><p class="reason">${t("exposure_note")}</p><div class="tbl-wrap"><table class="data"><thead><tr><th>${t("month")}</th>
        <th class="r">${t("model_risk")}</th><th class="r">${t("base_risk")}</th><th class="r">${t("reduction")}</th><th>Row ID</th></tr></thead><tbody>
        ${c.exposure.map((r) => `<tr><td>${monthName(r.period, state.lang, true)}</td><td class="r">${fmt.n1(r.model_risk_rs_m_per_day)}</td><td class="r">${fmt.n1(r.baseline_risk_rs_m_per_day)}</td><td class="r">${fmt.n1(r.risk_reduction_rs_m_per_day)}</td><td class="mono">${r.row_id}</td></tr>`).join("") || `<tr><td colspan="5">-</td></tr>`}
      </tbody></table></div></section>
    </div>`;
  body.querySelector("#f-period").addEventListener("change", (e) => { state.costPeriod = e.target.value; viewCost(); });
  barChart(body.querySelector("#b1"), { values: c.hourly.map((d) => ({ hour: d.hour, v: d.price_pkr_mwh, row_id: d.price_row_id })), highlight: EVENING, height: 220, fmtV: (v) => `${fmt.n0(v)} PKR/MWh` });
  barChart(body.querySelector("#b2"), { values: c.hourly.map((d) => ({ hour: d.hour, v: d.cost_pkr_m_per_hour, row_id: `${d.demand_row_id} x ${d.price_row_id}` })), highlight: EVENING, height: 220, fmtV: (v) => `PKR ${fmt.n1(v)}m / hour`, axisFmt: (v) => fmt.n0(v) });
}

// ------------------------------------------------------------------ DATA QUALITY
async function viewQuality(keep = false) {
  // keep: a decision-log filter changed - refresh the content in place so the page keeps its scroll position
  if (!keep) {
    view.innerHTML = `<div class="page-head"><div><h1>${t("dq_title")}</h1><div class="sub">${t("dq_sub")}</div></div>${filtersHTML({ months: false })}</div>
      <div id="dq">${skel(400)}</div><div class="foot">${t("footer")}</div>`;
    bindFilters(() => viewQuality());
  }
  const [conf, q, runs] = await Promise.all([api(`/api/confidence?entity=${state.entity}`), api(`/api/quality${state.dqFilter ? `?action=${state.dqFilter}` : ""}`), api("/api/runs")]);
  const st = conf.status;
  const actionPill = (a) => pill({ FIX: "neutral", FILL: "neutral", FLAG: "AMBER", PASS: "GREEN" }[a] || "neutral", a);
  view.querySelector("#dq").innerHTML = `${banners(conf)}
    <section class="card"><div class="card-head"><h2>${t("overall")}: ${pill(st.overall)}</h2><span class="period">${esc(st.run_id)} · ${pkt(st.built_at_utc)} PKT</span></div>
      <div class="tiles">
        <div class="tile"><div class="k">${t("fixes")}</div><div class="stat">${st.n_fix}</div></div>
        <div class="tile"><div class="k">${t("fills")}</div><div class="stat">${st.n_fill}</div></div>
        <div class="tile"><div class="k">${t("flags")}</div><div class="stat">${st.n_flag}</div></div>
        <div class="tile"><div class="k">${t("critical")}</div><div class="stat">${st.n_critical}</div></div>
        <div class="tile"><div class="k">${t("pending")}</div><div class="stat">${conf.pending_review.length}</div></div>
        <div class="tile"><div class="k">${t("fresh")}</div><div class="stat" style="font-size:16px">${pill(conf.freshness_level)}</div><div class="s">${esc(t("fresh_d", { p: monthName(st.ismo_latest_period, state.lang, true), d: st.ismo_age_days, h: fmt.n1(st.live_age_hours) }))}</div></div>
      </div></section>
    <div class="row-two" style="margin-top:16px">
      <section class="card"><h2>${t("src_fresh")}</h2><div class="tbl-wrap" style="margin-top:8px"><table class="data"><thead><tr><th>${t("source")}</th><th class="r">${t("files")}</th><th>${t("last_fetch")}</th></tr></thead><tbody>
        ${conf.sources.map((s) => `<tr><td>${esc(s.source)}</td><td class="r">${s.files}</td><td>${pkt(s.last_fetched_utc)}</td></tr>`).join("")}</tbody></table></div>
        <p class="reason">ISMO publishes each month ~15 days after it ends; the latest month is ${monthName(st.ismo_latest_period, state.lang)} (${st.ismo_age_days} days since month end). Fetch time is when the pipeline last downloaded, not when the publisher updated.</p></section>
      <section class="card"><h2>${t("runs")}</h2><div class="tbl-wrap scroll-y" style="margin-top:8px"><table class="data"><thead><tr><th>${t("started")}</th><th class="r">${t("duration")}</th><th>${t("status")}</th><th>${t("quality")}</th></tr></thead><tbody>
        ${runs.runs.map((r) => { const dur = (new Date(r.finished_at_utc) - new Date(r.started_at_utc)) / 1000;
          return `<tr><td>${pkt(r.started_at_utc)}</td><td class="r">${fmt.n0(dur)} s</td><td>${pill(r.status)}</td><td>${r.quality ? pill(r.quality) : "-"}</td></tr>`; }).join("") || `<tr><td colspan="4">-</td></tr>`}
      </tbody></table></div></section>
    </div>
    <section class="card" style="margin-top:16px" id="review"><h2>${t("review_q")} (${conf.pending_review.length})</h2><div class="tbl-wrap scroll-y" style="margin-top:8px"><table class="data"><thead><tr><th>${t("check")}</th><th>${t("entity")}</th><th>${t("month")}</th><th>${t("reason")}</th></tr></thead><tbody>
      ${conf.pending_review.map((r) => `<tr><td class="mono">${esc(r.check_id)}</td><td>${esc(r.entity || "-")}</td><td>${esc(r.period || "-")}</td><td class="reason">${esc(r.reason)}</td></tr>`).join("") || `<tr><td colspan="4">-</td></tr>`}
    </tbody></table></div></section>
    <section class="card" style="margin-top:16px"><div class="card-head"><h2>${t("decisions")}</h2>
      <div class="filter-chips" role="group">${["", "FIX", "FILL", "FLAG", "PASS"].map((a) => `<button type="button" data-a="${a}" aria-pressed="${state.dqFilter === a}">${a || t("all")}${a ? ` (${q.counts[a] || 0})` : ""}</button>`).join("")}</div></div>
      <div class="tbl-wrap scroll-y" style="margin-top:8px"><table class="data"><thead><tr><th>${t("check")}</th><th>${t("action")}</th><th>${t("entity")}</th><th>${t("month")}</th><th class="r">${t("rows")}</th><th>${t("reason")}</th></tr></thead><tbody>
      ${q.decisions.map((d) => `<tr><td class="mono">${esc(d.check_id)}</td><td>${actionPill(d.action)}</td><td>${esc(d.entity || "-")}</td><td>${esc(d.period || "-")}</td><td class="r">${fmt.n0(d.rows_affected)}</td><td class="reason">${esc(d.reason)}</td></tr>`).join("")}
    </tbody></table></div></section>
    <section class="card" style="margin-top:16px"><h2>${t("drift_t")}</h2><div class="tbl-wrap scroll-y" style="margin-top:8px"><table class="data"><thead><tr><th>${t("entity")}</th><th>${t("metric")}</th><th class="r">${t("value")}</th><th>${t("status")}</th><th>${t("reason")}</th></tr></thead><tbody>
      ${conf.drift.map((d) => `<tr><td>${esc(entShort(d.entity))}</td><td>${esc(d.metric)}</td><td class="r">${fmt.n2(d.value)}</td><td>${pill(d.status)}</td><td class="reason">${esc(d.detail)}</td></tr>`).join("")}
    </tbody></table></div></section>`;
  view.querySelectorAll("[data-a]").forEach((b) => b.addEventListener("click", () => { state.dqFilter = b.dataset.a; viewQuality(true); }));
}

// ------------------------------------------------------------------ ANALYSIS
async function viewAnalysis() {
  view.innerHTML = `<div class="page-head"><div><h1>${t("an_title")}</h1><div class="sub">${t("an_sub")}</div></div>${filtersHTML({ months: false })}</div><div id="an">${skel(400)}</div>`;
  bindFilters(() => viewAnalysis());
  const p = await api(`/api/performance?entity=${state.entity}`);
  const m = p.metrics;
  const grp = (by) => `<section class="card"><h2>${t("by")} ${esc(by.replace("_", " "))}</h2><div class="tbl-wrap" style="margin-top:8px"><table class="data"><thead><tr><th></th>
      <th class="r">${t("model")}</th><th class="r">${t("baseline")}</th><th class="r">${t("change")}</th><th class="r">${t("coverage")}</th><th class="r">${t("bias")}</th></tr></thead><tbody>
      ${p.groups.filter((g) => g.group_by === by).map((g) => `<tr><td>${esc(g.group_value)}</td><td class="r">${fmt.pct(g.model_mape)}</td><td class="r">${fmt.pct(g.baseline_mape)}</td>
        <td class="r">${g.improvement_pct >= 0 ? "-" : "+"}${fmt.n0(Math.abs(g.improvement_pct))}%</td><td class="r">${fmt.pct(g.coverage_80, 0)}</td><td class="r">${g.bias_pct > 0 ? "+" : ""}${fmt.n1(g.bias_pct)}%</td></tr>`).join("")}
      </tbody></table></div></section>`;
  view.querySelector("#an").innerHTML = `
    <section class="card"><div class="tiles">
      <div class="tile"><div class="k">${t("overall_mape")}</div><div class="stat">${fmt.pct(m.model_mape, 2)}</div><div class="s">${t("base_mape")} ${fmt.pct(m.baseline_mape, 2)}</div></div>
      <div class="tile"><div class="k">${t("ke_mape")}</div><div class="stat">${fmt.pct(m.ke_model_mape, 2)}</div><div class="s">baseline ${fmt.pct(m.ke_baseline_mape, 2)}</div></div>
      <div class="tile"><div class="k">Evening peak MAPE</div><div class="stat">${fmt.pct(m.peak_model_mape, 2)}</div><div class="s">baseline ${fmt.pct(m.peak_baseline_mape, 2)}</div></div>
      <div class="tile"><div class="k">${t("coverage")}</div><div class="stat">${fmt.pct(m.coverage_80, 1)}</div><div class="s">target 80%</div></div>
    </div><p class="reason">${esc(p.baseline_definition)}. Test months: ${(m.test_months || []).join(", ")} (Jun-Jul 2026 not published by ISMO).</p></section>
    <section class="card" style="margin-top:16px"><h2>${esc(t("by_month", { ent: entShort(state.entity) }))}</h2><div class="tbl-wrap" style="margin-top:8px"><table class="data"><thead><tr><th>${t("month")}</th><th class="r">${t("model")}</th><th class="r">${t("baseline")}</th></tr></thead><tbody>
      ${p.by_month.map((r) => `<tr><td>${monthName(r.period, state.lang, true)}</td><td class="r">${fmt.pct(r.model_mape)}</td><td class="r">${fmt.pct(r.baseline_mape)}</td></tr>`).join("")}</tbody></table></div></section>
    <div class="row-two" style="margin-top:16px">${grp("entity")}${grp("season")}</div>
    <div class="row-two" style="margin-top:16px">${grp("province")}${grp("hour_band")}</div>
    <section class="card" style="margin-top:16px"><h2>Figures</h2>
      <img class="fig" style="margin-top:10px" src="files/reports/figures/baseline_vs_model.png" alt="Bar chart: test MAPE by entity, model versus declared baseline">
      <img class="fig" style="margin-top:10px" src="files/reports/figures/ke_profiles_test.png" alt="K-Electric hourly profiles for each test month: actual, model with 80% interval, and baseline">
      <img class="fig" style="margin-top:10px" src="files/reports/figures/errors_by_group.png" alt="Test MAPE by season and hour band, model versus baseline"></section>`;
}

// ------------------------------------------------------------------ SCENARIOS (what if it is hotter?)
const DELTAS = [-2, -1, 0, 1, 2, 3, 5];
const sgn = (d) => (d > 0 ? `+${d}` : `${d}`);
async function viewScenarios() {
  if (state.delta == null) state.delta = 3;
  view.innerHTML = `<div class="page-head"><div><h1>${t("sc_title")}</h1><div class="sub">${t("sc_sub")}</div></div>${filtersHTML()}</div>
    <section class="card"><div class="card-head"><div><h2>${t("sc_shift")}</h2><div class="card-sub">${t("sc_shift_sub")}</div></div>
      <div class="filter-chips" role="group" aria-label="${t("sc_shift")}">${DELTAS.map((d) =>
        `<button type="button" data-d="${d}" aria-pressed="${d === state.delta}">${sgn(d)}°C</button>`).join("")}</div></div>
      <div id="sc-body" style="margin-top:12px">${skel(340)}</div></section>
    <div class="foot">${t("footer")}</div>`;
  bindFilters(() => viewScenarios());
  view.querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => { state.delta = +b.dataset.d; viewScenarios(); }));
  const s = await api(`/api/scenario?entity=${state.entity}&month=${state.month}&delta=${state.delta}`);
  const body = view.querySelector("#sc-body");
  if (!s.hours?.length) { body.innerHTML = `<div class="empty"><b>${esc(s.empty_reason || t("no_fc"))}</b></div>`; return; }
  const m = s.summary, chg = (v, unit = " MW") => `${v > 0 ? "+" : ""}${fmt.n0(v)}${unit}`;
  body.innerHTML = `
    ${s.outside_training_range ? `<div class="banner warn" role="status">${icons.warn}<span>${esc(t("sc_outside", { max: s.scenario_max_temp_c, train: s.training_max_temp_c }))}</span></div>` : ""}
    <div class="tiles">
      <div class="tile"><div class="k">${t("mean")}</div><div class="stat">${fmt.n0(m.scen_mean_mw)} MW</div>
        <div class="s">${chg(m.change_mw)} (${m.change_pct > 0 ? "+" : ""}${fmt.n1(m.change_pct)}%) · ${t("sc_base")} ${fmt.n0(m.base_mean_mw)} MW</div></div>
      <div class="tile"><div class="k">${t("peak")}</div><div class="stat">${fmt.n0(m.scen_peak_mw)} MW</div>
        <div class="s">${fmt.hh(m.scen_peak_hour)} PKT · ${chg(m.peak_change_mw)}</div></div>
      <div class="tile"><div class="k">${t("sc_temp")}</div><div class="stat">${fmt.n1(s.scenario_max_temp_c)}°C</div>
        <div class="s">${esc(t("sc_train", { t: fmt.n1(s.training_max_temp_c) }))}</div></div>
    </div>
    <div class="legend" style="margin-top:14px"><span><span class="sw sw-line"></span> ${t("sc_line")} (${sgn(state.delta)}°C)</span>
      <span><span class="sw sw-band"></span> ${t("lg_band")}</span><span><span class="sw sw-dash"></span> ${t("sc_base")}</span>
      <span><span class="sw sw-eve"></span> ${t("lg_eve")}</span></div>
    <div id="sc-chart" class="chart" style="margin-top:6px"></div>
    <h3 style="margin-top:18px">${t("sc_curve")}</h3>
    <div class="tbl-wrap" style="margin-top:6px"><table class="data"><thead><tr><th>${t("sc_delta")}</th><th class="r">${t("mean")} (MW)</th>
      <th class="r">${t("change")}</th><th class="r">${t("peak")} (MW)</th><th></th></tr></thead><tbody>
      ${(s.curve || []).map((c) => `<tr ${c.delta_c === state.delta ? 'style="font-weight:700"' : ""}><td>${sgn(c.delta_c)}°C</td><td class="r">${fmt.n0(c.mean_mw)}</td>
        <td class="r">${c.change_pct > 0 ? "+" : ""}${fmt.n1(c.change_pct)}%</td><td class="r">${fmt.n0(c.peak_mw)}</td>
        <td>${c.outside_training_range ? pill("AMBER", t("sc_flag")) : ""}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="reason">${t("sc_explain")}</p>
    <p class="period">${esc(s.assumptions)} · model ${esc(s.model_version)} · ${fmt.pct(s.weather_coverage * 100, 0)} ${t("cov")}</p>`;
  demandChart(body.querySelector("#sc-chart"), {
    forecast: s.hours.map((h) => ({ hour: h.hour, pred: h.scen, lo: h.lo, hi: h.hi })),
    baseline: s.hours.map((h) => ({ hour: h.hour, value: h.base })),
    visible: { forecast: true, band: true, baseline: true, evening: true }, evening: EVENING, selected: null, t,
    labels: { forecast: `${t("sc_line")} ${sgn(state.delta)}°C`, base: t("sc_base") },
  });
}

// ------------------------------------------------------------------ DATA (sources)
async function viewData() {
  view.innerHTML = `<div class="page-head"><div><h1>${t("data_title")}</h1><div class="sub">${t("data_sub")}</div></div></div><div id="src">${skel(400)}</div>`;
  const s = await api("/api/sources");
  view.querySelector("#src").innerHTML = `<section class="card"><div class="tbl-wrap scroll-y" style="max-height:640px"><table class="data"><thead><tr>
      <th>${t("file")}</th><th>${t("source")}</th><th>${t("period")}</th><th>${t("fetched")}</th><th>SHA-256</th><th>${t("licence")}</th></tr></thead><tbody>
    ${s.files.map((f) => `<tr><td><span class="mono">${esc(f.file_id)}</span><br><span class="period">${esc(f.title)}</span></td><td>${esc(f.source)}</td><td>${esc(f.period)}</td>
      <td>${esc((f.fetched_at_utc || "").replace("T", " ").replace("Z", ""))}</td><td class="mono">${esc(f.sha256_12)}…</td><td class="reason">${esc(f.licence)}</td></tr>`).join("")}
    </tbody></table></div></section>`;
}

// ------------------------------------------------------------------ REPORTS
async function viewReports() {
  const docs = [
    ["files/docs/Summary.pdf", "Summary.pdf", "One-page summary"],
    ["files/docs/datasetproposal.pdf", "datasetproposal.pdf", "Dataset proposal: sources, licences, volume"],
    ["files/reports/model_report.md", "model_report.md", "Model report: baseline vs model, errors by group"],
    ["files/docs/optimization_log.md", "optimization_log.md", "Optimization log"],
    ["files/docs/business_model.md", "business_model.md", "Business model"],
    ["files/docs/problem_analysis.md", "problem_analysis.md", "Problem analysis"],
    ["files/docs/baseline_declaration.md", "baseline_declaration.md", "Baseline declaration"],
    ["files/reports/quality_log_latest.csv", "quality_log_latest.csv", "Data Quality Agent decisions (latest build)"],
  ];
  view.innerHTML = `<div class="page-head"><div><h1>${t("rep_title")}</h1><div class="sub">${t("rep_sub")}</div></div></div>
    <section class="card"><ul class="doc-list">${docs.map(([h, n, d]) => `<li><a href="${h}" target="_blank" rel="noopener"><b>${esc(n)}</b><span>${esc(d)}</span></a></li>`).join("")}</ul></section>`;
}

// ------------------------------------------------------------------ SETTINGS
async function viewSettings() {
  view.innerHTML = `<div class="page-head"><div><h1>${t("set_title")}</h1></div></div>
    <section class="card"><h2>${t("set_lang")}</h2><div class="lang" style="width:fit-content;margin-top:10px" role="group" aria-label="${t("set_lang")}">
      <button type="button" data-lang="en" aria-pressed="${state.lang === "en"}">English</button><button type="button" data-lang="ur" aria-pressed="${state.lang === "ur"}">اردو</button></div></section>
    <section class="card"><h2>${t("set_about")}</h2><p class="reason">${t("set_about_t")}</p>
      <p class="period">${t("snapshot")}: ${pkt(state.meta.snapshot_utc)} PKT · forecast generated ${pkt(state.meta.forecast_generated_at_utc)} PKT${STATIC ? "" : ` · API: <a href="/docs" target="_blank" rel="noopener">/docs</a>`}</p></section>`;
  view.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
}

// ------------------------------------------------------------------ boot
function setLang(lang) {
  state.lang = lang; store.set("bc.lang", lang); t = makeT(lang);
  render();
  if (document.getElementById("drawer-root").innerHTML) { document.getElementById("drawer-root").innerHTML = ""; openDrawer(); }
}
document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
window.addEventListener("hashchange", () => { render(); view.focus({ preventScroll: true }); window.scrollTo(0, 0); });
render();
