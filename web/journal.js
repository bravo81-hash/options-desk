/* Trade journal: closed trades from the ONE Summary Report, visual. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const day = (iso) => iso ? new Date(iso.length > 10 ? iso : iso + "T12:00:00").toLocaleDateString([], {day: "numeric", month: "short", year: "2-digit"}) : "–";
const PAL = {"A14": "var(--s1)", "TimeEdge": "var(--s2)", "TimeZone": "var(--s3)", "Triple Cal": "var(--s4)", "Flyagonal": "var(--accent)", "Allantis": "var(--warn)", "IF": "var(--info)", "M200": "var(--muted)", "Other": "var(--faint)"};
const col = (s) => PAL[s] || "var(--faint)";
let J = null, F = {strategy: "", ticker: "", group: "", result: "", q: ""};

/* ---------- overview ---------- */
function overview(T) {
  const W = T.filter((t) => (t.pnl || 0) > 0), tot = T.reduce((a, t) => a + (t.pnl || 0), 0);
  const avg = (a, f) => a.length ? a.reduce((s, t) => s + (f(t) || 0), 0) / a.length : null;
  const best = T.reduce((m, t) => (!m || t.pnl > m.pnl ? t : m), null), worst = T.reduce((m, t) => (!m || t.pnl < m.pnl ? t : m), null);
  const tile = (l, b, sub, k = "") => `<div><span class="lbl">${l}</span><span class="big ${k}">${b}</span><span class="small muted">${sub}</span></div>`;
  $("jnStrip").innerHTML = tile("Closed trades", T.length, `${W.length} won · ${T.length - W.length} lost`) +
    tile("Win rate", T.length ? Math.round(100 * W.length / T.length) + "%" : "–", "share of closed trades in profit") +
    tile("Total P&L", money(tot), `average ${money(avg(T, (t) => t.pnl))} per trade`, cls(tot)) +
    tile("Average return", pctS(avg(T, (t) => t.ret)), `of margin · ${(avg(T, (t) => t.dit) || 0).toFixed(0)} days held on average`, cls(avg(T, (t) => t.ret))) +
    tile("Best", best ? money(best.pnl) : "–", best ? `#${best.trade_id} ${esc(best.ticker)} ${day(best.exit_us)}` : "", "pos") +
    tile("Worst", worst ? money(worst.pnl) : "–", worst ? `#${worst.trade_id} ${esc(worst.ticker)} ${day(worst.exit_us)}` : "", "neg");
  // cumulative P&L by close date, plus each trade as a bar
  const byDay = {};
  T.forEach((t) => { if (t.exit_us) byDay[t.exit_us] = (byDay[t.exit_us] || 0) + (t.pnl || 0); });
  const days = Object.keys(byDay).sort(); let run = 0;
  const cum = days.map((d) => ({d, v: (run += byDay[d])}));
  lineChart($("jnCum"), {label: "cumulative P&L of closed trades", h: 220, series: [{name: "Cumulative P&L", short: "", data: cum, color: "var(--s1)", width: 2}],
    fy: (v) => Math.abs(v) >= 1000 ? (v / 1000).toFixed(0) + "k" : v.toFixed(0), ft: (v) => money(v), refs: [{y: 0}]});
  // days held vs return, coloured by strategy, size by margin
  const mx = Math.max(...T.map((t) => t.margin || 0), 1);
  scatter($("jnScatter"), {label: "days held vs return", h: 220, xLabel: "days in trade →", points: T.filter((t) => ok(t.dit) && ok(t.ret)).map((t) => ({x: t.dit, y: t.ret, color: col(t.strategy),
    r: 3 + 6 * Math.sqrt((t.margin || 0) / mx), title: `<b>#${t.trade_id} ${esc(t.name)}</b><br>${t.dit} days · ${pctS(t.ret)} · ${money(t.pnl)}<br>${esc(t.note)}`}))});
  // by strategy
  const g = {};
  T.forEach((t) => { const s = (g[t.strategy] = g[t.strategy] || {n: 0, w: 0, pnl: 0, ret: 0, dit: 0}); s.n++; if (t.pnl > 0) s.w++; s.pnl += t.pnl || 0; s.ret += t.ret || 0; s.dit += t.dit || 0; });
  const rows = Object.entries(g).sort((a, b) => b[1].pnl - a[1].pnl), mp = Math.max(...rows.map(([, s]) => Math.abs(s.pnl)), 1);
  $("jnStrat").innerHTML = rows.map(([k, s]) => `<div class="rsrow" style="grid-template-columns:7em minmax(0,1fr) 16em" title="${s.n} trades · win ${Math.round(100 * s.w / s.n)}% · avg ${pctS(s.ret / s.n)} over ${(s.dit / s.n).toFixed(0)} days">
    <span><i class="dot" style="background:${col(k)}"></i>${esc(k)}</span><span class="rstrack"><i style="${s.pnl >= 0 ? `left:50%;width:${50 * s.pnl / mp}%` : `left:${50 - 50 * -s.pnl / mp}%;width:${50 * -s.pnl / mp}%`};background:${s.pnl >= 0 ? "var(--up)" : "var(--down)"}"></i><em></em></span>
    <span class="mono small">${money(s.pnl)} · ${s.n} · win ${Math.round(100 * s.w / s.n)}% · ${pctS(s.ret / s.n)}</span></div>`).join("");
  // month x strategy heat
  const months = [...new Set(T.map((t) => (t.exit_us || "").slice(0, 7)).filter(Boolean))].sort();
  const strats = rows.map(([k]) => k);
  const cell = (m, s) => T.filter((t) => (t.exit_us || "").startsWith(m) && t.strategy === s).reduce((a, t) => a + (t.pnl || 0), 0);
  const all = months.flatMap((m) => strats.map((s) => Math.abs(cell(m, s)))), hm = Math.max(...all, 1);
  $("jnMonths").innerHTML = `<div class="tbl"><table><thead><tr><th>Month closed</th>${strats.map((s) => `<th class="n">${esc(s)}</th>`).join("")}<th class="n">All</th></tr></thead><tbody>${
    months.slice().reverse().map((m) => { const tot = strats.reduce((a, s) => a + cell(m, s), 0); return `<tr><td>${new Date(m + "-15").toLocaleDateString([], {month: "short", year: "numeric"})}</td>${strats.map((s) => { const v = cell(m, s);
      return `<td class="n" style="${v ? `background:color-mix(in srgb, var(${v > 0 ? "--up" : "--down"}) ${Math.round(12 + 45 * Math.abs(v) / hm)}%, transparent)` : ""}">${v ? money(v) : ""}</td>`; }).join("")}<td class="n"><b class="${cls(tot)}">${money(tot)}</b></td></tr>`; }).join("")}</tbody></table></div>`;
}

/* ---------- trades: list on the left, one trade in full on the right ---------- */
let SEL = null, SORT = "date";
const OPEN_KEY = "od.jn.open";
let openF = (() => { try { return JSON.parse(localStorage.getItem(OPEN_KEY) || "null") || {}; } catch (e) { return {}; } })();
function filtered() {
  return J.trades.filter((t) => (!F.strategy || t.strategy === F.strategy) && (!F.ticker || t.ticker === F.ticker) && (!F.group || t.group === F.group)
    && (!F.result || (F.result === "win" ? t.pnl > 0 : t.pnl <= 0)) && (!F.q || (t.name + " " + t.note + " " + t.trade_id).toLowerCase().includes(F.q.toLowerCase())));
}
const sorter = {date: (a, b) => (b.close || "").localeCompare(a.close || ""), pnl: (a, b) => (b.pnl || 0) - (a.pnl || 0), ret: (a, b) => (b.ret || 0) - (a.ret || 0), worst: (a, b) => (a.pnl || 0) - (b.pnl || 0)};
function list() {
  const T = filtered();
  $("jnCount").textContent = `${T.length} of ${J.trades.length}`;
  const g = {};
  T.forEach((t) => { (g[t.strategy] = g[t.strategy] || []).push(t); });
  const folders = Object.entries(g).sort((a, b) => b[1].length - a[1].length);
  const mx = Math.max(...T.map((t) => Math.abs(t.ret || 0)), 1);
  $("jnList").innerHTML = folders.map(([s, rows]) => {
    const tot = rows.reduce((a, t) => a + (t.pnl || 0), 0), win = rows.filter((t) => t.pnl > 0).length, open = openF[s] !== false;
    rows.sort(sorter[SORT]);
    return `<div class="jfold"><button type="button" class="jfh" data-s="${esc(s)}"><span>${open ? "▾" : "▸"} <i class="dot" style="background:${col(s)}"></i><b>${esc(s)}</b> <span class="muted">${rows.length}</span></span>
      <span class="mono small ${cls(tot)}">${money(tot)} <span class="muted">· win ${Math.round(100 * win / rows.length)}%</span></span></button>
      ${open ? rows.map((t) => `<div class="jrow ${SEL === t.key ? "sel" : ""}" data-key="${esc(t.key)}" tabindex="0">
        <span class="mono">#${esc(t.trade_id)}</span><span><b>${esc(t.ticker)}</b> <span class="small muted">${esc(t.name.replace(/\s*-\s*\d+\s*LOTS?/i, ""))}</span></span>
        <span class="jbar"><i style="width:${(50 * Math.min(Math.abs(t.ret || 0), mx) / mx).toFixed(0)}%;${(t.ret || 0) >= 0 ? "left:50%" : "right:50%"};background:${(t.pnl || 0) >= 0 ? "var(--up)" : "var(--down)"}"></i></span>
        <span class="mono small ${cls(t.pnl)}" style="text-align:right">${money(t.pnl)}</span>
        <span class="small muted" style="text-align:right">${day(t.exit_us)}</span></div>`).join("") : ""}</div>`;
  }).join("") || `<div class="state">No closed trades match.</div>`;
  $("jnList").querySelectorAll(".jfh").forEach((b) => b.addEventListener("click", () => {
    openF[b.dataset.s] = openF[b.dataset.s] === false; try { localStorage.setItem(OPEN_KEY, JSON.stringify(openF)); } catch (e) {} list(); }));
  $("jnList").querySelectorAll(".jrow").forEach((r) => r.addEventListener("click", () => select(r.dataset.key)));
  if (!SEL || !T.some((t) => t.key === SEL)) { const first = $("jnList").querySelector(".jrow"); if (first) select(first.dataset.key, true); else $("jnDetailBody").innerHTML = ""; }
}
function visibleKeys() { return [...$("jnList").querySelectorAll(".jrow")].map((r) => r.dataset.key); }
function select(key, quiet) {
  SEL = key;
  $("jnList").querySelectorAll(".jrow").forEach((r) => r.classList.toggle("sel", r.dataset.key === key));
  const row = $("jnList").querySelector(`.jrow[data-key="${CSS.escape(key)}"]`); if (row && !quiet) row.scrollIntoView({block: "nearest"});
  detail(key);
}
document.addEventListener("keydown", (e) => {
  if ($("tab-journal").hidden || !SEL || ["INPUT", "TEXTAREA", "SELECT"].includes((document.activeElement || {}).tagName)) return;
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const ks = visibleKeys(), i = ks.indexOf(SEL), j = e.key === "ArrowDown" ? i + 1 : i - 1;
  if (j >= 0 && j < ks.length) { e.preventDefault(); select(ks[j]); }
});

function detail(key) {
  const t = J.trades.find((x) => x.key === key); if (!t) return;
  const c = t.ctx || {}, B = ivtsBand(c.ivts), S = t.swing || {};
  $("jnDetailTitle").innerHTML = `<span class="mono">#${esc(t.trade_id)}</span> · ${esc(t.name)} <span class="chip" style="color:${col(t.strategy)};margin-left:6px">${esc(t.strategy)}</span> <span class="small muted">${esc(t.group)}</span>`;
  const swing = ok(S.mae) ? `<b>${money(S.mae)} / ${money(S.mfe)}</b><span class="small muted">worst / best marked P&amp;L · ${S.marked_days} closes recorded</span>`
    : `<b>${pctS(c.maxdn)} / ${pctS(c.maxup)}</b><span class="small muted">worst / best ${esc(t.ticker)} move · marked P&amp;L recorded from mid-Oct 2026</span>`;
  $("jnDetailBody").innerHTML = `<div class="kv mini">
      <div><span class="lbl">Result</span><b class="${cls(t.pnl)}" style="font-size:20px">${money(t.pnl)}</b><span class="small muted">${pctS(t.ret)} of ${money(t.margin)} margin · comms ${money(t.comms)}</span></div>
      <div><span class="lbl">Days in trade</span><b>${t.dit ?? "–"}</b><span class="small muted">${day(t.entry_us)} → ${day(t.exit_us)} · ${t.dte ?? "–"} DTE at entry</span></div>
      <div><span class="lbl">Expiry</span><b>${esc(t.expiry)}</b><span class="small muted">${esc(t.ticker)}</span></div>
      <div><span class="lbl">P&amp;L fluctuation</span>${swing}</div>
      <div><span class="lbl">Entry conditions</span><b>VIX ${ok(c.vix) ? c.vix.toFixed(1) : "–"}</b><span class="small muted">VIX/VIX3M ${ok(c.ivts) ? c.ivts.toFixed(3) : "–"} (${esc(B.label)})${ok(c.vs_sma20) ? ` · ${esc(t.ticker)} ${pctS(c.vs_sma20)} vs 20-day avg` : ""}</span></div>
      <div><span class="lbl">Adjustments</span><b>${t.adjustments}</b><span class="small muted">${t.legs_n} leg rows in ONE</span></div>
    </div>
    <div class="jnedit"><span class="lbl">Learning note</span><textarea id="jnNote" rows="2" maxlength="300">${esc(t.note)}</textarea>
      <div class="row"><button type="button" id="jnSave">Save note</button><button type="button" class="ghost" id="jnAuto">Use the suggestion</button><span class="small muted" id="jnNoteMsg">${t.note_edited ? "your note" : "suggested from the data"}</span></div></div>
    <h3>${esc(t.ticker)} through the trade · solid = entry strikes · dotted = strikes added by adjustments · orange = adjustment days</h3><div class="chart" id="jnPath"></div>
    ${t.marked_path && t.marked_path.length > 1 ? `<h3 style="margin-top:8px">Marked P&amp;L at each session close</h3><div class="chart" id="jnMarked"></div>` : ""}
    <details style="margin-top:6px"><summary class="small">Legs (${t.legs.length})</summary><div class="tbl"><table><thead><tr><th>Opened</th><th>Side</th><th class="n">Qty</th><th>Contract</th><th class="n">Open</th><th>Closed</th><th class="n">Close</th><th class="n">Leg P&amp;L</th></tr></thead><tbody>${
      t.legs.map((l) => `<tr><td class="small">${day(l.open)}</td><td>${esc(l.side)}</td><td class="n">${l.qty}</td><td class="mono small">${esc(l.symbol)}</td><td class="n">${ok(l.open_px) ? l.open_px.toFixed(2) : "–"}</td><td class="small">${day(l.close)}</td><td class="n">${ok(l.close_px) ? l.close_px.toFixed(2) : "–"}</td><td class="n ${cls(l.pnl)}">${money(l.pnl)}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Leg P&amp;L is cash realised when each leg closed; adjustments often close a losing leg while its offsetting legs stay open, so a running total of it is not the trade's P&amp;L at that moment.</p></details>`;
  const save = async (note) => {
    await fetch("/api/journal/note", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key: t.key, note})});
    t.note = note || t.note_auto; t.note_edited = !!note; $("jnNote").value = t.note; $("jnNoteMsg").textContent = note ? "saved" : "suggestion restored";
  };
  $("jnSave").addEventListener("click", () => save($("jnNote").value.trim()));
  $("jnAuto").addEventListener("click", () => save(""));
  if (t.path && t.path.length > 1) {
    const v = t.path.map((p) => p.v), lo = Math.min(...v) * 0.9, hi = Math.max(...v) * 1.1, entry = new Set(t.entry_strikes || []);
    const refs = (t.strikes || []).filter((k) => k > lo && k < hi).map((k) => entry.has(k) ? {y: k, color: "var(--warn)", label: String(k)} : {y: k, color: "color-mix(in srgb, var(--warn) 35%, transparent)"});
    lineChart($("jnPath"), {label: "underlying path", h: 300, series: [{name: t.ticker, short: t.ticker, data: t.path, color: "var(--ink)", width: 2}],
      refs, fy: (x) => x.toFixed(0), ft: (x) => x.toFixed(2)});
    requestAnimationFrame(() => { const svg = $("jnPath").querySelector("svg"); if (!svg) return;
      const dates = t.path.map((p) => p.d), n = dates.length, W = svg.viewBox.baseVal.width, H = svg.viewBox.baseVal.height, mL = 44, mR = 70, pw = W - mL - mR;
      (t.adj_dates || []).forEach((d) => { const i = dates.indexOf(d); if (i < 0) return; const x = mL + i * pw / Math.max(n - 1, 1);
        svg.insertAdjacentHTML("beforeend", `<line x1="${x}" x2="${x}" y1="8" y2="${H - 22}" stroke="var(--accent)" stroke-width="1.2" opacity=".6"><title>adjusted ${d}</title></line>`); }); });
  } else $("jnPath").innerHTML = `<div class="state">No daily price history for ${esc(t.ticker)} in the desk (index trades only).</div>`;
  if (t.marked_path && t.marked_path.length > 1) lineChart($("jnMarked"), {label: "marked P&L", h: 170, series: [{name: "Marked P&L", short: "", data: t.marked_path, color: "var(--s1)", width: 1.8}], refs: [{y: 0}], fy: (x) => (x / 1000).toFixed(1) + "k", ft: (x) => money(x)});
}

/* ---------- load ---------- */
async function load() {
  $("jnList").innerHTML = `<div class="state">Reading the ONE report…</div>`;
  try {
    J = await api("/api/journal");
    if (!J.trades || !J.trades.length) { $("jnList").innerHTML = `<div class="state">No closed trades found. Export a ONE Summary Report to Documents.</div>`; return; }
    $("jnMeta").textContent = `from ${String(J.file || "").split(/[\\/]/).pop()}`;
    const opts = (k) => [...new Set(J.trades.map((t) => t[k]))].sort();
    const sel = (id, k, label) => { $(id).innerHTML = `<option value="">${label}</option>` + opts(k).map((v) => `<option>${esc(v)}</option>`).join(""); };
    sel("jnStrategy", "strategy", "all strategies"); sel("jnTicker", "ticker", "all tickers"); sel("jnGroup", "group", "all accounts");
    overview(J.trades); list();
  } catch (e) { $("jnList").innerHTML = `<div class="state err">${esc(e.message || e)}</div>`; }
}
[["jnStrategy", "strategy"], ["jnTicker", "ticker"], ["jnGroup", "group"], ["jnResult", "result"]].forEach(([id, k]) => $(id).addEventListener("change", () => { F[k] = $(id).value; list(); }));
$("jnSearch").addEventListener("input", () => { F.q = $("jnSearch").value; list(); });
$("jnSort").addEventListener("change", () => { SORT = $("jnSort").value; list(); });
window.loadJournal = load;
})();
