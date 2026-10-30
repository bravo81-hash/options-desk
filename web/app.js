"use strict";
const $ = (id) => document.getElementById(id);
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`); return r.json(); };
const zcls = (z) => !ok(z) ? "muted" : Math.abs(z) >= 2 ? "neg" : Math.abs(z) >= 1 ? "wrn" : "";
const zTxt = (z) => ok(z) ? `z ${sgn(z, 2)}` : "z –";
const pctTxt = (p) => ok(p) ? `${fmt(p, 0)}th pct` : "";
const errBox = (e) => `<div class="state err">${esc(e.message || e)}</div>`;

/* ---------------- theme: auto (Windows setting) / light / dark, also applied to the Market iframe ---------------- */
const isDark = (t) => t === "auto" ? matchMedia("(prefers-color-scheme: dark)").matches : t === "dark";
function applyTheme(t) {
  const set = (doc) => { if (!doc) return; if (t === "auto") delete doc.documentElement.dataset.theme; else doc.documentElement.dataset.theme = t; };
  set(document);
  try { set($("mdFrame") && $("mdFrame").contentDocument); } catch (e) {}
  const dark = isDark(t);
  $("themeBtn").setAttribute("aria-checked", String(dark));
  $("themeBtn").title = dark ? "Switch to light mode" : "Switch to dark mode";
  document.querySelectorAll(".chart").forEach((c) => c._draw && c._draw());
}
let theme = "auto";  // until the switch is used the desk follows Windows
try { const t = localStorage.getItem("od.theme"); if (t === "light" || t === "dark") theme = t; } catch (e) {}
applyTheme(theme);
$("themeBtn").addEventListener("click", () => { theme = isDark(theme) ? "light" : "dark"; try { localStorage.setItem("od.theme", theme); } catch (e) {} applyTheme(theme); });
$("mdFrame").addEventListener("load", () => applyTheme(theme));

/* ---------------- data freshness (header) ---------------- */
async function loadFresh() {
  try {
    const F = await api("/api/freshness");
    const day = (d) => d ? new Date(d + "T12:00:00Z").toLocaleDateString([], {day: "numeric", month: "short", timeZone: "UTC"}) : "none";
    const stale = F.sources.filter((x) => x.stale);
    $("freshBar").className = "datapill" + (stale.length ? " st" : "");
    $("freshBar").textContent = `Data: ${day(F.last_close)} ${stale.length ? `· ${stale.length} stale` : "✓"}`;
    $("freshList").innerHTML = `<p class="small muted">Latest US close: <b>${day(F.last_close)}</b></p><div class="tbl"><table><thead><tr><th>Source</th><th class="n">Date</th><th>Used by</th></tr></thead><tbody>${F.sources.map((x) =>
      `<tr><td>${esc(x.name)}</td><td class="n ${x.stale ? "wrn" : ""}">${x.name === "ONE export" ? (x.stale ? "stale" : "ok") : day(x.date)}</td><td class="small muted">${esc(x.what)}</td></tr>`).join("")}</tbody></table></div>`;
  } catch (e) { $("freshBar").textContent = "Data"; }
}
loadFresh(); setInterval(loadFresh, 300000);
$("freshBar").addEventListener("click", () => { $("updPanel").hidden = false; });

/* live badges in the sidebar */
window.navBadge = (tab, text, cls = "") => { const b = $("nb-" + tab); if (b) { b.textContent = text; b.className = "nbadge " + cls; } };
$("navBtn").addEventListener("click", (e) => { e.stopPropagation(); $("sideNav").classList.toggle("open"); });
document.addEventListener("click", (e) => { if (!e.target.closest("#sideNav")) $("sideNav").classList.remove("open"); });

/* ---------------- tabs ---------------- */
const loaded = {};
let curTab = null;
function showTab(name) {
  if (name !== curTab) {  // coming to a tab starts on its first sub-tab
    curTab = name; firstSubs($("tab-" + name));
    if (name === "market") try { firstSubs($("mdFrame").contentDocument); } catch (e) {}
  }
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $("sideNav").classList.remove("open");
  document.querySelectorAll(".tab").forEach((t) => { t.hidden = t.id !== "tab-" + name; });
  try { sessionStorage.setItem("od.tab", name); } catch (e) {}
  if (!loaded[name]) { loaded[name] = true; ({actions: () => window.loadActions(), market: () => { if (mdStale) { mdStale = false; try { $("mdFrame").contentWindow.location.reload(); } catch (e) {} } }, pick: () => window.loadPick(), season: () => window.loadSeason(), journal: () => window.loadJournal(), today: loadToday, cal: loadCal, skew: loadSkew, risk: () => window.loadRisk(), em: () => window.loadEm(), a14: () => window.loadA14(), pnl: () => window.loadPnl(), evidence: loadEvidence, rec: loadRec, guide: () => {}})[name](); }
  else document.querySelectorAll(`#tab-${name} .chart`).forEach((c) => c._draw && c._draw());
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

/* after a desk update (update.js): every tab reloads on its next visit, the open one now (unless a pop-up is open) */
let mdStale = false;
window.deskReload = function () {
  if (document.querySelector(".modalp:not([hidden])")) { setTimeout(window.deskReload, 5000); return; }
  const cur = (document.querySelector('.tabs button[aria-selected="true"]') || {}).dataset?.tab || "actions";
  Object.keys(loaded).forEach((k) => delete loaded[k]);
  mdStale = true;
  showTab(cur);
  loadFresh();
  if (window.loadReadiness) window.loadReadiness();
};

/* ---------------- today ---------------- */
function gateCards(gates) {
  if (!gates.length) return `<div class="state">${window.DESK_CLOUD ? `🔒 Strategy gates use the daily option recording in your snapshot. <button type="button" class="unlockBtn">Unlock snapshot</button>` : "No recorded snapshot yet. Use the Recorder tab."}</div>`;
  return gates.map((g) => `<div class="card ${g.pass ? "pass" : "fail"}"><div class="row" style="justify-content:space-between"><h2>${esc(g.name)}</h2><span class="chip ${g.pass ? "pos" : "neg"}">${g.pass ? "✓ Rules pass" : "✕ Rule fails"}</span></div>
    <span class="small muted">${esc(g.rule)}</span>
    <span class="small">${segBar([{n: g.checks.filter((c) => c[1]).length, color: "var(--up)", label: "checks pass"}, {n: g.checks.filter((c) => !c[1]).length, color: "var(--down)", label: "checks fail"}], {w: 160})} ${g.checks.filter((c) => c[1]).length} of ${g.checks.length} checks pass</span>
    <span class="small">Nearest pair: <b class="mono">${g.pair.fdte} / ${g.pair.bdte} DTE</b> · contango <b class="mono">${sgn(g.pair.contango)}</b> pts${ok(g.pair.z) ? ` · <span class="${zcls(g.pair.z)}">${zTxt(g.pair.z)}</span>` : ""}${ok(g.pair.debit) ? ` · ATM put cal ${fmt(g.pair.debit)}` : ""}</span>
    <ul>${g.checks.map(([t, pass, v]) => `<li><span class="${pass ? "pos" : "neg"}">${pass ? "✓" : "✕"}</span> ${esc(t)} <span class="muted mono">${esc(v)}</span></li>`).join("")}</ul></div>`).join("");
}
async function loadToday() {
  try {
    const [t, spx, rut, sk] = await Promise.all([api("/api/term"), api("/api/calendar?symbol=SPX"), api("/api/calendar?symbol=RUT"), api("/api/skew?symbol=SPX&tenor=30")]);
    if (t.error) { $("todayStrip").innerHTML = errBox(t.error); return; }
    const c0 = t.curves[0].points, iv = sk.proxies["IV30 (IBKR, 30-day ATM)"], rv = sk.proxies["Realized vol 20d"];
    const tile = (lbl, big, sub, cls = "") => `<div><span class="lbl">${lbl}</span><span class="big ${cls}">${big}</span><span class="small muted">${sub}</span></div>`;
    const sp = t.spreads["VIX − VIX9D (30d vs 9d)"];
    $("todayStrip").innerHTML =
      tile("VIX / VIX3M", fmt(t.ratio.now, 3), `${ivtsBand(t.ratio.now).label} · ${ivtsBand(t.ratio.now).a14} · ${ivtsBand(t.ratio.now).cal} · ${zTxt(t.ratio.z)}`, ivtsBand(t.ratio.now).cls) +
      tile("30d − 9d vol", sgn(sp.now) + " pts", `${zTxt(sp.z)} · ${pctTxt(sp.pct)}`, zcls(sp.z)) +
      tile("SPX IV30", iv ? fmt(iv.now, 1) + "%" : "–", iv ? `${zTxt(iv.z)} · ${pctTxt(iv.pct)}` : (window.DESK_CLOUD ? "🔒 in your snapshot" : "run Recorder"), iv ? zcls(iv.z) : "") +
      tile("SPX realized 20d", rv ? fmt(rv.now, 1) + "%" : "–", iv && rv ? `IV − RV ${sgn(iv.now - rv.now, 1)} pts` : "") +
      tile("Data as of", shortDate(t.date), spx.date ? `snapshot ${shortDate(spx.date)}` : (window.DESK_CLOUD ? "CBOE curve (option recording in your snapshot)" : "no snapshot yet"));
    const cols = ["var(--s1)", "var(--s2)", "var(--s3)"];
    xyChart($("termCurve"), {label: "VIX term structure", xUnit: "d", xMin: 0, series: t.curves.map((c, k) => ({name: c.label, color: cols[k], dash: k ? "5 3" : null, pts: c.points.map((p) => [p.tenor, p.v, `${p.name} (${p.tenor}d)`])}))});
    $("termLegend").innerHTML = legend(t.curves.map((c, k) => [`${c.label} (${shortDate(c.date)})`, cols[k]]));
    lineChart($("ratioChart"), {label: "VIX/VIX3M", h: 190, series: [{name: "VIX / VIX3M", short: "", data: t.ratio.hist, color: "var(--ink)", width: 1.4}],
      refs: [{y: 1, label: "1.00", color: "var(--down)"}, {y: 0.83, label: "0.83", color: "var(--warn)"}], fy: (v) => v.toFixed(2), ft: (v) => v.toFixed(3)});
    $("ratioNote").textContent = "Above 1.00 = backwardation (TimeEdge hard skip). Since 2009 (model backtest, Evidence → Since 2009): calendars entered below 0.90 with SPX above its 20-day average averaged about +4% of the debit; at 0.90+ they lost on average. Your June 2–4 calendar losses (0.80–0.81) were one shock that the backtest reproduces; steep contango was otherwise the best calendar zone.";
    $("gates").innerHTML = gateCards([...(spx.gates || []), ...(rut.gates || [])]);
    const vc = {VIX9D: "var(--s2)", VIX: "var(--ink)", VIX3M: "var(--s1)"};
    lineChart($("vixHist"), {label: "VIX9D VIX VIX3M", h: 220, series: Object.entries(t.vix_hist).map(([k, d]) => ({name: k, short: k, data: d, color: vc[k], width: k === "VIX" ? 1.8 : 1.3}))});
    $("vixLegend").innerHTML = legend(Object.keys(vc).map((k) => [k, vc[k]]));
  } catch (e) { $("todayStrip").innerHTML = errBox(e); }
}

/* ---------------- calendar scanner ---------------- */
let calData = null, calSel = null, calSort = null;
const METRIC = {contango: ["Contango", "pts"], z: ["Contango z", ""], fwd_premium: ["Forward premium", "pts"], fwd_vs_rv: ["Fwd vol − RV20", "pts"]};
async function loadCal(ev) {
  if (ev) ev.preventDefault();
  const q = new URLSearchParams({symbol: $("calSym").value, fmin: $("fmin").value, fmax: $("fmax").value, gmin: $("gmin").value, gmax: $("gmax").value});
  $("calMeta").textContent = "Scanning…";
  try {
    calData = await api("/api/calendar?" + q);
    if (calData.error) { $("heat").innerHTML = errBox(calData.error); $("calMeta").textContent = ""; return; }
    calSort = {k: $("calRank").value, dir: -1};
    $("calMeta").textContent = `${calData.symbol} ${fmt(calData.spot, 2)} · snapshot ${calData.date} · ${calData.pairs.length} pairs · RV20 ${fmt(calData.rv20, 1)}% · ${calData.recorded_days} recorded sessions`;
    renderCal();
    $("calGates").innerHTML = gateCards(calData.gates);
  } catch (e) { $("heat").innerHTML = errBox(e); }
}
function calWhy(p, rank, total, colLabel, s) {
  const pros = [], cons = [];
  if (p.contango > 0) pros.push(`back month ${fmt(p.contango)} vol pts above the front: contango pays the calendar`); else cons.push(`inverted (${sgn(p.contango)} pts): front IV above back`);
  if (ok(p.z)) (p.z <= -1 ? cons : pros).push(p.z >= 1 ? `contango steeper than usual (z ${sgn(p.z)})` : p.z <= -1 ? `contango flatter than usual (z ${sgn(p.z)})` : `contango about normal (z ${sgn(p.z)})`);
  if (ok(p.fwd_premium)) (p.fwd_premium > 0 ? pros : cons).push(`forward vol ${fmt(p.fwd_vol)} is ${sgn(p.fwd_premium)} vs the front IV`);
  if (ok(p.fwd_vs_rv)) (p.fwd_vs_rv > 0 ? pros : cons).push(`forward vol ${sgn(p.fwd_vs_rv)} vs 20-day realised`);
  if (p.fdte <= 5) cons.push(`front expires in ${p.fdte}d: gamma risk`);
  const li = (a) => a.map((x) => `<li>${x}</li>`).join("");
  return `<div><b>#${rank} of ${total}</b> by ${esc(colLabel)} (${s.dir < 0 ? "highest" : "lowest"} first)</div><div>${p.fdte}d / ${p.bdte}d · ATM put calendar ${fmt(p.debit)}</div>
    ${pros.length ? `<div style="margin-top:4px"><b class="pos">For</b><ul style="margin:2px 0;padding-left:16px">${li(pros)}</ul></div>` : ""}
    ${cons.length ? `<div><b class="wrn">Watch</b><ul style="margin:2px 0;padding-left:16px">${li(cons)}</ul></div>` : ""}`;
}
function renderCal() {
  const k = $("calRank").value, P = calData.pairs;
  const fronts = [...new Map(P.map((p) => [p.front, p.fdte])).entries()].sort((a, b) => a[1] - b[1]);
  const backs = [...new Map(P.map((p) => [p.back, p.bdte])).entries()].sort((a, b) => a[1] - b[1]);
  const cells = new Map(P.map((p) => [`${p.front}|${p.back}`, {v: p[k], sel: calSel && calSel.front === p.front && calSel.back === p.back,
    title: `<div><b>${p.fdte} / ${p.bdte} DTE</b> (${p.front} → ${p.back})</div><div>Front IV <b>${fmt(p.front_iv)}</b> · back <b>${fmt(p.back_iv)}</b></div><div>Contango <b>${sgn(p.contango)}</b> · ${zTxt(p.z)}</div><div>Fwd vol <b>${fmt(p.fwd_vol)}</b> · premium <b>${sgn(p.fwd_premium)}</b></div><div>ATM put cal <b>${fmt(p.debit)}</b></div>`}]));
  heatmap($("heat"), {label: "pair heatmap", rows: fronts.map(([e, d]) => ({key: e, label: `${d}d ${shortDate(e.slice(0, 4) + "-" + e.slice(4, 6) + "-" + e.slice(6))}`})),
    cols: backs.map(([e, d]) => ({key: e, label: `${d}d`})), cells, onClick: (f, b) => selectPair(f, b)});
  $("heatLegend").innerHTML = legend([[`higher ${METRIC[k][0].toLowerCase()}`, "var(--up)", 1], [`lower / negative`, "var(--down)", 1], ["no data", "var(--soft)", 1]]);
  const cols = [["fdte", "Front"], ["bdte", "Back"], ["front_iv", "Front IV"], ["back_iv", "Back IV"], ["contango", "Contango"], ["z", "Contango z"], ["fwd_vol", "Fwd vol"], ["fwd_premium", "Fwd prem."], ["fwd_vs_rv", "Fwd − RV20"], ["debit", "ATM put cal"]];
  const s = calSort, sorted = [...P].sort((a, b) => { const x = a[s.k], y = b[s.k]; if (!ok(x) && !ok(y)) return 0; if (!ok(x)) return 1; if (!ok(y)) return -1; return s.dir < 0 ? y - x : x - y; });
  const rows = sorted.slice(0, 40), colName = Object.fromEntries(cols);
  $("pairTable").innerHTML = `<div class="tbl"><table><thead><tr><th class="n" title="rank by the sorted column · hover a badge for why">#</th>${cols.map(([c, l]) => `<th class="sort n" tabindex="0" data-k="${c}" ${s.k === c ? `aria-sort="${s.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${s.k === c ? (s.dir < 0 ? " ▾" : " ▴") : ""}</th>`).join("")}</tr></thead><tbody>${
    rows.map((p, i) => `<tr class="click ${calSel && calSel.front === p.front && calSel.back === p.back ? "sel" : ""}" tabindex="0" data-f="${p.front}" data-b="${p.back}">
      <td class="n"><span class="rank" data-i="${i}">${i + 1}</span></td><td class="n">${p.fdte}d</td><td class="n">${p.bdte}d</td><td class="n">${fmt(p.front_iv)}</td><td class="n">${fmt(p.back_iv)}</td>
      <td class="n ${p.contango < 0 ? "neg" : ""}">${sgn(p.contango)}</td><td class="n ${zcls(p.z)}" title="${esc(p.zsrc || "")}">${ok(p.z) ? sgn(p.z) : "–"}</td>
      <td class="n">${fmt(p.fwd_vol)}</td><td class="n">${sgn(p.fwd_premium)}</td><td class="n">${sgn(p.fwd_vs_rv)}</td><td class="n">${fmt(p.debit)}</td></tr>`).join("")}</tbody></table></div>`;
  const ci = cols.findIndex(([c]) => c === s.k), vals = rows.map((p) => p[s.k]).filter(ok), mx = Math.max(...vals.map(Math.abs), 1e-9), signed = vals.some((v) => v < 0);
  if (ci >= 0) $("pairTable").querySelectorAll("tbody tr").forEach((tr, i) => { const td = tr.children[ci + 1], v = rows[i][s.k];
    if (td && ok(v)) td.insertAdjacentHTML("afterbegin", hBarSvg(v, mx, {w: 44, zeroLeft: !signed, color: signed ? null : "var(--accent)", label: `${colName[s.k]} vs the largest in the list`}) + " "); });
  bindTip($("pairTable"), ".rank", (n) => calWhy(rows[+n.dataset.i], +n.dataset.i + 1, sorted.length, colName[s.k] || s.k, s));
  $("pairTable").querySelectorAll("th.sort").forEach((th) => { const go = () => { calSort = {k: th.dataset.k, dir: calSort.k === th.dataset.k ? -calSort.dir : -1}; renderCal(); };
    th.addEventListener("click", go); th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }); });
  $("pairTable").querySelectorAll("tr.click").forEach((tr) => { const go = () => selectPair(tr.dataset.f, tr.dataset.b); tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); });
}
async function pairRisk(front, back, strike) {
  const box = document.createElement("div"); box.id = "pairRisk"; box.innerHTML = `<div class="state loading">Pricing the calendar…</div>`;
  $("pairBox").appendChild(box);
  const c = await api(`/api/pair/curve?symbol=${calData.symbol}&front=${front}&back=${back}${ok(strike) ? "&strike=" + strike : ""}`).catch((e) => ({error: e.message}));
  if (c.error) { box.innerHTML = errBox(c.error); return; }
  const usd = (v) => (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString();
  const mv = (x) => ok(x) ? (x > 0 ? "+" : "") + x.toFixed(1) + "%" : "beyond the chart";
  const dayMv = 100 * c.em_day / c.spot;
  const stopTxt = c.stops.map((s) => `<div><span class="lbl">Stop ${Math.round(100 * s.pct)}% of debit</span><b>${usd(s.level)}</b><span class="small muted">hit overnight by ${mv(s.down)} / ${mv(s.up)} · a 1-day 1σ move is ±${dayMv.toFixed(1)}%</span></div>`).join("");
  box.innerHTML = `<h3 style="margin:12px 0 6px">Risk at the card's stop · ${esc(c.symbol)} ${fmt(c.strike, 0)}P ${c.fdte}d / ${c.bdte}d, 1 lot</h3>
    <div class="kv mini"><div><span class="lbl">Debit</span><b>${fmt(c.debit)}</b><span class="small muted">${c.modelled ? "modelled from the recorded smile (no common strike quoted)" : "recorded mid"} · ${esc(c.date)} 15:40 ET, not live</span></div>${stopTxt}</div>
    <div class="chart" id="pairRiskChart"></div>${legend([["tomorrow (overnight gap)", "var(--s1)"], ["tomorrow, IV −2 pts", "var(--down)"], [`after ${c.half} days`, "var(--accent)"], ["at front expiry", "var(--faint)"], ["stop 15% / 20%", "var(--warn)"]])}
    <p class="note">Black-76 on the snapshot's own IV at this strike, each strike's IV held (sticky strike); shaded = a 1-day 1σ move. Your worst June calendar lost 39% in one day: a move past the stop points above, or an IV drop on top of a smaller move, gets there before you can adjust. Size so a full-debit loss on one trade is acceptable, and exit at the stop.</p>`;
  const flat = (v) => c.S.map(() => v);
  window.riskChart($("pairRiskChart"), {label: "calendar risk graph", h: 240, xs: c.S, spot: c.spot, nowPnl: 0, ticks: 5,
    fx: (v, long) => long ? `${c.symbol} ${fmt(v, 0)} (${(100 * (v / c.spot - 1)).toFixed(1)}%)` : fmt(v, 0),
    series: [{name: "at front expiry", ys: c.front_exp, color: "var(--faint)", width: 1.4}, {name: `after ${c.half} days`, ys: c.mid, color: "var(--accent)", width: 1.8},
      {name: "tomorrow", ys: c.tomorrow, color: "var(--s1)", width: 2.2, fill: true}, {name: "tomorrow, IV −2 pts", ys: c.tomorrow_ivdown, color: "var(--down)", width: 1.4, dash: "5 3"},
      ...c.stops.map((s) => ({name: `stop ${Math.round(100 * s.pct)}%`, ys: flat(s.level), color: "var(--warn)", width: 1.2, dash: "2 3"}))],
    bands: [[c.spot - c.em_day, c.spot + c.em_day]]});
}
async function selectPair(front, back) {
  calSel = {front, back}; renderCal();
  const p = calData.pairs.find((x) => x.front === front && x.back === back);
  $("pairPanel").hidden = false;
  $("pairBox").innerHTML = `<div class="state loading">Loading history…</div>`;
  try {
    const d = await api(`/api/pair?symbol=${calData.symbol}&front=${front}&back=${back}`);
    if (d.error) { $("pairBox").innerHTML = errBox(d.error); return; }
    const series = [];
    if (d.matched && d.matched.length) series.push({name: "Maturity-matched (CBOE)", short: "matched", data: d.matched, color: "var(--s1)", width: 1.4});
    if (d.matched_recorded && d.matched_recorded.length) series.push({name: "Maturity-matched (recorded)", short: "rec", data: d.matched_recorded, color: "var(--s3)", width: 1.6, dots: d.matched_recorded.length < 40});
    if (d.actual && d.actual.length) series.push({name: "This exact expiry pair", short: "actual", data: d.actual, color: "var(--accent)", width: 2, dots: true});
    $("pairBox").innerHTML = `<div class="kv">
      <div><span class="lbl">Pair</span><b class="mono">${p.fdte} / ${p.bdte}d</b><span class="small muted">${front} → ${back}</span></div>
      <div><span class="lbl">Contango</span><b>${sgn(p.contango)}</b><span class="small ${zcls(p.z)}">${zTxt(p.z)} ${p.zsrc ? "· " + esc(p.zsrc) : ""}</span></div>
      <div><span class="lbl">Forward vol</span><b>${fmt(p.fwd_vol)}</b><span class="small muted">premium ${sgn(p.fwd_premium)} · vs RV ${sgn(p.fwd_vs_rv)}</span></div>
      <div><span class="lbl">ATM put calendar</span><b>${fmt(p.debit)}</b><span class="small muted">strike ${fmt(p.strike, 0)}</span></div></div>
      <div class="chart" id="pairChart"></div>${legend(series.map((s) => [s.name, s.color]))}
      <p class="note">Maturity-matched = today's ${p.fdte}d and ${p.bdte}d maturities re-measured on every past day, so it is comparable through time. The exact-pair line follows these two expiries as they age, from your recorded snapshots.${d.matched_src ? " Source: " + esc(d.matched_src) + "." : ""}</p>`;
    lineChart($("pairChart"), {label: "pair contango history", h: 220, mR: 112, series, refs: [{y: 0, color: "var(--line)"}], ft: (v) => sgn(v) + " pts"});
    pairRisk(front, back, p.strike);
  } catch (e) { $("pairBox").innerHTML = errBox(e); }
}
$("calForm").addEventListener("submit", loadCal);
$("calRank").addEventListener("change", () => { if (calData && !calData.error) { calSort = {k: $("calRank").value, dir: -1}; renderCal(); } });

/* ---------------- skew & IV ---------------- */
let skData = null;
async function loadSkew(ev) {
  if (ev) ev.preventDefault();
  try {
    skData = await api(`/api/skew?symbol=${$("skSym").value}&tenor=${$("skTen").value}`);
    const d = skData;
    $("skMeta").textContent = d.date ? `snapshot ${d.date} · ${d.recorded_days} recorded session${d.recorded_days === 1 ? "" : "s"}` : "no snapshot yet";
    const cur = Object.entries(d.current);
    const zBar = (z) => ok(z) ? bulletSvg(z, {w: 150, lo: -3, hi: 3, color: Math.abs(z) >= 2 ? "var(--down)" : Math.abs(z) >= 1 ? "var(--warn)" : "var(--accent)", label: `z-score ${fmt(z, 2)} (0 = its usual level)`,
      zones: [{from: -3, to: -2, color: "var(--down)"}, {from: -2, to: -1, color: "var(--warn)"}, {from: 1, to: 2, color: "var(--warn)"}, {from: 2, to: 3, color: "var(--down)"}], marks: [{v: 0, color: "var(--muted)", width: 1}]}) : "";
    $("skCur").innerHTML = cur.length ? cur.map(([k, v]) => `<div><span class="lbl">${esc(k)}</span><b>${fmt(v.now)}${k === "ATM IV" ? "%" : " pts"}</b>${zBar(v.z)}<span class="small ${zcls(v.z)}">${ok(v.z) ? zTxt(v.z) : `z after 20 sessions (${v.n} so far)`}</span></div>`).join("")
      : `<div class="state">No recorded surface yet for ${d.symbol}. Record from the Recorder tab.</div>`;
    $("skProxy").innerHTML = Object.entries(d.proxies).map(([k, v]) => `<div><span class="lbl">${esc(k)}</span><b>${fmt(v.now)}</b>${zBar(v.z)}<span class="small ${zcls(v.z)}">${ok(v.z) ? `${zTxt(v.z)} · ${pctTxt(v.pct)}` : ""}</span></div>`).join("");
    const cols = {atm: ["ATM", "var(--ink)"], p25: ["25Δ put", "var(--s2)"], p10: ["10Δ put", "var(--down)"], c25: ["25Δ call", "var(--s1)"]};
    xyChart($("skTerm"), {label: "vol by expiry", xUnit: "d", series: Object.entries(cols).map(([k, [n, c]]) => ({name: n, color: c, pts: d.term.map((r) => [r.dte, r[k], `${n} ${r.dte}d`])}))});
    $("skTermLegend").innerHTML = legend(Object.values(cols));
    const opts = [...Object.keys(d.history).map((k) => ["rec:" + k, k + " (recorded)"]), ...Object.entries(d.proxies).filter(([, v]) => v.hist).map(([k]) => ["px:" + k, k])];
    $("skHistSel").innerHTML = opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
    if (opts.length) $("skHistSel").value = opts.find((o) => o[0].startsWith("px:"))?.[0] || opts[0][0];
    drawSkHist();
  } catch (e) { $("skCur").innerHTML = errBox(e); }
}
function drawSkHist() {
  const v = $("skHistSel").value; if (!v || !skData) { $("skHist").innerHTML = ""; return; }
  const i = v.indexOf(":"), kind = v.slice(0, i), key = v.slice(i + 1);
  const data = kind === "rec" ? skData.history[key] : skData.proxies[key].hist;
  lineChart($("skHist"), {label: key, h: 230, series: [{name: key, short: "", data, color: "var(--s1)", width: 1.5, dots: data.length < 40}]});
}
$("skewForm").addEventListener("submit", loadSkew);
$("skHistSel").addEventListener("change", drawSkHist);

/* ---------------- evidence ---------------- */
let evData = null;
async function loadEvidence() {
  if (window.loadBacktest) window.loadBacktest();
  try {
    evData = await api("/api/evidence");
    if (evData.error) { $("evStrat").innerHTML = errBox(evData.error); return; }
    $("evMeta").textContent = `${evData.n} closed trades · ONE: ${(evData.files.one || "none").split(/[\\/]/).pop()} · OptionStrat: ${(evData.files.optionstrat || "none").split(/[\\/]/).pop()}`;
    $("evStrat").innerHTML = evData.by_strategy.map((s) => `<div><span class="lbl">${esc(s.strategy)}</span><b class="${s.pnl >= 0 ? "pos" : "neg"}">${s.pnl >= 0 ? "+" : "−"}$${Math.abs(s.pnl).toLocaleString(undefined, {maximumFractionDigits: 0})}</b><span class="small muted">${s.n} trades · ${Math.round(100 * s.wins / s.n)}% winners</span></div>`).join("");
    barChart($("evStratChart"), {label: "P&L by strategy ($k)", h: 130, unit: "k", items: evData.by_strategy.map((s) => ({label: s.strategy, v: s.pnl / 1000, n: s.n,
      title: `<b>${esc(s.strategy)}</b>: ${s.pnl >= 0 ? "+" : "−"}$${Math.abs(s.pnl).toLocaleString(undefined, {maximumFractionDigits: 0})} · ${s.n} trades · ${Math.round(100 * s.wins / s.n)}% winners`}))});
    $("evNote").textContent = evData.note;
    $("evFeat").innerHTML = evData.features.map((f) => `<option value="${f.key}">${esc(f.label)}</option>`).join("");
    $("evFeat").value = "vix_vix3m";
    $("evFeatTable").innerHTML = `<div class="tbl"><table><thead><tr><th>Condition at entry</th><th class="n">Winners (median)</th><th class="n">Losers (median)</th><th>Every trade · medians</th><th>Best skip rule in hindsight</th></tr></thead><tbody>${
      evData.features.map((f) => { const b = f.best_rule, xs = evData.trades.map((t) => t[f.key]).filter(ok);
        const strip = xs.length ? bulletSvg(null, {w: 130, lo: Math.min(...xs), hi: Math.max(...xs), label: `${f.label}: each tick a trade (teal winner, red loser); thick = medians, dashed = skip line`,
          marks: [...evData.trades.filter((t) => ok(t[f.key])).map((t) => ({v: t[f.key], width: 1, color: `color-mix(in srgb, ${t.win ? "var(--up)" : "var(--down)"} 45%, transparent)`})),
            {v: f.win_median, color: "var(--up)", width: 3}, {v: f.loss_median, color: "var(--down)", width: 3}, ...(b ? [{v: b.threshold, color: "var(--ink)", width: 1.5, dash: 1}] : [])]}) : "";
        return `<tr class="click" data-k="${f.key}"><td title="${esc(f.hint)}">${esc(f.label)}</td><td class="n">${fmt(f.win_median, 3)}</td><td class="n">${fmt(f.loss_median, 3)}</td><td>${strip}</td>
        <td class="small">${b ? `skip ${b.side} <b class="mono">${b.threshold}</b>: ${b.skipped} trades (${b.skipped_losers} losers, ${b.skipped_winners} winners), P&amp;L skipped <span class="${b.pnl_skipped < 0 ? "pos" : "neg"}">${b.pnl_skipped < 0 ? "−" : "+"}$${Math.abs(b.pnl_skipped).toLocaleString()}</span>` : "–"}</td></tr>`; }).join("")}</tbody></table></div>
      <p class="note">A rule that skips more losing P&amp;L than winning P&amp;L shows the skipped amount in teal. These are fitted to past trades, so treat them as things to watch, not filters to trust.</p>`;
    $("evFeatTable").querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => { $("evFeat").value = tr.dataset.k; drawEv(); }));
    const T = [...evData.trades].sort((a, b) => a.pnl - b.pnl), tmx = Math.max(...T.map((t) => Math.abs(t.pnl)), 1);
    $("evTrades").innerHTML = `<div class="tbl"><table><thead><tr><th>Entered</th><th>Strategy</th><th>Trade</th><th class="n">P&amp;L</th><th class="n">Return</th><th class="n">VIX/VIX3M</th><th class="n">VIX9D/VIX</th><th class="n">Slope 15→22</th><th class="n">VIX 5d chg</th><th class="n">SPX 5d %</th><th>Source</th></tr></thead><tbody>${
      T.map((t) => `<tr><td class="mono small">${t.date}</td><td>${esc(t.strategy)}</td><td class="small">${esc(t.name)}</td><td class="n ${t.pnl >= 0 ? "pos" : "neg"}">${hBarSvg(t.pnl, tmx, {w: 60, label: "P&L vs the largest trade"})} ${Math.round(t.pnl).toLocaleString()}</td><td class="n">${fmt(t.ret_pct, 1)}%</td>
        <td class="n ${t.vix_vix3m >= 0.90 ? "wrn" : ""}">${fmt(t.vix_vix3m, 3)}</td><td class="n">${fmt(t.vix9d_vix, 3)}</td><td class="n">${fmt(t.slope_15_22, 2)}</td><td class="n">${sgn(t.vix_chg5)}</td><td class="n">${sgn(t.spx_ret5)}</td><td class="small muted">${esc(t.source)}</td></tr>`).join("")}</tbody></table></div>`;
    drawEv();
  } catch (e) { $("evStrat").innerHTML = errBox(e); }
}
function drawEv() {
  const k = $("evFeat").value, f = evData.features.find((x) => x.key === k);
  const mx = Math.max(...evData.trades.map((t) => Math.abs(t.pnl)), 1);
  scatter($("evScatter"), {label: f.label, xLabel: f.label, vline: f.best_rule ? f.best_rule.threshold : null,
    points: evData.trades.map((t) => ({x: t[k], y: t.pnl, color: t.win ? "var(--up)" : "var(--down)", r: 3.5 + 7 * Math.sqrt(Math.abs(t.pnl) / mx),
      title: `<div><b>${esc(t.strategy)}</b> ${esc(t.date)}</div><div>${esc(t.name)}</div><div>P&L <b>${Math.round(t.pnl).toLocaleString()}</b> · ${esc(f.label)} <b>${fmt(t[k], 3)}</b></div>`}))});
}
$("evFeat").addEventListener("change", drawEv);

/* ---------------- recorder ---------------- */
async function loadRec() {
  try {
    const s = await api("/api/status");
    const nxt = s.next_record ? new Date(s.next_record) : null;
    $("recKv").innerHTML = `<div><span class="lbl">Status</span><b>${s.recorder.running ? "Recording…" : "Idle"}</b><span class="small muted">last ${s.last_record ? new Date(s.last_record).toLocaleString() : "never"}</span></div>
      <div><span class="lbl">Next scheduled</span><b>${nxt ? nxt.toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"}) : "–"}</b><span class="small muted">${esc(s.record_time_et)} ET on weekdays (your time shown)</span></div>
      <div><span class="lbl">CBOE history</span><b>${s.cboe_refreshed ? new Date(s.cboe_refreshed).toLocaleDateString() : "never"}</b><span class="small muted">refreshes every 8 hours</span></div>`;
    const inv = s.inventory;
    $("recInv").innerHTML = `<div class="tbl"><table><thead><tr><th>Series</th><th class="n">Rows</th><th>From</th><th>To</th></tr></thead><tbody>${
      inv.snapshots.map((r) => `<tr><td><b>${esc(r.symbol)} surface snapshots</b></td><td class="n">${r.n}</td><td class="mono small">${r.a}</td><td class="mono small">${r.b}</td></tr>`).join("") +
      inv.history.map((r) => `<tr><td>${esc(r.symbol)}</td><td class="n">${r.n.toLocaleString()}</td><td class="mono small">${r.a}</td><td class="mono small">${r.b}</td></tr>`).join("")}</tbody></table></div>`;
    $("recLog").textContent = (s.recorder.log || []).join("\n") || "No activity yet.";
    if (!window.DESK_CLOUD) loadSnap();
    $("btnRecord").disabled = s.recorder.running;
    if (s.recorder.running) setTimeout(loadRec, 3000);
  } catch (e) { $("recKv").innerHTML = errBox(e); }
}
async function loadSnap() {
  const s = await api("/api/snapshot").catch(() => null); if (!s) return;
  $("snapKv").innerHTML = `<div><span class="lbl">Passphrase</span><b class="${s.key_set ? "pos" : "wrn"}">${s.key_set ? "set" : "not set"}</b><span class="small muted">${s.key_set_at ? "since " + new Date(s.key_set_at).toLocaleString() : "nothing is published until you set one"}</span></div>
    <div><span class="lbl">Last published</span><b>${s.last ? new Date(s.last).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"}) : "never"}</b><span class="small muted">${s.running ? "publishing…" : s.bytes ? Math.round(s.bytes / 1024).toLocaleString() + " kB encrypted" + (s.entries ? " · " + s.entries + " views" : "") : ""}</span></div>
    <div><span class="lbl">Automatic</span><b>${s.auto ? "on" : "off"}</b><span class="small muted">${s.error ? `<span class="neg">${esc(s.error)}</span>` : "when anything changes, at most every 20 min"}</span></div>`;
  if (s.running) setTimeout(loadSnap, 3000);
}
$("snapKeyForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const a = $("snapP1").value, b = $("snapP2").value;
  if (a !== b) { $("snapMsg").innerHTML = `<span class="neg">The two entries differ.</span>`; return; }
  const r = await api("/api/snapshot/key", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({passphrase: a})});
  $("snapP1").value = $("snapP2").value = "";
  if (r.error) { $("snapMsg").innerHTML = `<span class="neg">${esc(r.error)}</span>`; return; }
  $("snapMsg").textContent = "Passphrase set. Publishing…";
  await api("/api/snapshot/publish", {method: "POST"}); setTimeout(loadSnap, 1500);
});
$("snapPub").addEventListener("click", async () => { $("snapMsg").textContent = "Publishing…"; await api("/api/snapshot/publish", {method: "POST"}); setTimeout(loadSnap, 1500); });
$("btnRecord").addEventListener("click", async () => { $("recMsg").textContent = "Starting…"; const r = await api("/api/record", {method: "POST"}); $("recMsg").textContent = r.started ? "Recording started. This takes about 2 minutes." : r.message; loadRec(); });
$("btnHist").addEventListener("click", async () => { $("recMsg").textContent = "Downloading CBOE history…"; const r = await api("/api/refresh-history", {method: "POST"}); $("recMsg").textContent = r.error || "CBOE history refreshed."; loadRec(); });
$("btnTws").addEventListener("click", async () => { $("recMsg").textContent = "Connecting…"; const r = await api("/api/tws"); $("recMsg").innerHTML = r.ok ? `<span class="pos">TWS connection OK (read-only).</span>` : `<span class="neg">Could not connect: ${esc(r.error || "")}. Check TWS is open and API socket clients are enabled on port 7496.</span>`; });

// a fresh open lands on Actions; a reload keeps the tab you were on
let start = "actions"; try { start = sessionStorage.getItem("od.tab") || "actions"; } catch (e) {}
window.addEventListener("load", () => showTab(["actions", "market", "today", "cal", "skew", "risk", "pnl", "evidence", "rec"].includes(start) ? start : "actions"));

/* the Market tab is the former Market Desk page in a same-origin frame: size it to its content */
(() => {
  const f = $("mdFrame"); if (!f) return;
  // measure the page's own content (.wrap), not the document: the document is never shorter than the frame,
  // so it could only ever grow and a short sub-tab would leave empty scroll below it
  const fit = () => { try { const d = f.contentDocument, w = d && (d.querySelector(".wrap") || d.body); if (w) f.style.height = Math.ceil(w.getBoundingClientRect().height + 4) + "px"; } catch (e) {} };
  f.addEventListener("load", () => {
    fit();
    try { const d = f.contentDocument; new ResizeObserver(fit).observe(d.querySelector(".wrap") || d.body); d.defaultView.addEventListener("subtab", () => setTimeout(fit, 50)); } catch (e) {}
    setInterval(fit, 1500);
  });
})();
