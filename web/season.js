/* Seasonality viewer for SPX, NDX, RUT, Dow. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
let D = null;
const U = () => D && D.unit === "pts";  // VIX: changes in points, rising = bad (red)
const pct = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}${U() ? "" : "%"}` : "–";
const lvl = (v) => ok(v) ? v.toFixed(1) : "–";
const cls = (v) => !ok(v) ? "" : (U() ? -v : v) > 0 ? "pos" : (U() ? -v : v) < 0 ? "neg" : "";
const heat = (v, full) => { if (!ok(v)) return ""; const g = U() ? -v : v; return `background:color-mix(in srgb, var(${g >= 0 ? "--up" : "--down"}) ${Math.round(Math.min(Math.abs(v) / full, 1) * 50)}%, transparent)`; };

function pathChart(el) {
  const P = D.path, n = P.avg.length, ti = D.today_i;
  mount(el, (W) => {
    const H = 300, mL = 44, mR = 70, mT = 10, mB = 24, pw = W - mL - mR, ph = H - mT - mB;
    const all = P.avg.concat(P.median, P.cur).filter(ok);
    let lo = U() ? Math.min(...all) : Math.min(0, ...all), hi = U() ? Math.max(...all) : Math.max(0, ...all); const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    const X = (i) => mL + i * pw / (n - 1), Y = (v) => mT + ph - (v - lo) * ph / (hi - lo);
    const line = (a) => { let d = ""; a.forEach((v, i) => { if (ok(v)) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); }); return d; };
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="seasonal path">`;
    niceTicks(lo, hi, 5).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="${v === 0 ? "var(--faint)" : "var(--grid)"}"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${v}${U() ? "" : "%"}</text>`; });
    D.month_ticks.forEach((m) => { s += `<line x1="${X(m.i).toFixed(1)}" x2="${X(m.i).toFixed(1)}" y1="${mT}" y2="${mT + ph}" stroke="var(--grid)" stroke-dasharray="2 4"/><text x="${(X(m.i) + 3).toFixed(1)}" y="${H - 6}">${m.label}</text>`; });
    if (ti >= 0 && ti < n) s += `<rect x="${X(ti).toFixed(1)}" y="${mT}" width="${(X(n - 1) - X(ti)).toFixed(1)}" height="${ph}" fill="var(--s1)" opacity=".05"/><line x1="${X(ti).toFixed(1)}" x2="${X(ti).toFixed(1)}" y1="${mT}" y2="${mT + ph}" stroke="var(--accent)" stroke-dasharray="3 3"/>`;
    s += `<path d="${line(P.median)}" fill="none" stroke="var(--s1)" stroke-width="1.2" stroke-dasharray="4 3" opacity=".8"/>`;
    s += `<path d="${line(P.avg)}" fill="none" stroke="var(--s1)" stroke-width="2.2"/>`;
    s += `<path d="${line(P.cur)}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>`;
    const show = (v) => U() ? lvl(v) : pct(v);
    const lab = (a, col, txt) => { const i = a.length - 1 - [...a].reverse().findIndex(ok); if (i < 0 || i >= a.length) return ""; return `<circle cx="${X(i).toFixed(1)}" cy="${Y(a[i]).toFixed(1)}" r="3.5" fill="${col}"/><text class="lab" x="${(X(i) + 6).toFixed(1)}" y="${(Y(a[i]) + 4).toFixed(1)}">${txt} ${show(a[i])}</text>`; };
    s += lab(P.cur, "var(--accent)", D.cur) + `<text class="lab" x="${(mL + pw + 6).toFixed(1)}" y="${(Y(P.avg[n - 1] ?? P.avg.filter(ok).pop()) + 4).toFixed(1)}">avg ${show(P.avg.filter(ok).pop())}</text>`;
    s += `<line class="xh" x1="0" x2="0" y1="${mT}" y2="${mT + ph}" stroke="var(--muted)" visibility="hidden"/><rect class="hit" x="${mL}" y="${mT}" width="${pw}" height="${ph}" fill="transparent"/></svg>`;
    el.innerHTML = s;
    const svg = el.firstChild, xh = svg.querySelector(".xh"), hit = svg.querySelector(".hit");
    const mon = (i) => { let m = D.month_ticks[0].label; D.month_ticks.forEach((t) => { if (i >= t.i) m = t.label; }); return m; };
    hit.addEventListener("pointermove", (ev) => { const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.round((ev.clientX - r.left - mL) / pw * (n - 1))));
      xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("visibility", "visible");
      showTip(`<div>trading day ${i + 1} · ${mon(i)}</div><div><span class="sw" style="background:var(--s1)"></span>average <b>${show(P.avg[i])}</b></div><div><span class="sw" style="background:var(--s1)"></span>median <b>${show(P.median[i])}</b></div><div><span class="sw" style="background:var(--accent)"></span>${D.cur} <b>${show(P.cur[i])}</b></div>`, ev.clientX, ev.clientY); });
    hit.addEventListener("pointerleave", () => { xh.setAttribute("visibility", "hidden"); hideTip(); });
  });
  $("sePathLegend").innerHTML = legend([[`average of ${D.n_years} years (${D.first}–${D.last})`, "var(--s1)"], ["median", "var(--s1)"], [`${D.cur} so far`, "var(--accent)"], ["today", "var(--accent)"]]);
}
function bars(rows, key, full, label, extra) {
  const mx = Math.max(full, ...rows.map((r) => Math.abs(r[key] || 0)));
  return rows.map((r) => { const v = r[key], w = ok(v) ? 50 * Math.abs(v) / mx : 0;
    return `<div class="rsrow" style="grid-template-columns:3.6em minmax(0,1fr) 11em"><span>${esc(r[label])}</span>
      <span class="rstrack"><i style="${v >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`};background:${v >= 0 ? "var(--up)" : "var(--down)"}"></i><em></em></span>
      <span class="mono small">${extra(r)}</span></div>`; }).join("");
}
function render() {
  const R = D.rest || {};
  const tile = (l, b, sub, k = "") => `<div><span class="lbl">${l}</span><span class="big ${k}">${b}</span><span class="small muted">${sub}</span></div>`;
  const f21 = D.forward.find((f) => f.h === 21) || {};
  const curM = D.months.find((m) => m.m === new Date(D.today + "T12:00:00Z").toLocaleString("en", {month: "short", timeZone: "UTC"})) || {};
  if (U()) {
    const cyc = D.cycle.find((c) => c.now) || {};
    $("seStrip").innerHTML =
      tile("VIX now", lvl(R.ytd), `seasonal average for this date ${lvl(R.seasonal_to_date)}`, R.ytd > R.seasonal_to_date ? "wrn" : "") +
      tile("Rest of the year, seasonally", `${pct(R.seasonal_rest)} pts`, `median ${pct(R.rest_median)} · VIX higher by year end in ${Math.round(R.rest_up || 0)}% of years`, cls(R.seasonal_rest)) +
      tile("Next 21 trading days", `${pct(f21.mean)} pts`, `VIX up in ${Math.round(f21.up || 0)}% of years · biggest rise ${pct(f21.best)} pts`, cls(f21.mean)) +
      tile(`${curM.m || "This month"} on average`, `${pct(curM.mean)} pts`, `VIX up in ${Math.round(curM.up || 0)}% of years · biggest ${pct(curM.best)} pts`, cls(curM.mean)) +
      tile("Presidential cycle", D.cycle_now, `average VIX in ${D.cycle_now} years ${lvl(cyc.mean)}`);
  } else
  $("seStrip").innerHTML =
    tile(`${D.name} ${D.cur} to date`, pct(R.ytd), `seasonal average by now ${pct(R.seasonal_to_date)}`, cls(R.ytd)) +
    tile("Rest of the year, seasonally", pct(R.seasonal_rest), `median ${pct(R.rest_median)} · up in ${Math.round(R.rest_up || 0)}% of years`, cls(R.seasonal_rest)) +
    tile("Next 21 trading days", pct(f21.mean), `up in ${Math.round(f21.up || 0)}% of years · worst ${pct(f21.worst)}`, cls(f21.mean)) +
    tile(`${curM.m || "This month"} on average`, pct(curM.mean), `up in ${Math.round(curM.up || 0)}% · realised vol ${ok(curM.rv) ? curM.rv.toFixed(1) : "–"}%`, cls(curM.mean)) +
    tile("Presidential cycle", D.cycle_now, `${D.cur} · ${(D.cycle.find((c) => c.now) || {}).mean != null ? `avg year ${pct(D.cycle.find((c) => c.now).mean)}` : ""}`);
  $("seMeta").textContent = `${D.n_years} years (${D.first}–${D.last}${$("seCycle").value === "same" ? `, ${D.cycle_now} years only` : ""}) · history from ${D.history_from} · data to ${D.today}`;
  pathChart($("sePath"));
  $("seFwdNote").textContent = `same calendar date in each past year (${D.today.slice(5)})`;
  const fwdChart = () => rangeChart($("seFwdChart"), {label: "range of outcomes by holding period", h: 160, unit: U() ? "" : "%", extColor: "var(--down)",
    items: D.forward.map((f) => ({label: `${f.h}d`, lo: f.p10, hi: f.p90, mid: f.mean, ext: U() ? f.best : f.worst,
      title: `next ${f.h} sessions · middle 80% of years ${pct(f.p10, 1)} to ${pct(f.p90, 1)} · mean ${pct(f.mean, 2)} · ${U() ? "biggest rise" : "worst"} ${pct(U() ? f.best : f.worst, 1)} · ${Math.round(f.up)}% up`}))});
  if (U()) {
    $("seFwd").innerHTML = `<div class="chart" id="seFwdChart"></div><div class="tbl"><table><thead><tr><th>Next</th><th class="n">Mean</th><th class="n">Median</th><th class="n">VIX up</th><th class="n" title="1 in 10 years VIX rose more than this">90th pct</th><th class="n">Biggest rise</th><th class="n">Biggest fall</th></tr></thead><tbody>${
      D.forward.map((f) => `<tr><td>${f.h} days</td><td class="n ${cls(f.mean)}">${pct(f.mean, 2)}</td><td class="n">${pct(f.median, 2)}</td><td class="n">${Math.round(f.up)}%</td><td class="n neg">${pct(f.p90, 1)}</td><td class="n neg">${pct(f.best, 1)}</td><td class="n pos">${pct(f.worst, 1)}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Changes in VIX points from this calendar date in past years. The 90th-percentile and biggest-rise columns are the vol-spike risk for short-vega trades (A14, short premium); calendars are long vega and gain from rises.</p>`;
  } else
  $("seFwd").innerHTML = `<div class="chart" id="seFwdChart"></div><div class="tbl"><table><thead><tr><th>Next</th><th class="n">Mean</th><th class="n">Median</th><th class="n">Up</th><th class="n" title="1 in 10 years was worse than this">10th pct</th><th class="n">Worst</th><th class="n" title="average realised volatility over the window, vs ${D.rv_all.toFixed(1)}% across the whole year">Realised vol</th></tr></thead><tbody>${
    D.forward.map((f) => `<tr><td>${f.h} days</td><td class="n ${cls(f.mean)}">${pct(f.mean, 2)}</td><td class="n">${pct(f.median, 2)}</td><td class="n">${Math.round(f.up)}%</td><td class="n neg">${pct(f.p10, 1)}</td><td class="n neg">${pct(f.worst, 1)}</td><td class="n ${ok(f.rv) && f.rv > D.rv_all * 1.1 ? "wrn" : ""}">${ok(f.rv) ? f.rv.toFixed(1) + "%" : "–"}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">Chart: the box is the middle 80% of past years (10th to 90th percentile), the dot the mean, the red tick the worst year. For option sellers: the 10th-percentile and worst rows are the seasonal stress for that holding period; realised vol above the yearly average (${D.rv_all.toFixed(1)}%, highlighted) means the window has historically moved more than usual — compare with today's implied vol on the Expected moves tab.</p>`;
  fwdChart();
  const vx = Object.fromEntries((D.vix || []).map((v) => [v.m, v]));
  $("seMonths").innerHTML = U()
    ? bars(D.months, "mean", 1, "m", (r) => `${pct(r.mean, 2)} pts · up ${Math.round(r.up)}% · avg level ${vx[r.m] ? lvl(vx[r.m].level) : "–"}`) + `<p class="note">Average change in VIX through the month (points), how often it rose, and the average VIX level in that month.</p>`
    : bars(D.months, "mean", 1, "m", (r) => `${pct(r.mean, 2)} · ${Math.round(r.up)}% up · RV ${ok(r.rv) ? r.rv.toFixed(0) : "–"}${vx[r.m] ? ` · VIX ${vx[r.m].chg >= 0 ? "+" : ""}${vx[r.m].chg.toFixed(1)}` : ""}`) +
    `<p class="note">RV = average realised volatility in that month; VIX = average change in VIX points through the month (since 1990).</p>`;
  const years = Object.keys(D.table).map(Number).sort((a, b) => b - a);
  $("seTable").innerHTML = `<table><thead><tr><th>Year</th>${D.months.map((m) => `<th class="n">${m.m}</th>`).join("")}<th class="n">Year</th></tr></thead><tbody>${
    years.map((y) => { const row = D.table[y], tot = U() ? row.filter(ok).reduce((a, v) => a + v, 0) : row.filter(ok).reduce((a, v) => a * (1 + v / 100), 1) * 100 - 100;
      return `<tr${y === D.cur ? ' class="held"' : ""}><td>${y}</td>${row.map((v) => `<td class="n" style="${heat(v, 6)}">${ok(v) ? v.toFixed(1) : ""}</td>`).join("")}<td class="n"><b class="${cls(tot)}">${pct(tot, 1)}</b></td></tr>`; }).join("")}
    <tr><td><b>Mean</b></td>${D.months.map((m) => `<td class="n" style="${heat(m.mean, 2)}"><b>${m.mean.toFixed(1)}</b></td>`).join("")}<td></td></tr>
    <tr><td><b>% up</b></td>${D.months.map((m) => `<td class="n">${Math.round(m.up)}</td>`).join("")}<td></td></tr></tbody></table>`;
  $("seTom").innerHTML = bars(D.tom, "mean", 0.05, "d", (r) => `${pct(r.mean, 3)} · ${Math.round(r.up)}% up`) +
    (() => { const win = D.tom.filter((t) => ["−2", "last", "+1", "+2", "+3"].includes(t.d)), m = win.reduce((a, t) => a + t.mean, 0) / win.length;
      return `<p class="note">Average day ${pct(D.avg_day, 3)}. The turn-of-month window (2 days before the month end to the 3rd day after) averaged ${pct(m, 3)} a day — ${m > D.avg_day * 1.5 ? "stronger than a normal day in these years" : "no real edge over a normal day in these years"}.</p>`; })();
  $("seWd").innerHTML = `<h3>By weekday</h3>` + bars(D.weekday, "mean", 0.05, "d", (r) => `${pct(r.mean, 3)} · ${Math.round(r.up)}% up`);
  $("seCyc").innerHTML = `<h3>Presidential cycle · ${U() ? "average VIX level that year" : "average calendar-year return"}</h3>${U() ? "" : bars(D.cycle, "mean", 5, "k", (r) => `${pct(r.mean)} · ${ok(r.up) ? Math.round(r.up) + "% up" : ""}${r.now ? " ← now" : ""}`)}<div class="tbl"><table><thead><tr><th>Year type</th><th class="n">${U() ? "Avg VIX" : "Avg year"}</th><th class="n">Up</th><th class="n">Years</th></tr></thead><tbody>${
    D.cycle.map((c) => `<tr${c.now ? ' class="held"' : ""}><td>${esc(c.k)}${c.now ? ` <span class="chip">${D.cur}</span>` : ""}</td><td class="n ${U() ? "" : cls(c.mean)}">${U() ? lvl(c.mean) : pct(c.mean)}</td><td class="n">${U() ? "" : ok(c.up) ? Math.round(c.up) + "%" : "–"}</td><td class="n">${c.n}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">The cycle year you are in is highlighted. Few years per type, so treat it as context, not a signal. Pick "same presidential-cycle year as now" above to see the path of ${D.cycle_now} years only.</p>`;
}
async function load() {
  $("seMeta").textContent = "loading history…";
  try {
    const q = new URLSearchParams({sym: $("seSym").value, years: $("seYears").value, cycle: $("seCycle").value});
    D = await api("/api/season?" + q);
    if (D.error) { $("seStrip").innerHTML = `<div class="state err">${esc(D.error)}</div>`; return; }
    render();
  } catch (e) { $("seStrip").innerHTML = `<div class="state err">${esc(e.message || e)}</div>`; }
}
["seSym", "seYears", "seCycle"].forEach((id) => $(id).addEventListener("change", load));
$("seForm").addEventListener("submit", (e) => { e.preventDefault(); load(); });
window.loadSeason = load;
})();
