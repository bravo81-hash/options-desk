/* VIX conditions panel — shared by the desk (Today's pick) and the Market page. Self-contained helpers. */
"use strict";
(() => {
const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const okv = (v) => v != null && isFinite(v);
const f = (v, d = 1) => okv(v) ? Number(v).toFixed(d) : "–";
const sg = (v, d = 1) => okv(v) ? (v > 0 ? "+" : "") + Number(v).toFixed(d) : "–";
const KIND = {sitout: ["Sit out", "var(--down)"], caution: ["Caution", "var(--warn)"], take: ["Opportunity", "var(--up)"]};
const SIZE = {"Full size": "var(--up)", "Reduce about a quarter": "var(--accent)", "Half size": "var(--warn)", "Stand aside": "var(--down)"};

function statLine(s, base) {
  if (!s) return `<span class="muted">not enough history</span>`;
  const worse = base && s.dd5 > base.dd5 * 1.3, better = base && s.dd5 < base.dd5 * 0.8;
  return `next 21 days: SPX <b>${sg(s.ret21, 1)}%</b>, up ${Math.round(s.up21)}% · a 5% drop followed <b style="color:${worse ? "var(--down)" : better ? "var(--up)" : "inherit"}">${Math.round(s.dd5)}%</b> of the time (normally ${Math.round(base ? base.dd5 : 0)}%) · VIX ${sg(s.vix10, 1)} pts in 10 days${okv(s.rut21) ? ` · RUT ${sg(s.rut21, 1)}%` : ""} · <span class="muted">${s.n} cases since ${s.since.slice(0, 4)}</span>`;
}
function render(el, V, compact) {
  const R = V.readings, base = V.base;
  const chip = (lab, val, warn) => `<span class="vcr ${warn ? "w" : ""}"><span>${lab}</span><b>${val}</b></span>`;
  const readings = [
    chip("VIX", f(R.vix, 2), R.vix >= 25), chip("VIX/VIX3M · " + (window.ivtsBand ? ivtsBand(R.ivts).label : ""), f(R.ivts, 3), R.ivts >= 0.9), chip("VIX − RV20", sg(R.vrp, 1), R.vrp < 0),
    chip("VVIX", f(R.vvix, 0), R.vvix >= 110), chip("VIX9D/VIX", f(R.r9, 2), R.r9 >= 1), chip("RVX − VIX", sg(R.rvx_spread, 1), R.rvx_spread <= 3),
    chip("Long-term trend (200d)", sg(R.vs200, 1) + "%", R.vs200 < 0), chip("SPX today", sg(R.spx_r, 2) + "%", R.spx_r <= -1), chip("HYG today", sg(R.hyg_r, 2) + "%", R.hyg_r <= -1),
  ].join("");
  const active = V.conditions.filter((c) => c.active);
  const order = {sitout: 0, caution: 1, take: 2};
  active.sort((a, b) => order[a.kind] - order[b.kind]);
  const card = (c) => `<div class="vcc" style="border-left-color:${KIND[c.kind][1]}"><div><span class="vck" style="color:${KIND[c.kind][1]}">${KIND[c.kind][0]}</span> <b>${e(c.label)}</b></div>
    <div>${e(c.advice)}</div><div class="small">${statLine(c.stats, base)}</div></div>`;
  const B = V.bucket.stats;
  const bucket = `<div class="vcc" style="border-left-color:var(--line)"><div><span class="vck">VIX level</span> <b>VIX ${e(V.bucket.range)}</b> — the risk band you are in</div><div class="small">${statLine(B, base)}</div></div>`;
  const prefer = V.prefer ? `<div class="small">Index: <b>${V.prefer}</b> has the better premium right now (RVX − VIX ${sg(R.rvx_spread, 1)}).</div>` : "";
  const timing = V.timing.length ? `<div class="small muted">${V.timing.map((t) => e(t)).join("<br>")}</div>` : "";
  const all = `<details><summary class="small muted">All ${V.conditions.length} conditions and their history</summary><div class="tbl"><table><thead><tr><th>Condition</th><th>Type</th><th class="n">Now</th><th class="n">Cases</th><th class="n">SPX 21d</th><th class="n">Up</th><th class="n">5% drop</th><th class="n">VIX 10d</th><th class="n">RUT 21d</th></tr></thead><tbody>${
    V.conditions.map((c) => { const s = c.stats || {}; return `<tr><td class="small">${e(c.label)}</td><td class="small" style="color:${KIND[c.kind][1]}">${KIND[c.kind][0]}</td><td class="n">${c.active ? "<b>●</b>" : ""}</td><td class="n">${s.n ?? "–"}</td><td class="n">${sg(s.ret21, 2)}%</td><td class="n">${okv(s.up21) ? Math.round(s.up21) + "%" : "–"}</td><td class="n">${okv(s.dd5) ? Math.round(s.dd5) + "%" : "–"}</td><td class="n">${sg(s.vix10, 1)}</td><td class="n">${sg(s.rut21, 2)}%</td></tr>`; }).join("")}
    <tr><td class="small"><b>Any day (baseline)</b></td><td></td><td></td><td class="n">${base.n}</td><td class="n">${sg(base.ret21, 2)}%</td><td class="n">${Math.round(base.up21)}%</td><td class="n">${Math.round(base.dd5)}%</td><td class="n">${sg(base.vix10, 1)}</td><td class="n">${sg(base.rut21, 2)}%</td></tr></tbody></table></div>
    <p class="note">History: SPX and VIX since 1990 (VIX3M from 2009, VIX9D from 2011, VVIX from 2006, RVX from 2009, HYG total return from 2007). Overlapping windows from one market history; one-off events are counted once per 5 sessions. Use it to adjust size and timing, not as a signal on its own.</p></details>`;
  const pts = [V.bucket.stats && V.bucket.stats.dd5].concat(active.map((c) => c.stats && c.stats.dd5)).filter(okv), worst = pts.length ? Math.max(...pts) : null;
  el.innerHTML = `<div class="vchead"><div><span class="lbl">VIX inputs on their own</span><span class="vcsize">${okv(worst) ? Math.round(worst) + "%" : "–"}</span><span class="small muted">chance of a 5% drop within 21 sessions (normally ${Math.round(base.dd5)}%) · the size call is the Trade readiness bar at the top · data ${e(R.date)}</span></div><div class="vcrs">${readings}</div></div>
    <div class="vclist">${active.length ? active.map(card).join("") : `<div class="vcc" style="border-left-color:var(--up)"><b>No special VIX condition is active.</b> <span class="muted">Normal behaviour for this VIX level applies.</span></div>`}${bucket}</div>
    ${prefer}${timing}${compact ? "" : all}`;
}
async function loadVixCond(el, compact) {
  if (!el) return;
  el.innerHTML = `<div class="state">Reading VIX conditions…</div>`;
  try {
    const V = await (await fetch("/api/vixcond")).json();
    if (V.error) { el.innerHTML = `<div class="state err">${e(V.error)}</div>`; return; }
    render(el, V, compact);
  } catch (err) { el.innerHTML = `<div class="state err">${e(err.message || err)}</div>`; }
}
window.loadVixCond = loadVixCond;
})();
