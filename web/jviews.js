/* Journal views built on whole positions: Table, Edge, Confidence, Discipline, Risk taken, Behaviour, Review, Settings.
   Numbers come from web/jstats.js on the book in /api/journal. Information only: nothing here reads into sizing, gates or orders. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const St = window.JStats;
const RO = !!window.DESK_CLOUD;  // the cloud copy reads a snapshot: nothing can be saved there
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const R = (v, d = 2) => ok(v) ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}R` : "–";
const pc = (v, d = 0) => ok(v) ? `${(100 * v).toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const x2 = (v, d = 2) => ok(v) ? `${v.toFixed(d)}×` : "–";
const day = (iso) => iso ? new Date(iso.length > 10 ? iso : iso + "T12:00:00").toLocaleDateString([], {day: "numeric", month: "short", year: "2-digit"}) : "–";
const tile = (l, b, sub, k = "", tip = "") => `<div${tip ? ` title="${esc(tip)}"` : ""}><span class="lbl">${l}</span><b class="${k}">${b}</b><span class="small muted">${sub}</span></div>`;
const PAL = {A14: "var(--s1)", TimeEdge: "var(--s2)", TimeZone: "var(--s3)", "Triple Cal": "var(--s4)", Flyagonal: "var(--accent)", Allantis: "var(--warn)", IF: "var(--info)", M200: "var(--muted)", Other: "var(--faint)"};
const col = (s) => PAL[s] || "var(--faint)";
const stars = (d) => `<b class="${d.pnl > 0 ? "pos" : "neg"}">${R(d.r)}</b>`;
let J = null, open = null, D = [], ROWS = [], ALL = false, TSORT = {k: "entry", dir: -1}, REVIEW = null, BT = null;
let F = {strategy: "", acct: "", vix: "", dte: "", from: "", to: ""};
const FILTERED = ["Table", "Edge", "Confidence", "Discipline", "Risk taken", "Behaviour"];

async function post(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const out = await r.json().catch(() => ({}));
  if (!r.ok || out.ok === false) throw new Error(out.error || `could not save (${r.status})`);
  return out;
}
const saved = async (msg) => { if (msg) msg.textContent = "saved"; await window.loadJournal(); };

function match(r) {
  return (!F.strategy || r.strategy === F.strategy) && (!F.acct || r.acct === F.acct) && (!F.vix || St.bucket(r.vix, St.VIX) === F.vix) && (!F.dte || St.bucket(r.dte0, St.DTE) === F.dte)
    && (!F.from || (r.exit_us || r.entry_us) >= F.from) && (!F.to || (r.exit_us || r.entry_us) <= F.to);
}

/* ---------- Table ---------- */
const COLS = [["entry", "Entered", (r) => r.entry], ["trade", "Trade", (r) => r.ticker], ["strategy", "Strategy", (r) => r.strategy], ["acct", "Account", (r) => r.acct], ["pnl", "P&L", (r) => r.pnl], ["r", "R", (r) => r.r],
  ["risk0", "1R", (r) => r.risk0], ["creep", "Peak ÷ 1R", (r) => r.creep], ["adj", "Adj", (r) => r.adj], ["dit", "Days", (r) => r.dit], ["rod", "%/risk-day", (r) => r.rod], ["plan_pct", "Planned %", (r) => r.plan_pct], ["followed", "Rules", (r) => r.followed_ever]];
function flags(r) {
  const c = [];
  if (r.open) c.push(`<span class="chip">open</span>`);
  if (r.rolls) c.push(`<span class="chip" title="a losing trade reopened within the hour: joined into one position">rolled</span>`);
  if (r.extreme && r.extreme.length) c.push(`<span class="chip wrn" title="needs a post-mortem">⚠ review</span>`);
  if (r.revenge) c.push(`<span class="chip wrn" title="entered soon after a loss, bigger than usual or in the same ticker">⚠ revenge</span>`);
  if (r.hot) c.push(`<span class="chip" title="${r.streak} straight wins before this entry">streak ${r.streak}</span>`);
  if (!r.capped) c.push(`<span class="chip wrn" title="more calls short than long at entry: the loss has no ceiling, 1R stops at twice the top strike">⚠ uncapped</span>`);
  return c.join(" ");
}
function table() {
  const c = COLS.find((x) => x[0] === TSORT.k), val = c[2];
  const rows = [...ROWS].sort((a, b) => { const x = val(a), y = val(b); if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * TSORT.dir; });
  $("jeTable").innerHTML = `<div class="tbl"><table><thead><tr>${COLS.map(([k, l], i) => `<th class="${i > 3 && k !== "followed" ? "n" : ""}"><button type="button" class="thsort" data-k="${k}" aria-sort="${TSORT.k === k ? (TSORT.dir > 0 ? "ascending" : "descending") : "none"}">${l}${TSORT.k === k ? (TSORT.dir > 0 ? " ▴" : " ▾") : ""}</button></th>`).join("")}<th>Flags</th></tr></thead><tbody>${
    rows.map((r) => `<tr class="jtr" data-key="${esc(r.key)}" tabindex="0"><td class="small">${day(r.entry_us)}</td><td><span class="mono small">#${esc(r.trade_id)}</span> <b>${esc(r.ticker)}</b></td><td><i class="dot" style="background:${col(r.strategy)}"></i>${esc(r.strategy)}</td><td class="small">${esc(r.acct)}</td>
      <td class="n ${cls(r.pnl)}">${money(r.pnl)}</td><td class="n ${cls(r.r)}">${R(r.r)}</td><td class="n">${money(r.risk0)}</td><td class="n ${r.creep > J.settings.creep_x ? "wrn" : ""}">${x2(r.creep, 1)}</td><td class="n">${r.adj}</td><td class="n">${r.dit ?? "–"}</td><td class="n ${cls(r.rod)}">${ok(r.rod) ? fmt(r.rod, 2) + "%" : "–"}</td>
      <td class="n ${r.plan_pct > J.settings.cap_pct ? "wrn" : ""}">${ok(r.plan_pct) ? fmt(r.plan_pct, 2) + "%" : `<span class="muted" title="no card stop">–</span>`}</td><td class="small">${r.followed_ever == null ? `<span class="muted">not scored</span>` : r.followed_ever ? "kept" : `<span class="wrn">broken</span>`}</td><td>${flags(r)}</td></tr>`).join("") || `<tr><td colspan="14"><div class="state">No positions match these filters.</div></td></tr>`}</tbody></table></div>`;
  $("jeTable").querySelectorAll(".thsort").forEach((b) => b.addEventListener("click", () => { const k = b.dataset.k; TSORT = {k, dir: TSORT.k === k ? -TSORT.dir : k === "strategy" || k === "trade" || k === "acct" ? 1 : -1}; table(); }));
  $("jeTable").querySelectorAll(".jtr").forEach((n) => { const go = () => { const row = J.book.find((x) => x.key === n.dataset.key); if (!row.open) open(row.keys); }; n.addEventListener("click", go); n.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); });
}

/* ---------- Edge ---------- */
function capitalBase() {
  const first = {};
  ROWS.forEach((r) => { if (!first[r.acct] || r.entry < first[r.acct].entry) first[r.acct] = r; });
  return St.sum(Object.values(first).map((r) => r.nav || 0)) || null;
}
function edge() {
  const k = St.kpi(D), c = St.curve(D, capitalBase());
  if (!k.n) { $("jeKpi").innerHTML = `<div class="state">No closed decisions match these filters.</div>`; ddChart($("jeCurve"), {points: []}); histChart($("jeHist"), {bins: []}); $("jeCurveSub").textContent = ""; $("jeHistSub").textContent = ""; $("jeRecover").textContent = ""; $("jeSkew").textContent = ""; return; }
  const gap = k.mean - k.median;
  $("jeKpi").innerHTML = tile("Decisions", k.n, `${k.wins} won · ${k.losses} lost · twins once`) +
    tile("Win rate", pc(k.win), `80% range ${pc(k.ci[0])}–${pc(k.ci[1])}`) +
    tile("Avg win / loss", `<span class="pos">${R(k.avgWin)}</span> / <span class="neg">${R(-k.avgLoss)}</span>`, `${money(k.avgWinUsd)} / ${money(k.avgLossUsd)}`) +
    tile("Payoff", x2(k.payoff), "avg win ÷ avg loss") +
    tile("Expectancy", R(k.expR), `${money(k.expUsd)} a decision`, cls(k.expR)) +
    tile("Total", R(k.totalR, 1), money(k.totalUsd), cls(k.totalR)) +
    tile("Mean / median", `${R(k.mean)} / ${R(k.median)}`, gap < -0.005 ? "big losses pull the mean" : gap > 0.005 ? "big wins lift the mean" : "about equal") +
    tile("Std dev", R(k.sd).replace("+", ""), `CV ${fmt(k.cv, 1)}: spread ÷ mean`) +
    tile("Skew", fmt(k.skew, 2), `${pc(k.tail)} lost over 0.5R`, "muted") +
    tile("Profit factor", fmt(k.pf, 2), "wins ÷ losses in R") +
    tile("SQN", fmt(k.sqn, 2), "mean ÷ std dev × √decisions") +
    tile("Biggest win", `<span class="pos">${R(k.bestR)}</span>`, money(k.bestUsd)) +
    tile("Biggest loss", `<span class="neg">${R(k.worstR)}</span>`, money(k.worstUsd)) +
    tile("Biggest loss ÷ avg", x2(k.worstOverAvg, 1), `review line ${J.settings.extreme_x}×`) +
    tile("Biggest win ÷ loss", x2(k.bestOverWorst), "in R") +
    tile("Return on risk-days", ok(k.rod) ? fmt(k.rod, 2) + "%" : "–", "P&L ÷ (risk held × days)", cls(k.rod), "Each span of a trade counts the worst case it carried at that moment. This is the pace measure that doesn't flatter a trade that grew.");
  ddChart($("jeCurve"), {label: "cumulative R", h: 250, unit: "R", points: c.pts.map((p) => ({d: p.d, v: p.v, peak: p.peak, tip: `<div>${esc(p.title.ticker)} ${esc(p.title.strategy)} · closed ${esc(p.d)}</div><div>${R(p.title.r)} · ${money(p.title.pnl)}</div><div>Running total <b>${R(p.v)}</b></div>${p.v < p.peak ? `<div>${R(p.v - p.peak)} from the high</div>` : ""}`}))});
  $("jeCurveSub").textContent = `max drawdown ${R(c.mddR, 1)}${ok(c.mddP) ? ` (${fmt(c.mddP, 1)}% of capital)` : ""} · now ${c.ddNow < -0.005 ? R(c.ddNow, 1) + " from the high" : "at the high"}`;
  $("jeRecover").innerHTML = `${c.mddP ? `Your deepest drawdown, ${fmt(Math.abs(c.mddP), 1)}% of capital, needed +${fmt(c.recover, 1)}% to get back. ` : ""}A 10% loss needs +11.1%, 20% needs +25%, 30% needs +42.9%, 50% needs +100%. The % is on the capital in these accounts at the first entry shown, in USD.`;
  histChart($("jeHist"), {label: "R per decision", h: 250, unit: "R", bins: St.hist(D.filter((d) => ok(d.r)).map((d) => d.r)), lines: [{x: k.mean, label: `mean ${R(k.mean)}`, color: "var(--accent)"}, {x: k.median, label: `median ${R(k.median)}`, color: "var(--warn)", dash: "4 3"}]});
  $("jeHistSub").textContent = `skew ${fmt(k.skew, 2)} · ${k.n} decisions`;
  $("jeSkew").innerHTML = `Short-premium books skew negative by nature: many small wins, rare big losses. So skew stays grey here, and a mild reading isn't a clean bill of health: it can mean the tail hasn't landed yet. Confidence sets it beside the since-2009 model.`;
}

/* ---------- Confidence ---------- */
const rangeBar = (v, lo, hi, cfg) => bulletSvg(v, {w: 110, lo: cfg.lo, hi: cfg.hi, color: "var(--accent)", label: cfg.label, zones: [{from: lo, to: hi, color: "var(--accent)"}], marks: cfg.marks});
const pass = (yes, txt) => yes ? `<span class="chip pos">✓ ${txt}</span>` : `<span class="small muted">${txt}</span>`;
function confidence() {
  const cfg = J.settings, g = {};
  D.forEach((d) => { if (ok(d.r)) (g[d.strategy] = g[d.strategy] || []).push(d); });
  const rows = Object.entries(g).sort((a, b) => b[1].length - a[1].length).map(([s, v]) => ({s, c: St.confidence(v, F.from || F.to || F.vix || F.dte || F.acct ? null : (J.history || {})[s], cfg)}));
  const mR = Math.max(0.3, ...rows.flatMap(({c}) => c.meanCi.map((v) => Math.abs(v || 0))));
  $("jeConf").innerHTML = `<div class="tbl"><table><thead><tr><th>Strategy</th><th>Decisions</th><th title="ONE's losing decisions plus OptionStrat's before June, which have a result but no legs, so no R">Losses (ONE + before) against ${cfg.loss_bar}</th><th>Win rate</th><th>Mean R</th><th class="n">SQN</th><th class="n" title="Profit factor: wins ÷ losses in R">PF</th><th title="Spread ÷ mean. A strategy that loses never passes: CV only measures spread around the mean">CV &lt; ${cfg.cv_max}</th><th title="Short premium normally reads negative, so this rarely passes">Skew &gt; ${cfg.skew_min}</th><th title="The bottom of the mean's 80% range sits above zero">Range &gt; 0R</th></tr></thead><tbody>${
    rows.map(({s, c}) => `<tr><td><i class="dot" style="background:${col(s)}"></i>${esc(s)}</td><td>${nTag(c.n)}</td>
      <td>${hBarSvg(c.lossesAll, cfg.loss_bar, {zeroLeft: true, w: 80, color: "var(--accent)", label: "losses against the bar"})} <span class="mono small">${c.losses}${c.prior.losses ? ` + ${c.prior.losses}` : ""}</span> <span class="small muted">${c.barOk ? "bar reached" : ok(c.more) && c.more ? `~${c.more} more` : ""}</span></td>
      <td>${rangeBar(100 * c.win, 100 * c.ci[0], 100 * c.ci[1], {lo: 0, hi: 100, label: `${pc(c.win)} · ${pc(c.ci[0])} to ${pc(c.ci[1])}`})} <span class="mono small">${pc(c.ci[0])}–${pc(c.ci[1])}</span></td>
      <td>${ok(c.meanCi[0]) ? rangeBar(c.mean, c.meanCi[0], c.meanCi[1], {lo: -mR, hi: mR, label: `${R(c.mean)} · ${R(c.meanCi[0])} to ${R(c.meanCi[1])}`, marks: [{v: 0, color: "var(--ink)", label: "0R"}]}) : ""} <span class="mono small ${cls(c.mean)}">${R(c.mean)}</span></td>
      <td class="n">${fmt(c.sqn, 2)}</td><td class="n">${fmt(c.pf, 2)}</td><td>${pass(c.cvOk, c.mean > 0 ? fmt(c.cv, 1) : "mean ≤ 0")}</td><td>${pass(c.skewOk, fmt(c.skew, 2))}</td><td>${pass(c.ciOk, ok(c.meanCi[0]) ? R(c.meanCi[0]) : "–")}</td></tr>`).join("") || `<tr><td colspan="10"><div class="state">No closed decisions match these filters.</div></td></tr>`}</tbody></table></div>`;
  const tiny = (id, list) => { $(id).innerHTML = list.length ? `<div class="tbl"><table><thead><tr><th></th><th class="n">n</th><th class="n">Won</th><th class="n">Mean R</th></tr></thead><tbody>${list.map((b) => `<tr><td class="small">${esc(b.label)}</td><td class="n">${nTag(b.n)}</td><td class="n">${pc(b.win)}</td><td class="n ${cls(b.mean)}">${R(b.mean)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="state">Nothing here.</div>`; };
  tiny("jeByVix", St.groupBy(D, (d) => St.bucket(d.vix, St.VIX), St.VIX.map((b) => b[0])));
  tiny("jeByBand", St.groupBy(D, (d) => ok(d.ivts) ? ivtsBand(d.ivts).band : null, ["steep", "normal", "flat", "backwardation"]));
  tiny("jeByDte", St.groupBy(D, (d) => St.bucket(d.dte0, St.DTE), St.DTE.map((b) => b[0])));
  tiny("jeByAdj", St.groupBy(D, (d) => St.bucket(d.adj, St.ADJ), St.ADJ.map((b) => b[0])));
  tail();
}
function tail() {
  const a14 = D.filter((d) => d.strategy === "A14" && ok(d.r)), big = a14.filter((d) => d.r < -0.5).length;
  const rows = BT && BT.a14 ? (BT.a14.SPX || []).filter((r) => [21, 45].includes(r.dte) && r.nostop) : [];
  const model = rows.map((r) => `${pc(r.nostop.big_loss, 1)} of trades at ${r.dte} DTE`).join(" and "), hit = rows.map((r) => a14.length * r.nostop.big_loss);
  $("jeTail").innerHTML = !a14.length || !rows.length ? "" : `<div class="small" style="margin-top:8px"><b>Tail check, A14:</b> ${big} of ${a14.length} decisions here lost over half their risk. The since-2009 SPX model with no stop did that on ${esc(model)}, so ${fmt(Math.min(...hit), 1)} to ${fmt(Math.max(...hit), 1)} would be expected in ${a14.length}.</div>
    <p class="note">This sample covers one calm stretch, so an unseen tail is the main thing it can't show. The model's rate comes from Evidence, Since 2009, with no stop and on margin; yours is on entry risk, so read them as the same order of size, not the same number.</p>`;
}

/* ---------- Discipline ---------- */
function discipline() {
  const a = St.accuracy(D, ALL), P = J.plan || {calls: []}, acted = P.calls.filter((c) => c.done), S = J.rules_from;
  $("jdStrip").innerHTML = tile("Rule accuracy", pc(a.accuracy), a.scored ? `${a.kept.n} of ${a.scored} scored decisions kept every rule` : "nothing scored yet") +
    tile("Win rate, same decisions", a.scored ? pc((a.kept.n * (a.kept.win || 0) + a.broke.n * (a.broke.win || 0)) / a.scored) : "–", "judge yourself on the first number") +
    tile("Rules kept", R(a.kept.mean), `${money(a.kept.pnl)} · ${a.kept.n} decisions ${nTag(a.kept.n)}`, cls(a.kept.mean)) +
    tile("Rules broken", R(a.broke.mean), `${money(a.broke.pnl)} · ${a.broke.n} decisions ${nTag(a.broke.n)}`, cls(a.broke.mean)) +
    tile("Not scored", a.unscored, "no card, or the rule came later") +
    tile("Exit and Close calls", P.calls.length ? `${acted.length} of ${P.calls.length}` : "–", P.sessions ? `acted on · ${P.sessions} sessions logged` : "logged from today, when Trade plan opens") +
    tile("Adjustments against the gate", ok(P.adj_against) && P.adj_against + P.adj_allowed ? `${P.adj_against} of ${P.adj_against + P.adj_allowed}` : "–", "made while Adjust? said no");
  const empty = !a.scored && !ALL ? `<div class="state">Nothing has closed since the rules began, so nothing is scored yet. Tick the box above to see the older trades scored in hindsight.</div>` : "";
  $("jdRules").innerHTML = `${empty}<div class="tbl"><table><thead><tr><th>Rule</th><th title="kept against broken"></th><th class="n">Kept</th><th class="n">Broken</th><th class="n">Kept: mean R</th><th class="n">Broken: mean R</th><th class="n">Broken: P&amp;L</th></tr></thead><tbody>${
    a.rules.map((r) => `<tr><td>${esc(r.label)}</td><td>${segBar([{n: r.kept.n, color: "var(--accent)", label: "kept"}, {n: r.broke.n, color: "var(--warn)", label: "broken"}], {w: 90})}</td><td class="n">${r.kept.n}</td><td class="n">${r.broke.n}</td><td class="n ${cls(r.kept.mean)}">${R(r.kept.mean)}</td><td class="n ${cls(r.broke.mean)}">${R(r.broke.mean)}</td><td class="n ${cls(r.broke.pnl)}">${r.broke.n ? money(r.broke.pnl) : "–"}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">${ALL ? `Shown as if every rule had always existed. That's hindsight: most of these rules were written after, and partly from, the trades they score.` : `A rule only counts from the day it began: cards ${day(S.card)}, entry gates ${day(S.gate)}, cap ${day(S.cap)}. A card's stop is read as the card reads it, on ONE's %. Trades with no card stay unscored. A14's adjustment gates need the log kept at the time, so they're scored in the Adjustments tile instead.`}</p>`;
  overrides();
}
const decLabel = (d) => `${day(d.entry_us)} ${d.ticker} ${d.strategy}`;
function overrides() {
  const O = (J.manual.journal_overrides || []).slice().sort((a, b) => (b.updated || "").localeCompare(a.updated || "")), by = new Map(J.decisions.map((d) => [d.decision, d]));
  const linked = O.map((o) => by.get(o.decision)).filter((d) => d && ok(d.r)), others = J.decisions.filter((d) => ok(d.r) && !linked.includes(d));
  $("jdOverrides").innerHTML = `${O.length ? `<div class="tbl"><table><thead><tr><th>Trade</th><th>Why</th><th>Rule set aside</th><th>The rules said</th><th class="n">Result</th><th></th></tr></thead><tbody>${O.map((o) => { const d = by.get(o.decision);
    return `<tr><td class="small">${d ? esc(decLabel(d)) : "–"}</td><td class="small"><span class="chip">${esc(o.kind)}</span> ${esc(o.why)}</td><td class="small">${esc(o.rule)}</td><td class="small">${esc(o.rules_said)}</td><td class="n ${d ? cls(d.r) : ""}">${d ? R(d.r) : "–"}</td><td>${RO ? "" : `<button type="button" class="ghost ovDel" data-id="${esc(o.id)}">Remove</button>`}</td></tr>`; }).join("")}</tbody></table></div>
    <p class="note">Overrides averaged ${R(St.mean(linked.map((d) => d.r)))} on ${linked.length} closed decisions, everything else ${R(St.mean(others.map((d) => d.r)))} on ${others.length}. ${nTag(linked.length)}</p>` : `<div class="state">No overrides logged. Add one when you step outside the rules for news or a hunch.</div>`}
    ${RO ? "" : `<form class="row ovForm" id="ovForm" onsubmit="return false" style="margin-top:8px"><select id="ovDec" aria-label="Trade">${[...J.decisions].reverse().slice(0, 40).map((d) => `<option value="${esc(d.decision)}">${esc(decLabel(d))}</option>`).join("")}</select>
      <select id="ovKind" aria-label="Kind"><option value="news">news</option><option value="hunch">hunch</option><option value="other">other</option></select>
      <input type="text" id="ovRule" placeholder="rule set aside" maxlength="120" style="max-width:170px"><input type="text" id="ovWhy" placeholder="why" maxlength="300" style="max-width:220px"><input type="text" id="ovSaid" placeholder="what the rules said to do" maxlength="120" style="max-width:190px">
      <button type="button" id="ovAdd">Log it</button><span class="small muted" id="ovMsg"></span></form>`}`;
  if (RO) return;
  $("ovAdd").addEventListener("click", async () => { try { await post("/api/journal/override", {decision: $("ovDec").value, kind: $("ovKind").value, rule: $("ovRule").value, why: $("ovWhy").value, rules_said: $("ovSaid").value}); await saved(); } catch (e) { $("ovMsg").textContent = e.message; } });
  $("jdOverrides").querySelectorAll(".ovDel").forEach((b) => b.addEventListener("click", async () => { await post("/api/journal/override/delete", {id: b.dataset.id}); await saved(); }));
}

/* ---------- Risk taken ---------- */
function risk() {
  const cfg = J.settings, A = ROWS.filter((r) => ok(r.plan_pct)), none = ROWS.filter((r) => !ok(r.plan_pct)), med = St.median(A.map((r) => r.plan_pct)), over = A.filter((r) => r.plan_pct > cfg.cap_pct), warn = A.filter((r) => r.plan_pct > cfg.cap_warn_pct && r.plan_pct <= cfg.cap_pct);
  const wc = ROWS.map((r) => r.risk_pct).filter(ok), crept = ROWS.filter((r) => r.creep > cfg.creep_x), triple = ROWS.filter((r) => r.creep > 3);
  $("jrStrip").innerHTML = tile("Planned loss at entry", ok(med) ? fmt(med, 2) + "%" : "–", `median, of account NAV · ${A.length} trades with a card stop`) +
    tile(`Over ${cfg.cap_warn_pct}%`, warn.length, `between your warning and cap`, warn.length ? "wrn" : "") +
    tile(`Over ${cfg.cap_pct}%`, over.length, "above the cap", over.length ? "wrn" : "") +
    tile("Worst case at entry", ok(St.median(wc)) ? fmt(St.median(wc), 1) + "%" : "–", "median: why the cap is set on planned loss") +
    tile("No card stop", none.length, "left out of planned loss, as you chose") +
    tile("Risk added after entry", ok(St.median(ROWS.map((r) => r.creep))) ? x2(St.median(ROWS.map((r) => r.creep))) : "–", `median peak ÷ 1R · ${crept.length} over ${cfg.creep_x}×, ${triple.length} over 3×`, crept.length ? "wrn" : "");
  const lim = [cfg.cap_warn_pct / 2, cfg.cap_warn_pct, cfg.cap_pct], names = [`under ${lim[0]}%`, `${lim[0]}–${lim[1]}%`, `${lim[1]}–${lim[2]}%`, `over ${lim[2]}%`];
  const buckets = names.map((label, i) => ({label, v: A.filter((r) => r.plan_pct > (i ? lim[i - 1] : -1) && r.plan_pct <= (i < 3 ? lim[i] : 1e9)).length, color: i < 2 ? "var(--accent)" : "var(--warn)"}));
  barChart($("jrCap"), {label: "planned loss at entry, trades in each band", h: 170, unit: "", items: buckets.map((b) => ({...b, title: `${esc(b.label)} of NAV: <b>${b.v}</b> trades`}))});
  scatter($("jrCreep"), {label: "peak risk against result", h: 170, xLabel: "peak risk ÷ 1R →", vline: cfg.creep_x, points: ROWS.filter((r) => ok(r.r)).map((r) => ({x: Math.min(r.creep, 6), y: r.r, color: col(r.strategy), r: 4, title: `<b>#${esc(r.trade_id)} ${esc(r.name)}</b><br>peak ${x2(r.creep, 1)} entry risk · ${R(r.r)} · ${money(r.pnl)}<br>${r.adj} adjustments`}))});
  const accts = Object.keys(J.heat || {}).filter((a) => J.heat[a].length);
  $("jrHeatHost").innerHTML = accts.map((a) => `<div style="flex:1;min-width:0"><div class="small muted" id="jrHeatT-${esc(a)}"></div><div class="chart" id="jrHeat-${esc(a)}"></div></div>`).join("") || `<div class="state">No capital history yet: run Update all so the AUD/USD closes come in.</div>`;
  accts.forEach((a) => { const pts = J.heat[a], top = pts.reduce((m, p) => (p.plan > m.plan ? p : m), pts[0]), wc2 = pts.reduce((m, p) => (p.risk > m.risk ? p : m), pts[0]);
    $(`jrHeatT-${a}`).innerHTML = `<b>${esc(a)}</b> · high ${fmt(top.plan, 1)}% planned on ${esc(shortDate(top.d))} · worst case peaked at ${fmt(wc2.risk, 0)}% of NAV`;
    lineChart($(`jrHeat-${a}`), {label: `open risk ${a}`, h: 145, mR: 44, series: [{name: "Open planned loss, % of NAV", short: "", data: pts.map((p) => ({d: p.d, v: p.plan})), color: "var(--s1)", width: 2}, {name: "Open positions", short: "", data: pts.map((p) => ({d: p.d, v: p.n})), color: "var(--faint)", width: 1.2, dash: "3 3"}], fy: (v) => v.toFixed(0)}); });
  tickets();
}
function tickets() {
  const T = (J.manual.journal_tickets || []).slice().sort((a, b) => b.created.localeCompare(a.created)).slice(0, 8), link = new Map(J.book.filter((r) => r.ticket).map((r) => [r.ticket.ticket, r]));
  $("jrTickets").innerHTML = T.length ? `<div class="tbl"><table><thead><tr><th>Written</th><th>Trade</th><th class="n">Planned</th><th class="n">% of NAV</th><th>Filled</th></tr></thead><tbody>${T.map((t) => { const r = link.get(t.id);
    return `<tr><td class="small">${day(t.created)}</td><td>${esc(t.ticker)} ${esc(t.strategy)} <span class="small muted">${esc(t.account || "")}</span></td><td class="n">${money(t.plan ?? t.worst)}</td><td class="n">${t.nav ? fmt(100 * (t.plan ?? t.worst) / t.nav, 2) + "%" : "–"}</td><td class="small">${r ? (r.ticket.before_fill ? "✓ written before the fill" : `<span class="wrn">⚠ written after the fill</span>`) : `<span class="muted">not filled yet</span>`}</td></tr>`; }).join("")}</tbody></table></div>` : `<div class="state">No pre-commits yet. Write one before entering: the planned loss is accepted as gone at that point.</div>`;
}
/* the pop-up: what you can lose, as a share of the account, before the trade exists */
function preCommit() {
  const s = $("pcStrategy").value, card = (J.cards || {})[s] || {}, acct = $("pcAcct").value, worst = parseFloat($("pcWorst").value), nav = (J.nav_now || {})[acct], cfg = J.settings;
  const plan = ok(worst) && card.stop ? worst * card.stop / 100 : null, base = plan ?? worst, p = ok(base) && nav ? 100 * base / nav : null;
  $("pcStop").textContent = card.stop ? `Card stop ${card.stop}%` : "No card stop: the whole worst case is at stake";
  $("pcOut").innerHTML = !ok(worst) ? `<div class="state">Enter the worst case from the risk graph.</div>` : `<div class="kv mini">${tile("Accept this as gone", money(base), plan != null ? `${card.stop}% of the ${money(worst)} worst case` : "the worst case")}${tile("Share of the account", ok(p) ? fmt(p, 2) + "%" : "–", nav ? `of ${money(nav)} NAV` : "no NAV for this account", p > cfg.cap_pct ? "wrn" : "")}</div>${
    p > cfg.cap_pct ? `<div class="state" style="margin-top:6px">⚠ Over your ${cfg.cap_pct}% cap. The readiness bar still sets size; this only shows what this ticket risks.</div>` : p > cfg.cap_warn_pct ? `<div class="state" style="margin-top:6px">⚠ Over your ${cfg.cap_warn_pct}% warning line.</div>` : ""}`;
  $("pcChecks").innerHTML = [card.stop ? `Stop set at ${card.stop}% before entry` : null, card.time ? `Out by ${card.time} DTE` : null, card.adjust === "never" ? "No adjustments on this strategy" : card.adjust === "one" ? "One adjustment at most" : card.adjust === "gated" ? "Adjust only when the gate says so" : null, s === "A14" ? "Not in backwardation" : null, ["TimeEdge", "TimeZone", "Triple Cal"].includes(s) ? "Calendar gate open" : null, "Size taken from the readiness bar"].filter(Boolean)
    .map((t, i) => `<label class="lbl pcCheck"><input type="checkbox" data-c="${esc(t)}" id="pcC${i}"> ${esc(t)}</label>`).join("");
}
function openPre() {
  const names = [...new Set(J.book.map((r) => r.strategy).concat(Object.keys(J.cards || {})))].sort();
  $("pcStrategy").innerHTML = names.map((s) => `<option>${esc(s)}</option>`).join(""); $("pcStrategy").value = names.includes("A14") ? "A14" : names[0];
  $("pcAcct").innerHTML = Object.keys(J.nav_now || {}).map((a) => `<option>${esc(a)}</option>`).join("");
  ["pcTicker", "pcWorst", "pcNote"].forEach((id) => { $(id).value = ""; }); $("pcMsg").textContent = "";
  preCommit(); $("jePrePanel").hidden = false;
}
async function savePre() {
  const s = $("pcStrategy").value, card = (J.cards || {})[s] || {}, acct = $("pcAcct").value;
  if (!$("pcTicker").value.trim() || !(parseFloat($("pcWorst").value) > 0)) { $("pcMsg").textContent = "Enter the ticker and the worst case."; return; }
  const checklist = {}; $("pcChecks").querySelectorAll("input").forEach((c) => { checklist[c.dataset.c] = c.checked; });
  try { await post("/api/journal/ticket", {strategy: s, ticker: $("pcTicker").value.trim(), account: acct, worst: parseFloat($("pcWorst").value), stop_pct: card.stop || null, nav: (J.nav_now || {})[acct] || null, checklist, mood: $("pcMood").value, confidence: +$("pcConf").value || null, tired: $("pcTired").checked, note: $("pcNote").value});
    $("jePrePanel").hidden = true; await saved(); } catch (e) { $("pcMsg").textContent = e.message; }
}

/* ---------- Behaviour ---------- */
const STREAKS = [["0–1", 0, 1], ["2–3", 2, 3], ["4–7", 4, 7], ["8+", 8, 1e9]];
function behaviour() {
  const C = St.closed(D), cfg = J.settings, run = J.streak_now, base = St.mean(C.map((d) => d.r));
  const hot = C.filter((d) => d.hot), rest = C.filter((d) => !d.hot), rev = C.filter((d) => d.revenge), size = (a) => St.median(a.map((d) => d.size_x).filter(ok)), tags = J.manual.journal_tags || [], tired = tags.filter((t) => t.tired).length;
  $("jbStrip").innerHTML = tile("Streak now", run, run >= cfg.streak_n ? `⚠ at your ${cfg.streak_n}+ line: this is when size creeps` : `straight winning closes · line at ${cfg.streak_n}`, run >= cfg.streak_n ? "wrn" : "") +
    tile("Entered on a streak", hot.length, `${R(St.mean(hot.map((d) => d.r)))} against ${R(St.mean(rest.map((d) => d.r)))} otherwise ${nTag(hot.length)}`) +
    tile("Size after a streak", x2(size(hot)), `your usual size for the strategy; ${x2(size(rest))} otherwise`, size(hot) > 1.25 ? "wrn" : "") +
    tile("Revenge flags", rev.length, rev.length ? `${R(St.mean(rev.map((d) => d.r)))} on average ${nTag(rev.length)}` : `a ${cfg.revenge_loss_r}R loss, then bigger or the same ticker`, rev.length ? "wrn" : "") +
    tile("After a loss", x2(size(C.filter((d) => d.after_loss))), `size of the next five entries · ${R(St.mean(C.filter((d) => d.after_loss).map((d) => d.r)))}`) +
    tile("Tagged tired", tired, tags.length ? `of ${tags.length} tags` : "tag entries from the 5am sitting");
  barChart($("jbStreak"), {label: "mean R by winning streak before entry", h: 190, unit: "R", dp: 2, items: STREAKS.map(([label, lo, hi]) => { const a = C.filter((d) => d.streak >= lo && d.streak <= hi); return {label, v: St.mean(a.map((d) => d.r)), n: a.length, title: `${label} wins before entry: <b>${R(St.mean(a.map((d) => d.r)))}</b> · ${a.length} entries · size ${x2(size(a))}`}; })});
  barChart($("jbAfter"), {label: "size of each entry after a loss", h: 190, unit: "×", dp: 1, items: [1, 2, 3, 4, 5].map((i) => { const a = C.filter((d) => d.after_loss === i); return {label: `${i}${i === 1 ? "st" : i === 2 ? "nd" : i === 3 ? "rd" : "th"}`, v: size(a), n: a.length, color: "var(--accent)", title: `Entry ${i} after a loss: size <b>${x2(size(a))}</b> · ${R(St.mean(a.map((d) => d.r)))} · ${a.length} entries`}; })});
  const by = new Map(J.decisions.map((d) => [d.decision, d])), moods = {};
  tags.forEach((t) => { const d = by.get(t.decision); if (d && ok(d.r) && t.mood) { const k = `${t.phase === "before" ? "Before" : "After"}: ${t.mood}`; (moods[k] = moods[k] || []).push(d); } });
  const mr = Object.entries(moods).sort((a, b) => a[0].localeCompare(b[0]));
  $("jbMoods").innerHTML = mr.length ? `<div class="tbl"><table><thead><tr><th>Tag</th><th class="n">n</th><th class="n">Won</th><th class="n">Mean R</th></tr></thead><tbody>${mr.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${v.length} ${nTag(v.length)}</td><td class="n">${pc(v.filter((d) => d.pnl > 0).length / v.length)}</td><td class="n ${cls(St.mean(v.map((d) => d.r)))}">${R(St.mean(v.map((d) => d.r)))}</td></tr>`).join("")}</tbody></table></div>` : `<div class="state">No tags yet: they start now. Add them in a pre-commit and on a trade's card.</div>`;
  const list = C.filter((d) => d.revenge || (d.hot && d.size_x >= 1.5)).reverse().slice(0, 5);
  $("jbFlags").innerHTML = list.length ? `<div class="tbl"><table><thead><tr><th>Entered</th><th>Trade</th><th>Flag</th><th class="n">Size</th><th class="n">Result</th></tr></thead><tbody>${list.map((d) => `<tr><td class="small">${day(d.entry_us)}</td><td>${esc(d.ticker)} ${esc(d.strategy)}</td><td class="small">${d.revenge ? "revenge" : `streak ${d.streak}, bigger`}</td><td class="n">${x2(d.size_x)}</td><td class="n">${stars(d)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="state">Nothing flagged in this view. A base of ${R(base)} a decision is the comparison.</div>`;
}

/* ---------- Review ---------- */
const flagged = () => J.decisions.filter((d) => d.extreme.length && ok(d.r)).sort((a, b) => b.close.localeCompare(a.close));
const reviewed = () => new Map((J.manual.journal_reviews || []).map((r) => [r.decision, r]));
const whyText = (d) => d.extreme.map((w) => w === "size" ? `over ${J.settings.extreme_x}× the average loss` : "past the loss planned at entry").join(" · ");
function review() {
  const L = flagged(), done = reviewed(), due = L.filter((d) => !done.has(d.decision)).length;
  $("jvCount").textContent = `${due} due of ${L.length}`;
  $("jvList").innerHTML = L.map((d) => `<div class="jrow jvrow ${REVIEW === d.decision ? "sel" : ""}" data-d="${esc(d.decision)}" tabindex="0"><span>${done.has(d.decision) ? `<span class="pos">✓</span>` : `<span class="wrn">⚠</span>`}</span><span><b>${esc(d.ticker)}</b> <span class="small muted">${esc(d.strategy)} · ${day(d.exit_us)}</span></span><span class="mono small ${cls(d.r)}" style="text-align:right">${R(d.r)}</span><span class="mono small ${cls(d.pnl)}" style="text-align:right">${money(d.pnl)}</span></div>`).join("") || `<div class="state">No losses need a post-mortem.</div>`;
  $("jvList").querySelectorAll(".jvrow").forEach((n) => { const go = () => { REVIEW = n.dataset.d; review(); }; n.addEventListener("click", go); n.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); });
  const d = L.find((x) => x.decision === REVIEW) || L.find((x) => !done.has(x.decision)) || L[0];
  if (!d) { $("jvForm").innerHTML = ""; $("jvTitle").textContent = "Post-mortem"; return; }
  REVIEW = d.decision; const r = done.get(d.decision) || {};
  $("jvTitle").textContent = `${d.ticker} ${d.strategy} · ${day(d.entry_us)} to ${day(d.exit_us)}`;
  $("jvForm").innerHTML = `<div class="kv mini">${tile("Result", `<span class="${cls(d.r)}">${R(d.r)}</span>`, money(d.pnl))}${tile("Why it's here", d.extreme.includes("size") ? x2(Math.abs(d.r) / (J.avg_loss_r || 1), 1) : "stop", whyText(d))}${tile("Planned loss", money(d.plan), "card stop × entry risk")}${tile("Peak ÷ 1R", x2(d.creep, 1), `${d.adj} adjustments · ${d.dit} days`)}${tile("Entry", ok(d.vix) ? `VIX ${fmt(d.vix, 1)}` : "–", `${d.streak} straight wins before it · ${ivtsBand(d.ivts).label}`)}</div>
    <div class="jvgrid"><label class="lbl">Cause<textarea id="jvCause" rows="3" maxlength="300" ${RO ? "disabled" : ""}>${esc(r.cause || "")}</textarea></label><label class="lbl">Emotion at the time<input type="text" id="jvEmotion" maxlength="120" value="${esc(r.emotion || "")}" ${RO ? "disabled" : ""}></label>
    <label class="lbl">Rule broken, if any<input type="text" id="jvRule" maxlength="120" value="${esc(r.rule_broken || "")}" ${RO ? "disabled" : ""}></label><label class="lbl">What changes next time<textarea id="jvLesson" rows="3" maxlength="300" ${RO ? "disabled" : ""}>${esc(r.lesson || "")}</textarea></label></div>
    <div class="row">${RO ? `<span class="small muted">Read-only here: post-mortems are written on the laptop.</span>` : `<button type="button" id="jvSave">Save post-mortem</button>`}<button type="button" class="ghost" id="jvOpen">Open the trade</button><span class="small muted" id="jvMsg">${r.updated ? `saved ${day(r.updated)}` : "due"}</span></div>`;
  $("jvOpen").addEventListener("click", () => { open(d.keys); });
  if (!RO) $("jvSave").addEventListener("click", async () => { try { await post("/api/journal/review", {decision: d.decision, cause: $("jvCause").value, emotion: $("jvEmotion").value, rule_broken: $("jvRule").value, lesson: $("jvLesson").value}); await saved(); } catch (e) { $("jvMsg").textContent = e.message; } });
}

/* ---------- Settings ---------- */
const FIELDS = [["cap_warn_pct", "Warning line", "% of NAV, planned loss"], ["cap_pct", "Cap", "% of NAV, planned loss"], ["creep_x", "Risk growth flag", "peak ÷ 1R"], ["loss_bar", "Losses before a claim", "the guest's 30"], ["cv_max", "CV under", "the guest's 10"], ["skew_min", "Skew over", "the guest's 0.5"],
  ["extreme_x", "Extreme loss", "× the average loss in R"], ["streak_n", "Streak line", "straight wins"], ["revenge_minutes", "Revenge window", "minutes after a loss"], ["revenge_loss_r", "Revenge: loss of at least", "R"], ["revenge_size", "Revenge: size at least", "× usual"], ["roll_minutes", "Roll window", "minutes to reopen"]];
function settings() {
  $("jsForm").innerHTML = `<div class="jsgrid">${FIELDS.map(([k, l, u]) => `<label class="lbl">${esc(l)}<span class="row" style="gap:6px"><input type="number" step="any" min="0" id="js-${k}" value="${J.settings[k]}" ${RO ? "disabled" : ""}><span class="small muted">${esc(u)}</span></span></label>`).join("")}</div>
    <div class="row" style="margin-top:8px">${RO ? `<span class="small muted">Read-only here: settings are changed on the laptop.</span>` : `<button type="button" id="jsSave">Save settings</button><button type="button" class="ghost" id="jsReset">Back to defaults</button>`}<span class="small muted" id="jsMsg"></span></div>`;
  if (!RO) { $("jsSave").addEventListener("click", async () => { const v = {}; FIELDS.forEach(([k]) => { v[k] = parseFloat($("js-" + k).value); }); try { await post("/api/journal/settings", v); await saved(); } catch (e) { $("jsMsg").textContent = e.message; } });
    $("jsReset").addEventListener("click", async () => { await post("/api/journal/settings", J.defaults); await saved(); }); }
  const M = J.manual, n = Object.values(M).reduce((a, t) => a + t.length, 0);
  $("jsBackup").innerHTML = `<p class="small">Your notes, tags, pre-commits, overrides, post-mortems and settings: <b>${n} rows</b>. No report can rebuild these, so they travel in the encrypted snapshot too.</p>
    <div class="row"><button type="button" id="jsExport">Download a copy</button>${RO ? "" : `<label class="lbl" for="jsImport">Restore from a copy <input type="file" id="jsImport" accept=".json,application/json"></label>`}</div><span class="small muted" id="jsBackMsg"></span>`;
  $("jsExport").addEventListener("click", () => { const b = new Blob([JSON.stringify({version: 1, exported: new Date().toISOString(), tables: M}, null, 1)], {type: "application/json"}), a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `journal-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href); });
  if (!RO) $("jsImport").addEventListener("change", async (e) => { const f = e.target.files[0]; if (!f) return; try { const out = await post("/api/journal/import", JSON.parse(await f.text())); $("jsBackMsg").textContent = `${out.rows} rows restored`; await window.loadJournal(); } catch (x) { $("jsBackMsg").textContent = x.message; } });
}

/* ---------- a trade's position numbers and tags, on its card ---------- */
const MOODS = ["calm", "focused", "confident", "rushed", "frustrated", "fearful"];
window.jCardRow = (key) => {
  const r = J && J.book.find((x) => x.keys.includes(key)); if (!r) return "";
  const t = (J.manual.journal_tags || []).find((x) => x.decision === r.decision && x.phase === "after") || {};
  return `<div class="kv mini" style="margin-top:6px">${tile("In R", `<span class="${cls(r.r)}">${R(r.r)}</span>`, `1R ${money(r.risk0)} · worst case at entry`)}${tile("Peak ÷ 1R", x2(r.creep, 1), `peak ${money(r.peak)}`, r.creep > J.settings.creep_x ? "wrn" : "")}${tile("Planned loss", ok(r.plan) ? money(r.plan) : "–", ok(r.plan_pct) ? `${fmt(r.plan_pct, 2)}% of NAV` : "no card stop")}${r.rolls ? tile("Rolled", r.rolls, "joined with the trade it reopened") : ""}</div>
    <div class="row jtag"><span class="lbl">After the trade</span><select id="jtMood" aria-label="Mood after" ${RO ? "disabled" : ""}><option value="">mood</option>${MOODS.map((m) => `<option ${t.mood === m ? "selected" : ""}>${m}</option>`).join("")}</select>
    <select id="jtConf" aria-label="Confidence" ${RO ? "disabled" : ""}><option value="">confidence</option>${[1, 2, 3, 4, 5].map((c) => `<option ${t.confidence === c ? "selected" : ""}>${c}</option>`).join("")}</select>
    <label class="lbl"><input type="checkbox" id="jtTired" ${t.tired ? "checked" : ""} ${RO ? "disabled" : ""}> tired</label><span class="small muted" id="jtMsg"></span></div>`;
};
window.jTagBind = (key) => {
  const r = J && J.book.find((x) => x.keys.includes(key)); if (!r || RO || !$("jtMood")) return;
  const go = async () => { await post("/api/journal/tag", {decision: r.decision, phase: "after", mood: $("jtMood").value, confidence: +$("jtConf").value || null, tired: $("jtTired").checked});
    const T = J.manual.journal_tags, i = T.findIndex((x) => x.decision === r.decision && x.phase === "after"), v = {decision: r.decision, phase: "after", mood: $("jtMood").value, confidence: +$("jtConf").value || null, tired: $("jtTired").checked ? 1 : 0};
    if (i >= 0) T[i] = v; else T.push(v); $("jtMsg").textContent = "saved"; };
  ["jtMood", "jtConf", "jtTired"].forEach((id) => $(id).addEventListener("change", go));
};

/* ---------- filters and load ---------- */
function all() {
  ROWS = J.book.filter(match);
  D = St.fold(ROWS);
  const k = St.closed(D).length, closed = J.book.filter((r) => !r.open).length;
  $("jeCount").textContent = `${k} decisions · ${ROWS.filter((r) => !r.open).length} of ${closed} closed · ${ROWS.filter((r) => r.open).length} open · fills to ${day((J.detail_exported || "").slice(0, 10))}${J.pending.length ? ` · ${J.pending.length} not in that report yet` : ""}`;
  table(); edge(); confidence(); discipline(); risk(); behaviour();
}
function bar() {
  const opts = (sel, list, label) => { const cur = $(sel).value; $(sel).innerHTML = `<option value="">${label}</option>` + list.map((v) => `<option>${esc(v)}</option>`).join(""); $(sel).value = cur; };
  opts("jeStrategy", [...new Set(J.book.map((r) => r.strategy))].sort(), "all strategies");
  opts("jeAcct", [...new Set(J.book.map((r) => r.acct))].sort(), "all accounts");
  opts("jeVix", St.VIX.map((b) => b[0]), "any VIX at entry");
  opts("jeDte", St.DTE.map((b) => b[0]), "any entry DTE");
}
[["jeStrategy", "strategy"], ["jeAcct", "acct"], ["jeVix", "vix"], ["jeDte", "dte"], ["jeFrom", "from"], ["jeTo", "to"]].forEach(([id, k]) => $(id).addEventListener("change", () => { F[k] = $(id).value; if (J) all(); }));
$("jdAll").addEventListener("change", () => { ALL = $("jdAll").checked; discipline(); });
$("jePre").addEventListener("click", () => { if (J) openPre(); });
["pcStrategy", "pcAcct", "pcWorst"].forEach((id) => $(id).addEventListener("input", preCommit));
$("pcSave").addEventListener("click", savePre);
if (RO) { $("jePre").hidden = true; }
const syncBar = () => { const nav = document.querySelector("#tab-journal .subnav button[aria-selected=true]"); $("jeBar").hidden = !nav || !FILTERED.includes(nav.dataset.n); };
window.addEventListener("subtab", syncBar);

window.JV = {
  render(data, openTrade) {
    J = data; open = openTrade;
    J.decisions = St.fold(J.book);
    const none = !J.book.length;
    bar();
    if (none) return;
    all(); review(); settings(); syncBar();
    const due = flagged().filter((d) => !reviewed().has(d.decision)).length;
    if (window.navBadge) window.navBadge("journal", due ? String(due) : "", due ? "wrn" : "");
    if (!BT) api("/api/backtest").then((b) => { BT = b; tail(); }).catch(() => {});
  },
};
})();
