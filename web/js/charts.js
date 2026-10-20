// Hand-built SVG charts: monotone curves (no overshoot), evening window, hover/keyboard, resize-aware.
import { fmt } from "./i18n.js";

const NS = "http://www.w3.org/2000/svg";
const C = { blue: "#0755F5", band: "#D7E7FF", base: "#A4AAB5", grid: "#EDF1F7", eve: "#FFE3DA", coral: "#FF927C", text: "#637391" };

function niceMax(v) {
  if (!(v > 0)) return 1;
  const raw = v / 5, mag = 10 ** Math.floor(Math.log10(raw)), r = raw / mag;
  const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag;
  return { max: Math.ceil(v / step) * step, step };
}

// Fritsch-Butland monotone cubic through points sorted by x (same family as d3.curveMonotoneX).
export function monotone(pts, move = true) {
  const n = pts.length;
  if (n === 0) return "";
  if (n === 1) return `${move ? "M" : "L"}${pts[0][0]},${pts[0][1]}`;
  const dx = [], m = [], t = new Array(n);
  for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; m[i] = (pts[i + 1][1] - pts[i][1]) / dx[i]; }
  t[0] = m[0]; t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) {
    t[i] = m[i - 1] * m[i] <= 0 ? 0 : (3 * (dx[i - 1] + dx[i])) / ((2 * dx[i] + dx[i - 1]) / m[i - 1] + (dx[i] + 2 * dx[i - 1]) / m[i]);
  }
  let d = `${move ? "M" : "L"}${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[i + 1], h = dx[i] / 3;
    d += `C${(x0 + h).toFixed(1)},${(y0 + t[i] * h).toFixed(1)} ${(x1 - h).toFixed(1)},${(y1 - t[i + 1] * h).toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  return d;
}

const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
};

function observe(container, draw) {
  if (container._ro) container._ro.disconnect();
  let w = 0;
  const ro = new ResizeObserver(() => { const nw = container.clientWidth; if (Math.abs(nw - w) > 2) { w = nw; draw(); } });
  ro.observe(container);
  container._ro = ro;
  draw();
}

/** Monthly hourly demand chart. opts: forecast[{hour,pred,lo,hi,row_id}], baseline[{hour,value,row_id}],
 *  visible{forecast,band,baseline,evening}, evening[from,to], selected, onSelect(h), t(), height */
export function demandChart(container, opts) {
  const tip = document.createElement("div");
  tip.className = "tip"; tip.hidden = true;
  const draw = () => {
    const W = Math.max(container.clientWidth, 280);
    const H = opts.height || (W < 520 ? 240 : 290);
    const m = { l: 48, r: 38, t: 10, b: 30 };
    const fc = opts.forecast, base = opts.baseline || [], vis = opts.visible;
    const top = Math.max(...fc.map((d) => d.hi), ...(vis.baseline ? base.map((d) => d.value) : [0]));
    const { max: ymax, step } = niceMax(top * 1.04);
    const x = (h) => m.l + (h / 23) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - v / ymax) * (H - m.t - m.b);
    container.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "presentation" }, container);

    for (let v = 0; v <= ymax + 1e-9; v += step) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: C.grid }, svg);
      const t = el("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }, svg);
      t.textContent = fmt.n0(v);
    }
    const every = W < 560 ? 3 : 1;
    for (let h = 0; h < 24; h += every) {
      const t = el("text", { x: x(h), y: H - 9, "text-anchor": "middle" }, svg);
      t.textContent = fmt.h2(h);
    }
    const pk = el("text", { x: W - 2, y: H - 9, "text-anchor": "end", class: "axis-title" }, svg);
    pk.textContent = "PKT";
    const yl = el("text", { x: 4, y: m.t + 2, "text-anchor": "start", class: "axis-title", transform: `rotate(-90 4 ${m.t + 2})` }, svg);
    yl.textContent = "";

    if (vis.evening) {
      const x0 = Math.max(m.l, x(opts.evening[0] - 0.5)), x1 = Math.min(W - m.r, x(opts.evening[1] + 0.5));
      el("rect", { x: x0, y: m.t, width: x1 - x0, height: H - m.t - m.b, fill: C.eve, opacity: 0.85 }, svg);
    }
    if (vis.band) {
      const hi = fc.map((d) => [x(d.hour), y(d.hi)]), lo = fc.map((d) => [x(d.hour), y(d.lo)]).reverse();
      el("path", { d: monotone(hi) + monotone(lo, false) + "Z", fill: C.band, opacity: 0.85 }, svg);
    }
    if (vis.baseline && base.length) {
      el("path", { d: monotone(base.map((d) => [x(d.hour), y(d.value)])), fill: "none", stroke: C.base, "stroke-width": 2, "stroke-dasharray": "6 5" }, svg);
    }
    if (vis.forecast) {
      el("path", { d: monotone(fc.map((d) => [x(d.hour), y(d.pred)])), fill: "none", stroke: C.blue, "stroke-width": 2.6, "stroke-linecap": "round" }, svg);
    }

    const guide = el("line", { y1: m.t, y2: H - m.b, stroke: "#10172F", "stroke-opacity": 0.35, "stroke-dasharray": "3 3", visibility: "hidden" }, svg);
    const dot = el("circle", { r: 5, fill: C.blue, stroke: "#fff", "stroke-width": 2, visibility: "hidden" }, svg);
    const sel = opts.selected;
    if (sel != null && fc[sel]) {
      el("line", { x1: x(sel), x2: x(sel), y1: m.t, y2: H - m.b, stroke: C.blue, "stroke-opacity": 0.5 }, svg);
      el("circle", { cx: x(sel), cy: y(fc[sel].pred), r: 5.5, fill: C.blue, stroke: "#fff", "stroke-width": 2.5 }, svg);
    }

    const show = (h) => {
      const d = fc[h]; if (!d) return;
      guide.setAttribute("x1", x(h)); guide.setAttribute("x2", x(h)); guide.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(h)); dot.setAttribute("cy", y(d.pred)); dot.setAttribute("visibility", vis.forecast ? "visible" : "hidden");
      const b = base.find((r) => r.hour === h);
      const t = opts.t;
      tip.innerHTML = `<b>${fmt.hh(h)} PKT</b><br>${t("tip_forecast")}: <b>${fmt.n0(d.pred)} MW</b><br>` +
        `${t("tip_range")}: ${fmt.n0(d.lo)}-${fmt.n0(d.hi)} MW` +
        (b ? `<br>${t("tip_base")}: ${fmt.n0(b.value)} MW` : "") + `<br><span class="rid">${d.row_id}</span>`;
      tip.hidden = false;
      const left = Math.min(Math.max(x(h), 90), W - 90);
      tip.style.left = `${left}px`; tip.style.top = `${Math.max(y(d.hi) - 8, 64)}px`;
    };
    const hide = () => { tip.hidden = true; guide.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); };
    const step24 = (W - m.l - m.r) / 23;
    for (let h = 0; h < 24; h++) {
      const r = el("rect", { x: x(h) - step24 / 2, y: m.t, width: step24, height: H - m.t - m.b, fill: "transparent", style: "cursor:pointer" }, svg);
      r.addEventListener("mouseenter", () => show(h));
      r.addEventListener("click", () => opts.onSelect && opts.onSelect(h));
    }
    svg.addEventListener("mouseleave", hide);
    container.appendChild(tip);
  };
  container.tabIndex = 0;
  container.onkeydown = (e) => {
    if (!opts.onSelect) return;
    const cur = opts.selected ?? 0;
    if (e.key === "ArrowRight") { e.preventDefault(); opts.onSelect(Math.min(23, cur + 1)); }
    if (e.key === "ArrowLeft") { e.preventDefault(); opts.onSelect(Math.max(0, cur - 1)); }
  };
  observe(container, draw);
}

/** Hourly bar chart. values[{hour, v, row_id}], highlight[from,to], fmtV, unit */
export function barChart(container, opts) {
  const tip = document.createElement("div");
  tip.className = "tip"; tip.hidden = true;
  const draw = () => {
    const W = Math.max(container.clientWidth, 240), H = opts.height || 170;
    const m = { l: 46, r: 30, t: 8, b: 24 };
    const vals = opts.values;
    const { max: ymax, step } = niceMax(Math.max(...vals.map((d) => d.v)) * 1.05);
    const bw = (W - m.l - m.r) / vals.length;
    const y = (v) => m.t + (1 - v / ymax) * (H - m.t - m.b);
    container.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "presentation" }, container);
    for (let v = 0; v <= ymax + 1e-9; v += step) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: C.grid }, svg);
      const t = el("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, svg);
      t.textContent = opts.axisFmt ? opts.axisFmt(v) : fmt.n0(v);
    }
    vals.forEach((d, i) => {
      const hi = opts.highlight && d.hour >= opts.highlight[0] && d.hour <= opts.highlight[1];
      const r = el("rect", { x: m.l + i * bw + bw * 0.16, y: y(d.v), width: bw * 0.68, height: Math.max(0, y(0) - y(d.v)), rx: 2,
        fill: hi ? C.coral : C.blue, opacity: hi ? 1 : 0.82 }, svg);
      r.addEventListener("mouseenter", () => {
        tip.innerHTML = `<b>${fmt.hh(d.hour)} PKT</b><br>${opts.fmtV(d.v)}<br><span class="rid">${d.row_id || ""}</span>`;
        tip.hidden = false;
        tip.style.left = `${Math.min(Math.max(m.l + i * bw + bw / 2, 80), W - 80)}px`; tip.style.top = `${Math.max(y(d.v) - 6, 58)}px`;
      });
      r.addEventListener("mouseleave", () => { tip.hidden = true; });
      if (i % (W < 420 ? 4 : 2) === 0) {
        const t = el("text", { x: m.l + i * bw + bw / 2, y: H - 7, "text-anchor": "middle" }, svg);
        t.textContent = fmt.h2(d.hour);
      }
    });
    const pk = el("text", { x: W - 2, y: H - 7, "text-anchor": "end", class: "axis-title" }, svg);
    pk.textContent = "PKT";
    container.appendChild(tip);
  };
  observe(container, draw);
}

/** Small forecast sparkline with its 80% band. */
export function sparkline(container, { values, lo, hi, evening = [18, 22] }) {
  const draw = () => {
    const W = Math.max(container.clientWidth, 160), H = 64, p = 3;
    const mx = Math.max(...hi), mn = Math.min(...lo);
    const x = (h) => p + (h / 23) * (W - 2 * p), y = (v) => p + (1 - (v - mn) / (mx - mn || 1)) * (H - 2 * p);
    container.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "presentation" }, container);
    el("rect", { x: x(evening[0] - 0.5), y: 0, width: x(evening[1] + 0.5) - x(evening[0] - 0.5), height: H, fill: C.eve, opacity: 0.7 }, svg);
    el("path", { d: monotone(hi.map((v, h) => [x(h), y(v)])) + monotone(lo.map((v, h) => [x(h), y(v)]).reverse(), false) + "Z", fill: C.band }, svg);
    el("path", { d: monotone(values.map((v, h) => [x(h), y(v)])), fill: "none", stroke: C.blue, "stroke-width": 2 }, svg);
  };
  observe(container, draw);
}
