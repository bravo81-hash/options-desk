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

/* ---------- small SVG helpers ---------- */
function spark(t, W = 230, H = 54) {
  const P = t.path || [];
  if (P.length < 2) return `<div class="small muted" style="height:${H}px;display:flex;align-items:center">no price path (${esc(t.ticker)} not an index)</div>`;
  const vals = P.map((p) => p.v), ks = (t.strikes || []).filter((k) => k > Math.min(...vals) * 0.85 && k < Math.max(...vals) * 1.15);
  const lo = Math.min(...vals, ...ks), hi = Math.max(...vals, ...ks), X = (i) => 2 + i * (W - 4) / (P.length - 1), Y = (v) => H - 3 - (v - lo) * (H - 6) / ((hi - lo) || 1);
  const adj = new Set(t.adj_dates || []);
  let s = `<svg width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="display:block;height:${H}px">`;
  ks.forEach((k) => { s += `<line x1="0" x2="${W}" y1="${Y(k).toFixed(1)}" y2="${Y(k).toFixed(1)}" stroke="var(--warn)" stroke-width=".7" stroke-dasharray="3 3" opacity=".7"/>`; });
  P.forEach((p, i) => { if (adj.has(p.d)) s += `<line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="0" y2="${H}" stroke="var(--accent)" stroke-width=".8" opacity=".6"/>`; });
  s += `<polyline points="${P.map((p, i) => `${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ")}" fill="none" stroke="${(t.pnl || 0) >= 0 ? "var(--up)" : "var(--down)"}" stroke-width="1.6"/>`;
  return s + `</svg>`;
}
function swingBar(t) {
  const S = t.swing || {};
  if (ok(S.mae) && ok(S.mfe)) {
    const mx = Math.max(Math.abs(S.mae), Math.abs(S.mfe), Math.abs(t.pnl || 0), 1), w = (v) => 50 * Math.abs(v) / mx;
    return `<div class="swing" title="marked P&L at session closes: worst ${money(S.mae)}, best ${money(S.mfe)}, final ${money(t.pnl)} (${S.marked_days} closes recorded)">
      <span class="rstrack"><i style="left:${50 - w(S.mae)}%;width:${w(S.mae)}%;background:var(--down);opacity:.55"></i><i style="left:50%;width:${w(S.mfe)}%;background:var(--up);opacity:.55"></i><em></em>
      <b style="left:${50 + (t.pnl >= 0 ? 1 : -1) * w(t.pnl)}%"></b></span><span class="small muted">worst ${money(S.mae)} · best ${money(S.mfe)}</span></div>`;
  }
  const c = t.ctx || {};
  return `<div class="small muted" title="the desk records each open trade's marked P&L from mid-October; this trade closed before that">price swing: ${pctS(c.maxdn)} worst · ${pctS(c.maxup)} best</div>`;
}

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

/* ---------- trade cards ---------- */
function filtered() {
  return J.trades.filter((t) => (!F.strategy || t.strategy === F.strategy) && (!F.ticker || t.ticker === F.ticker) && (!F.group || t.group === F.group)
    && (!F.result || (F.result === "win" ? t.pnl > 0 : t.pnl <= 0)) && (!F.q || (t.name + " " + t.note + " " + t.trade_id).toLowerCase().includes(F.q.toLowerCase())));
}
function cards() {
  const T = filtered();
  $("jnCount").textContent = `${T.length} of ${J.trades.length} closed trades`;
  $("jnCards").innerHTML = T.map((t) => `<div class="jcard ${t.pnl > 0 ? "w" : "l"}" data-key="${esc(t.key)}">
    <div class="row" style="justify-content:space-between;gap:6px"><span><b class="mono">#${esc(t.trade_id)}</b> <span class="chip" style="color:${col(t.strategy)}">${esc(t.strategy)}</span> <b>${esc(t.ticker)}</b></span>
      <span class="big ${cls(t.pnl)}" style="font-size:17px">${money(t.pnl)} <span class="small">${pctS(t.ret)}</span></span></div>
    <div class="small muted" title="${esc(t.name)}">${esc(t.name)}</div>
    ${spark(t)}
    ${swingBar(t)}
    <div class="jmeta small"><span>${t.dit ?? "–"}d in trade</span><span>exp ${esc(t.expiry)}</span><span>${day(t.entry_us)} → ${day(t.exit_us)}</span><span>${t.adjustments} adj.</span><span>margin ${money(t.margin)}</span></div>
    <div class="jnote" title="click to edit your learning note">${t.note_edited ? "✎ " : "💡 "}${esc(t.note)}</div>
  </div>`).join("") || `<div class="state">No closed trades match.</div>`;
  $("jnCards").querySelectorAll(".jcard").forEach((c) => {
    c.addEventListener("click", (e) => { if (e.target.closest(".jnote")) return; detail(c.dataset.key); });
    c.querySelector(".jnote").addEventListener("click", () => editNote(c.dataset.key, c.querySelector(".jnote")));
  });
}
function editNote(key, el) {
  const t = J.trades.find((x) => x.key === key);
  el.innerHTML = `<input type="text" value="${esc(t.note)}" style="width:100%" maxlength="300"><div class="small muted">Enter to save · empty + Enter restores the suggestion · Esc to cancel</div>`;
  const inp = el.querySelector("input"); inp.focus(); inp.select();
  inp.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { cards(); return; }
    if (e.key !== "Enter") return;
    const note = inp.value.trim();
    await fetch("/api/journal/note", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key, note})});
    t.note = note || t.note_auto; t.note_edited = !!note; cards();
  });
}

/* ---------- detail pop-up ---------- */
function detail(key) {
  const t = J.trades.find((x) => x.key === key); if (!t) return;
  $("jnDetail").hidden = false;
  const c = t.ctx || {}, B = ivtsBand(c.ivts);
  $("jnDetailTitle").textContent = `#${t.trade_id} · ${t.name}`;
  $("jnDetailBody").innerHTML = `<div class="kv mini">
      <div><span class="lbl">Result</span><b class="${cls(t.pnl)}">${money(t.pnl)}</b><span class="small muted">${pctS(t.ret)} of ${money(t.margin)} margin · comms ${money(t.comms)}</span></div>
      <div><span class="lbl">Held</span><b>${t.dit ?? "–"} days</b><span class="small muted">${day(t.entry_us)} → ${day(t.exit_us)} · ${t.dte ?? "–"} DTE at entry · exp ${esc(t.expiry)}</span></div>
      <div><span class="lbl">Entry conditions</span><b>VIX ${ok(c.vix) ? c.vix.toFixed(1) : "–"}</b><span class="small muted">VIX/VIX3M ${ok(c.ivts) ? c.ivts.toFixed(3) : "–"} (${esc(B.label)}) · ${ok(c.vs_sma20) ? `${t.ticker} ${pctS(c.vs_sma20)} vs 20-day avg` : ""}</span></div>
      <div><span class="lbl">${esc(t.ticker)} during the trade</span><b class="${cls(c.move)}">${pctS(c.move)}</b><span class="small muted">worst ${pctS(c.maxdn)} · best ${pctS(c.maxup)}</span></div>
      <div><span class="lbl">Adjustments</span><b>${t.adjustments}</b><span class="small muted">${t.legs_n} leg rows in ONE</span></div>
    </div>
    <div class="jnote" style="margin:8px 0">💡 ${esc(t.note)}</div>
    <h3>${esc(t.ticker)} price through the trade · dashed = your strikes · orange = adjustment days</h3><div class="chart" id="jnPath"></div>
    ${t.marked_path && t.marked_path.length > 1 ? `<h3 style="margin-top:8px">Marked P&amp;L at each session close (recorded by the desk)</h3><div class="chart" id="jnMarked"></div>` : `<p class="note">Marked P&amp;L path: the desk records each open trade's P&amp;L at every session close from mid-October 2026; this trade has ${t.swing.marked_days || 0} recorded closes.</p>`}
    <h3 style="margin-top:8px">Legs (from ONE)</h3>
    <div class="tbl"><table><thead><tr><th>Opened</th><th>Side</th><th class="n">Qty</th><th>Contract</th><th class="n">Open</th><th>Closed</th><th class="n">Close</th><th class="n">P&amp;L</th></tr></thead><tbody>${
      t.legs.map((l) => `<tr><td class="small">${day(l.open)}</td><td>${esc(l.side)}</td><td class="n">${l.qty}</td><td class="mono small">${esc(l.symbol)}</td><td class="n">${ok(l.open_px) ? l.open_px.toFixed(2) : "–"}</td><td class="small">${day(l.close)}</td><td class="n">${ok(l.close_px) ? l.close_px.toFixed(2) : "–"}</td><td class="n ${cls(l.pnl)}">${money(l.pnl)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">Leg P&amp;L is realised cash when each leg closed: adjustments often close a losing leg while its offsetting legs stay open, so the running cash total is not the trade's P&amp;L at that moment.</p>`;
  if (t.path && t.path.length > 1) {
    const ks = (t.strikes || []).filter((k) => { const v = t.path.map((p) => p.v); return k > Math.min(...v) * 0.88 && k < Math.max(...v) * 1.12; });
    lineChart($("jnPath"), {label: "underlying path", h: 220, series: [{name: t.ticker, short: t.ticker, data: t.path, color: "var(--ink)", width: 1.8}],
      refs: ks.map((k) => ({y: k, color: "var(--warn)", label: String(k)})), fy: (v) => v.toFixed(0), ft: (v) => v.toFixed(2)});
    // adjustment markers
    requestAnimationFrame(() => { const svg = $("jnPath").querySelector("svg"); if (!svg) return; const dates = t.path.map((p) => p.d), n = dates.length, W = svg.viewBox.baseVal.width, mL = 44, mR = 70, pw = W - mL - mR;
      (t.adj_dates || []).forEach((d) => { const i = dates.indexOf(d); if (i < 0) return; const x = mL + i * pw / Math.max(n - 1, 1);
        svg.insertAdjacentHTML("beforeend", `<line x1="${x}" x2="${x}" y1="8" y2="${svg.viewBox.baseVal.height - 22}" stroke="var(--accent)" stroke-width="1" opacity=".55"/>`); }); });
  } else $("jnPath").innerHTML = `<div class="state">No daily price history for ${esc(t.ticker)} in the desk (index trades only).</div>`;
  if (t.marked_path && t.marked_path.length > 1) lineChart($("jnMarked"), {label: "marked P&L", h: 160, series: [{name: "Marked P&L", short: "", data: t.marked_path, color: "var(--s1)", width: 1.8}], refs: [{y: 0}], fy: (v) => (v / 1000).toFixed(1) + "k", ft: (v) => money(v)});
}

/* ---------- load ---------- */
async function load() {
  $("jnCards").innerHTML = `<div class="state">Reading the ONE report…</div>`;
  try {
    J = await api("/api/journal");
    if (!J.trades || !J.trades.length) { $("jnCards").innerHTML = `<div class="state">No closed trades found. Export a ONE Summary Report to Documents.</div>`; return; }
    $("jnMeta").textContent = `from ${String(J.file || "").split(/[\\/]/).pop()}`;
    const opts = (k) => [...new Set(J.trades.map((t) => t[k]))].sort();
    const sel = (id, k, label) => { $(id).innerHTML = `<option value="">${label}</option>` + opts(k).map((v) => `<option>${esc(v)}</option>`).join(""); };
    sel("jnStrategy", "strategy", "all strategies"); sel("jnTicker", "ticker", "all tickers"); sel("jnGroup", "group", "all accounts");
    overview(J.trades); cards();
  } catch (e) { $("jnCards").innerHTML = `<div class="state err">${esc(e.message || e)}</div>`; }
}
[["jnStrategy", "strategy"], ["jnTicker", "ticker"], ["jnGroup", "group"], ["jnResult", "result"]].forEach(([id, k]) => $(id).addEventListener("change", () => { F[k] = $(id).value; cards(); }));
$("jnSearch").addEventListener("input", () => { F.q = $("jnSearch").value; cards(); });
window.loadJournal = load;
})();
