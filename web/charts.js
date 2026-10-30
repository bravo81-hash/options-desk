/* Small SVG chart kit: measured width, solid hairline grid, hover tooltips. */
"use strict";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ok = (v) => v != null && isFinite(v);
const fmt = (v, d = 2) => ok(v) ? Number(v).toFixed(d) : "–";
const sgn = (v, d = 2) => ok(v) ? (v > 0 ? "+" : "") + Number(v).toFixed(d) : "–";
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const shortDate = (d) => { const [y, m, dd] = String(d).split("-"); return dd ? `${MON[+m - 1]} ${+dd}` : d; };
const monYear = (d) => { const [y, m] = String(d).split("-"); return `${MON[+m - 1]} ${y.slice(2)}`; };

const tipEl = () => document.getElementById("tip");
function showTip(html, x, y) { const t = tipEl(); t.innerHTML = html; t.hidden = false; const r = t.getBoundingClientRect(); let L = x + 14, T = y + 14; if (L + r.width > innerWidth - 8) L = x - r.width - 14; if (T + r.height > innerHeight - 8) T = y - r.height - 14; t.style.left = L + "px"; t.style.top = T + "px"; }
function hideTip() { tipEl().hidden = true; }
function bindTip(el, sel, fn) { el.querySelectorAll(sel).forEach((n) => { const h = (ev) => showTip(fn(n), ev.clientX, ev.clientY); n.addEventListener("pointermove", h); n.addEventListener("pointerdown", h); n.addEventListener("pointerleave", hideTip); }); }

function niceTicks(lo, hi, n = 4) {
  const span = hi - lo || 1, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw)), st = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const out = []; for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) out.push(+v.toFixed(10)); return out;
}
const ro = new ResizeObserver((es) => es.forEach((e) => { const el = e.target; if (el._draw && Math.abs(el.clientWidth - (el._w || 0)) > 4) el._draw(); }));
function mount(el, draw) { el._draw = () => { el._w = el.clientWidth; draw(el.clientWidth || 600); }; if (!el._obs) { el._obs = 1; ro.observe(el); } el._draw(); }
const legend = (items) => `<div class="legend">${items.map(([n, c, box]) => `<span><i class="${box ? "box" : ""}" style="background:${c}"></i>${esc(n)}</span>`).join("")}</div>`;

/* Time series on a shared date axis. series: [{name, data:[{d,v}], color, width, dash, short}] */
function lineChart(el, cfg) {
  const dates = [...new Set(cfg.series.flatMap((s) => s.data.map((p) => p.d)))].sort();
  const n = dates.length; if (!n) { el.innerHTML = `<div class="state">No history yet.</div>`; return; }
  const ix = new Map(dates.map((d, i) => [d, i]));
  mount(el, (W) => {
    const H = cfg.h || 200, mL = 44, mR = cfg.mR ?? (cfg.endLabels === false ? 12 : 70), mT = 8, mB = 22, pw = W - mL - mR, ph = H - mT - mB;
    const all = cfg.series.flatMap((s) => s.data.map((p) => p.v)).filter(ok).concat((cfg.refs || []).map((r) => r.y));
    let lo = cfg.yMin ?? Math.min(...all), hi = cfg.yMax ?? Math.max(...all); if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.06; if (cfg.yMin == null) lo -= pad; if (cfg.yMax == null) hi += pad;
    const X = (i) => mL + (n <= 1 ? pw / 2 : i * pw / (n - 1)), Y = (v) => mT + ph - (v - lo) * ph / (hi - lo);
    const fy = cfg.fy || ((v) => Math.abs(hi - lo) < 3 ? v.toFixed(2) : (+v.toFixed(1)).toString());
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "chart")}">`;
    niceTicks(lo, hi, cfg.ticks || 4).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--grid)"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${fy(v)}</text>`; });
    const xt = Math.max(2, Math.min(6, n, Math.floor(pw / 80)));
    const xf = n > 200 ? monYear : shortDate;
    for (let k = 0; k < xt; k++) { const i = Math.round(k * (n - 1) / Math.max(xt - 1, 1)); s += `<text x="${X(i).toFixed(1)}" y="${H - 6}" text-anchor="${k === 0 ? "start" : k === xt - 1 ? "end" : "middle"}">${xf(dates[i])}</text>`; }
    (cfg.refs || []).forEach((r) => { s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(r.y).toFixed(1)}" y2="${Y(r.y).toFixed(1)}" stroke="${r.color || "var(--faint)"}" stroke-dasharray="4 3"/>${r.label ? `<text x="${mL + pw + 4}" y="${(Y(r.y) + 3.5).toFixed(1)}">${esc(r.label)}</text>` : ""}`; });
    cfg.series.forEach((se) => {
      let d = "", pen = false;
      se.data.forEach((p) => { if (!ok(p.v)) { pen = false; return; } d += (pen ? "L" : "M") + X(ix.get(p.d)).toFixed(1) + " " + Y(p.v).toFixed(1); pen = true; });
      if (se.dots) se.data.forEach((p) => { if (ok(p.v)) s += `<circle cx="${X(ix.get(p.d)).toFixed(1)}" cy="${Y(p.v).toFixed(1)}" r="3" fill="${se.color}"/>`; });
      s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="${se.width || 1.8}" ${se.dash ? `stroke-dasharray="${se.dash}"` : ""} stroke-linejoin="round"/>`;
    });
    if (cfg.endLabels !== false) {
      const labs = cfg.series.map((se) => { const p = [...se.data].reverse().find((q) => ok(q.v)); return p ? {se, p, y: Y(p.v)} : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
      for (let k = 1; k < labs.length; k++) if (labs[k].y - labs[k - 1].y < 13) labs[k].y = labs[k - 1].y + 13;
      labs.forEach((o) => { s += `<circle cx="${X(ix.get(o.p.d)).toFixed(1)}" cy="${Y(o.p.v).toFixed(1)}" r="3.5" fill="${o.se.color}" stroke="var(--panel)" stroke-width="2"/><text class="lab" x="${mL + pw + 8}" y="${(o.y + 4).toFixed(1)}">${esc(o.se.short || "")} ${(cfg.ft || fy)(o.p.v)}</text>`; });
    }
    (cfg.marks || []).forEach((m) => { if (ix.has(m.d)) s += `<circle cx="${X(ix.get(m.d)).toFixed(1)}" cy="${Y(m.v).toFixed(1)}" r="5" fill="${m.color || "var(--accent)"}" stroke="var(--panel)" stroke-width="2"/>`; });
    s += `<line class="xh" x1="0" x2="0" y1="${mT}" y2="${mT + ph}" stroke="var(--muted)" visibility="hidden"/><rect class="hit" x="${mL}" y="${mT}" width="${pw}" height="${ph}" fill="transparent"/></svg>`;
    el.innerHTML = s;
    const svg = el.firstChild, xh = svg.querySelector(".xh"), hit = svg.querySelector(".hit");
    const maps = cfg.series.map((se) => new Map(se.data.map((p) => [p.d, p.v])));
    const mv = (ev) => { const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.round((ev.clientX - r.left - mL) / pw * (n - 1))));
      xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("visibility", "visible");
      showTip(`<div>${esc(dates[i])}</div>` + cfg.series.map((se, k) => `<div><span class="sw" style="background:${se.color}"></span>${esc(se.name)} <b>${ok(maps[k].get(dates[i])) ? (cfg.ft || fy)(maps[k].get(dates[i])) : "–"}</b></div>`).join(""), ev.clientX, ev.clientY); };
    hit.addEventListener("pointermove", mv); hit.addEventListener("pointerdown", mv); hit.addEventListener("pointerleave", () => { xh.setAttribute("visibility", "hidden"); hideTip(); });
  });
}

/* ---------- small inline SVGs (strings, no mounting) for tables ---------- */
/* Bullet: where a value sits on a scale with marked levels. marks: [{v, color, label}] */
function bulletSvg(v, cfg) {
  const w = cfg.w || 150, h = cfg.h || 22, lo = Math.min(cfg.lo, ok(v) ? v : cfg.lo), hi = Math.max(cfg.hi, ok(v) ? v : cfg.hi);
  const X = (x) => 4 + (x - lo) * (w - 8) / ((hi - lo) || 1), y = h / 2;
  let s = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(cfg.label || "position on scale")}"><title>${esc(cfg.label || "")}</title>`;
  (cfg.zones || []).forEach((z) => { s += `<rect x="${X(Math.max(z.from, lo)).toFixed(1)}" y="${y - 4}" width="${Math.max(0, X(Math.min(z.to, hi)) - X(Math.max(z.from, lo))).toFixed(1)}" height="8" fill="color-mix(in srgb, ${z.color} 22%, transparent)"/>`; });
  s += `<line x1="4" x2="${w - 4}" y1="${y}" y2="${y}" stroke="var(--line)"/>`;
  (cfg.marks || []).forEach((m) => { if (ok(m.v)) s += `<line x1="${X(m.v).toFixed(1)}" x2="${X(m.v).toFixed(1)}" y1="${y - 7}" y2="${y + 7}" stroke="${m.color}" stroke-width="${m.width || 2}"${m.dash ? ` stroke-dasharray="2 2"` : ""}><title>${esc(m.label || "")}</title></line>`; });
  if (ok(v)) s += `<circle cx="${X(v).toFixed(1)}" cy="${y}" r="5" fill="${cfg.color || (v >= 0 ? "var(--up)" : "var(--down)")}" stroke="var(--panel)" stroke-width="1.5"/>`;
  return s + `</svg>`;
}
/* Mini bars around zero, one per bucket; the selected one drawn solid. items: [{label, v, n, sel}] */
function sparkBars(items, cfg = {}) {
  const w = cfg.w || 84, h = cfg.h || 26, n = items.length, m = Math.max(0.5, ...items.map((i) => Math.abs(i.v || 0))), bw = (w - 2) / Math.max(n, 1), y0 = h / 2;
  let s = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(cfg.label || "results by bucket")}"><line x1="0" x2="${w}" y1="${y0}" y2="${y0}" stroke="var(--line)"/>`;
  items.forEach((it, k) => { if (!ok(it.v)) return; const bh = Math.abs(it.v) / m * (h / 2 - 1), x = 1 + k * bw + bw * 0.15, col = it.v >= 0 ? "var(--up)" : "var(--down)";
    s += `<rect x="${x.toFixed(1)}" y="${(it.v >= 0 ? y0 - bh : y0).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${Math.max(bh, 0.8).toFixed(1)}" fill="${col}" opacity="${it.sel ? 1 : 0.3}"${it.sel ? ` stroke="var(--ink)" stroke-width="1"` : ""}><title>${esc(`${it.label}: ${it.v > 0 ? "+" : ""}${it.v.toFixed(1)}%${ok(it.n) ? ` (${it.n})` : ""}${it.sel ? " ← today" : ""}`)}</title></rect>`; });
  return s + `</svg>`;
}
/* Size meter: four segments, quarter to full. */
function sizeMeter(size) {
  const k = ["Stand aside", "Quarter size", "Half size", "Three-quarter size", "Full size"].indexOf(size), col = k <= 0 ? "var(--down)" : k === 4 ? "var(--up)" : "var(--accent)";
  return `<svg width="76" height="10" viewBox="0 0 76 10" role="img" aria-label="${esc(size)}">${[1, 2, 3, 4].map((i) => `<rect x="${(i - 1) * 19}" y="1" width="17" height="8" rx="2" fill="${i <= k ? col : "var(--soft)"}"/>`).join("")}</svg>`;
}

/* Horizontal bar around zero for a table cell (v and max in the same unit). */
function hBarSvg(v, max, cfg = {}) {
  const w = cfg.w || 90, h = cfg.h || 10, m = Math.max(Math.abs(max) || 1, 1e-9), x0 = cfg.zeroLeft ? 1 : w / 2;
  const len = ok(v) ? Math.min(Math.abs(v) / m, 1) * (cfg.zeroLeft ? w - 2 : w / 2 - 1) : 0;
  const col = cfg.color || (v >= 0 ? "var(--up)" : "var(--down)");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(cfg.label || "bar")}" style="vertical-align:middle"><line x1="${x0}" x2="${x0}" y1="0" y2="${h}" stroke="var(--line)"/>${ok(v) ? `<rect x="${(v >= 0 || cfg.zeroLeft ? x0 : x0 - len).toFixed(1)}" y="1.5" width="${Math.max(len, 0.8).toFixed(1)}" height="${h - 3}" rx="1.5" fill="${col}"/>` : ""}${ok(cfg.tick) ? `<line x1="${(x0 + Math.min(cfg.tick / m, 1) * (cfg.zeroLeft ? w - 2 : w / 2 - 1)).toFixed(1)}" x2="${(x0 + Math.min(cfg.tick / m, 1) * (cfg.zeroLeft ? w - 2 : w / 2 - 1)).toFixed(1)}" y1="0" y2="${h}" stroke="var(--ink)" stroke-width="1.5"/>` : ""}</svg>`;
}

/* One bar split into proportional segments. parts: [{n, color, label}] */
function segBar(parts, cfg = {}) {
  const w = cfg.w || 120, h = cfg.h || 8, tot = parts.reduce((s, p) => s + (p.n || 0), 0);
  if (!tot) return "";
  let x = 0, s = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(cfg.label || parts.map((p) => `${p.n} ${p.label}`).join(", "))}" style="vertical-align:middle">`;
  parts.forEach((p) => { if (!p.n) return; const pw = p.n / tot * w; s += `<rect x="${(x + 0.5).toFixed(1)}" y="0" width="${Math.max(pw - 1, 0.8).toFixed(1)}" height="${h}" rx="1.5" fill="${p.color}"><title>${p.n} ${esc(p.label)}</title></rect>`; x += pw; });
  return s + `</svg>`;
}

/* Ranges by category: a band from lo to hi (e.g. 10th-90th percentile), a dot at mid, a tick at the extreme.
   items: [{label, lo, hi, mid, ext, title}] */
function rangeChart(el, cfg) {
  mount(el, (W) => {
    const H = cfg.h || 170, mL = 40, mR = 8, mT = 10, mB = 22, pw = W - mL - mR, ph = H - mT - mB, I = cfg.items;
    const vals = I.flatMap((i) => [i.lo, i.hi, i.mid, i.ext]).filter(ok);
    if (!vals.length) { el.innerHTML = `<div class="state">No data.</div>`; return; }
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals); const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const Y = (v) => mT + ph - (v - lo) * ph / (hi - lo), bw = pw / I.length;
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "ranges")}">`;
    niceTicks(lo, hi, 4).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="${v === 0 ? "var(--line)" : "var(--grid)"}"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${+v.toFixed(1)}${cfg.unit ?? "%"}</text>`; });
    I.forEach((it, k) => { const cx = mL + k * bw + bw / 2, bwid = Math.min(26, bw * 0.45);
      if (ok(it.lo) && ok(it.hi)) s += `<rect class="rc" data-k="${k}" x="${(cx - bwid / 2).toFixed(1)}" y="${Y(it.hi).toFixed(1)}" width="${bwid.toFixed(1)}" height="${Math.max(Y(it.lo) - Y(it.hi), 1).toFixed(1)}" rx="3" fill="color-mix(in srgb, ${cfg.color || "var(--s1)"} 35%, transparent)" stroke="${cfg.color || "var(--s1)"}"/>`;
      if (ok(it.ext)) s += `<line x1="${(cx - bwid / 2).toFixed(1)}" x2="${(cx + bwid / 2).toFixed(1)}" y1="${Y(it.ext).toFixed(1)}" y2="${Y(it.ext).toFixed(1)}" stroke="${cfg.extColor || "var(--down)"}" stroke-width="2"/><line x1="${cx}" x2="${cx}" y1="${Y(ok(it.lo) ? (it.ext < it.lo ? it.lo : it.hi) : 0).toFixed(1)}" y2="${Y(it.ext).toFixed(1)}" stroke="${cfg.extColor || "var(--down)"}" stroke-dasharray="2 2"/>`;
      if (ok(it.mid)) s += `<circle cx="${cx}" cy="${Y(it.mid).toFixed(1)}" r="4" fill="${it.mid >= 0 ? "var(--up)" : "var(--down)"}" stroke="var(--panel)" stroke-width="1.5"/>`;
      s += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${esc(it.label)}</text>`; });
    el.innerHTML = s + `</svg>`;
    bindTip(el, ".rc", (n) => I[+n.dataset.k].title || "");
  });
}

/* Vertical bars by category. items: [{label, v, n, title, hi}] (v in %) */
function barChart(el, cfg) {
  mount(el, (W) => {
    const H = cfg.h || 180, mL = 40, mR = 8, mT = 10, mB = cfg.rotate ? 34 : 24, pw = W - mL - mR, ph = H - mT - mB, I = cfg.items.filter((i) => ok(i.v));
    if (!I.length) { el.innerHTML = `<div class="state">No data.</div>`; return; }
    let lo = Math.min(0, ...I.map((i) => i.v)), hi = Math.max(0, ...I.map((i) => i.v)); const pad = (hi - lo) * 0.08 || 1; lo -= lo < 0 ? pad : 0; hi += pad;
    const Y = (v) => mT + ph - (v - lo) * ph / (hi - lo), bw = pw / cfg.items.length;
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "bar chart")}">`;
    niceTicks(lo, hi, 4).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="${v === 0 ? "var(--line)" : "var(--grid)"}"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${+v.toFixed(1)}${cfg.unit ?? "%"}</text>`; });
    const every = Math.ceil(cfg.items.length / Math.max(1, Math.floor(pw / (cfg.rotate ? 18 : 42))));
    cfg.items.forEach((it, k) => { const x = mL + k * bw;
      if (ok(it.v)) s += `<rect class="bc" data-k="${k}" x="${(x + bw * 0.14).toFixed(1)}" y="${Y(Math.max(it.v, 0)).toFixed(1)}" width="${(bw * 0.72).toFixed(1)}" height="${Math.max(Math.abs(Y(it.v) - Y(0)), 0.8).toFixed(1)}" rx="1.5" fill="${it.color || (it.v >= 0 ? "var(--up)" : "var(--down)")}" opacity="${it.dim ? 0.35 : 0.9}"${it.hi ? ` stroke="var(--ink)" stroke-width="1.5"` : ""}/>`;
      if (k % every === 0) s += `<text x="${(x + bw / 2).toFixed(1)}" y="${H - (cfg.rotate ? 18 : 8)}" text-anchor="middle">${esc(it.label)}</text>`; });
    el.innerHTML = s + `</svg>`;
    bindTip(el, ".bc", (n) => { const it = cfg.items[+n.dataset.k]; return it.title || `${esc(it.label)}: <b>${it.v > 0 ? "+" : ""}${it.v.toFixed(2)}${cfg.unit ?? "%"}</b>${ok(it.n) ? ` · ${it.n} entries` : ""}`; });
  });
}

/* Numeric-x line chart (e.g. vol by DTE). series: [{name, pts:[[x,y]], color}] */
function xyChart(el, cfg) {
  mount(el, (W) => {
    const H = cfg.h || 220, mL = 44, mR = 16, mT = 10, mB = 26, pw = W - mL - mR, ph = H - mT - mB;
    const xs = cfg.series.flatMap((s) => s.pts.map((p) => p[0])), ys = cfg.series.flatMap((s) => s.pts.map((p) => p[1])).filter(ok);
    if (!ys.length) { el.innerHTML = `<div class="state">No data yet.</div>`; return; }
    let x0 = cfg.xMin ?? Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys), hi = Math.max(...ys); const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
    const X = (x) => mL + (x - x0) * pw / ((x1 - x0) || 1), Y = (v) => mT + ph - (v - lo) * ph / (hi - lo);
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "chart")}">`;
    niceTicks(lo, hi, 4).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--grid)"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${v}</text>`; });
    niceTicks(x0, x1, Math.max(2, Math.floor(pw / 70))).forEach((v) => { if (v >= x0 && v <= x1) s += `<text x="${X(v).toFixed(1)}" y="${H - 8}" text-anchor="middle">${v}${cfg.xUnit || ""}</text>`; });
    cfg.series.forEach((se) => { const pts = se.pts.filter((p) => ok(p[1])); s += `<polyline points="${pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ")}" fill="none" stroke="${se.color}" stroke-width="2" ${se.dash ? `stroke-dasharray="${se.dash}"` : ""}/>`;
      pts.forEach((p) => { s += `<circle class="pt" cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="3.5" fill="${se.color}" stroke="var(--panel)" stroke-width="1.5" data-t="${esc(`${se.name}: ${p[2] || p[0] + (cfg.xUnit || "")} → ${fmt(p[1])}`)}"/>`; }); });
    el.innerHTML = s + `</svg>`;
    bindTip(el, ".pt", (n) => esc(n.dataset.t));
  });
}

/* Diverging heatmap. rows/cols labels, cells: Map key `${r}|${c}` -> {v, title} */
function heatmap(el, cfg) {
  mount(el, (W) => {
    const rows = cfg.rows, cols = cfg.cols, mL = 70, mT = 34, cw = Math.max(14, Math.min(46, (W - mL - 8) / cols.length)), ch = Math.max(16, Math.min(26, cw * 0.7));
    const H = mT + rows.length * ch + 8, vals = [...cfg.cells.values()].map((c) => c.v).filter(ok);
    const m = Math.max(...vals.map(Math.abs), 0.01), center = cfg.center ?? 0;
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "heatmap")}">`;
    cols.forEach((c, j) => { if (j % Math.ceil(30 / cw) === 0) s += `<text x="${(mL + j * cw + cw / 2).toFixed(1)}" y="${mT - 8}" text-anchor="middle">${esc(c.label)}</text>`; });
    rows.forEach((r, i) => {
      s += `<text x="${mL - 6}" y="${(mT + i * ch + ch / 2 + 3.5).toFixed(1)}" text-anchor="end">${esc(r.label)}</text>`;
      cols.forEach((c, j) => { const cell = cfg.cells.get(`${r.key}|${c.key}`); if (!cell) return;
        const v = cell.v, a = ok(v) ? Math.min(1, Math.abs(v - center) / m) : 0, col = !ok(v) ? "var(--soft)" : v >= center ? "var(--up)" : "var(--down)";
        s += `<rect class="hc" data-r="${esc(r.key)}" data-c="${esc(c.key)}" x="${(mL + j * cw + 1).toFixed(1)}" y="${(mT + i * ch + 1).toFixed(1)}" width="${(cw - 2).toFixed(1)}" height="${(ch - 2).toFixed(1)}" rx="2" fill="color-mix(in srgb, ${col} ${Math.round(12 + a * 78)}%, var(--panel))" ${cell.sel ? `stroke="var(--ink)" stroke-width="2"` : ""}/>`; });
    });
    el.innerHTML = s + `</svg>`;
    bindTip(el, ".hc", (n) => cfg.cells.get(`${n.dataset.r}|${n.dataset.c}`).title);
    el.querySelectorAll(".hc").forEach((n) => n.addEventListener("click", () => cfg.onClick && cfg.onClick(n.dataset.r, n.dataset.c)));
  });
}

/* Scatter: points [{x, y, color, r, title}] */
function scatter(el, cfg) {
  mount(el, (W) => {
    const H = cfg.h || 260, mL = 54, mR = 16, mT = 10, mB = 30, pw = W - mL - mR, ph = H - mT - mB, P = cfg.points.filter((p) => ok(p.x) && ok(p.y));
    if (!P.length) { el.innerHTML = `<div class="state">No data.</div>`; return; }
    let x0 = Math.min(...P.map((p) => p.x)), x1 = Math.max(...P.map((p) => p.x)), y0 = Math.min(0, ...P.map((p) => p.y)), y1 = Math.max(0, ...P.map((p) => p.y));
    const px = (x1 - x0) * 0.06 || 1, py = (y1 - y0) * 0.08 || 1; x0 -= px; x1 += px; y0 -= py; y1 += py;
    const X = (x) => mL + (x - x0) * pw / (x1 - x0), Y = (v) => mT + ph - (v - y0) * ph / (y1 - y0);
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "scatter")}">`;
    niceTicks(y0, y1, 4).forEach((v) => { if (v >= y0 && v <= y1) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="${v === 0 ? "var(--line)" : "var(--grid)"}"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${Math.abs(v) >= 1000 ? (v / 1000) + "k" : v}</text>`; });
    niceTicks(x0, x1, Math.max(2, Math.floor(pw / 80))).forEach((v) => { if (v >= x0 && v <= x1) s += `<line x1="${X(v).toFixed(1)}" x2="${X(v).toFixed(1)}" y1="${mT}" y2="${mT + ph}" stroke="var(--grid)"/><text x="${X(v).toFixed(1)}" y="${H - 12}" text-anchor="middle">${+v.toFixed(3)}</text>`; });
    if (ok(cfg.vline)) s += `<line x1="${X(cfg.vline).toFixed(1)}" x2="${X(cfg.vline).toFixed(1)}" y1="${mT}" y2="${mT + ph}" stroke="var(--accent)" stroke-dasharray="4 3"/>`;
    s += `<text x="${mL + pw}" y="${H - 1}" text-anchor="end">${esc(cfg.xLabel || "")}</text>`;
    P.forEach((p, k) => { s += `<circle class="sp" data-k="${k}" cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="${p.r || 5}" fill="${p.color}" fill-opacity=".75" stroke="var(--panel)" stroke-width="1.5"/>`; });
    el.innerHTML = s + `</svg>`;
    bindTip(el, ".sp", (n) => P[+n.dataset.k].title);
  });
}
