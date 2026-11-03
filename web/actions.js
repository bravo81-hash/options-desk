/* Actions: everything that needs doing today, on one screen. Each item links to the tab with the detail. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const SIZE_CLS = {"Full size": "pos", "Three-quarter size": "sz", "Half size": "sz", "Quarter size": "sz", "Stand aside": "neg"};
const ACT = {exit: ["neg", "⚠ Exit"], decide: ["wrn", "⚠ Decide"], close: ["pos", "✓ Close"], slow: ["wrn", "◔ Exit at next green"]};
const WORD = {"Full size": "full size", "Three-quarter size": "three-quarter size", "Half size": "half size", "Quarter size": "quarter size", "Stand aside": "stand aside"};
const go = (tab, text, sub) => `<a href="#" class="small" data-go="${tab}"${sub ? ` data-sub="${esc(sub)}"` : ""}>${esc(text)} →</a>`;
const order = (o) => window.orderTxt(o, true);
const dist = (t) => { const q = t.plan, a = q && q.at, pc = (x) => ok(x) && ok(t.spot) ? 100 * (x / t.spot - 1) : null;
  if (!a || !ok(t.spot)) return "";
  const m = [[a.decide, "var(--warn)", "decide"], [a.stop, "var(--down)", "stop"]].flatMap(([L, c, nm]) => !L || L.past ? [] : [[L.dn, "↓"], [L.up, "↑"]].filter(([x]) => ok(x)).map(([x, d]) => ({v: pc(x), color: c, label: `${nm} ${d} ${Math.round(x)} (${pctS(pc(x))} from spot)`})));
  return bulletSvg(0, {w: 150, lo: -10, hi: 6, color: "var(--accent)", label: "index now (dot) and its alert levels, % from spot",
    zones: [{from: -10, to: 6, color: "var(--soft)"}], marks: m.filter((x) => ok(x.v))});
};
const lv = (L, u) => !L ? "–" : L.past ? "already past" : [L.dn ? `${u} ↓ <b class="mono">${Math.round(L.dn).toLocaleString()}</b>` : null, L.up ? `↑ <b class="mono">${Math.round(L.up).toLocaleString()}</b>` : null].filter(Boolean).join(" · ") || "beyond −25% / +15%";

/* ---------- filters: ticker, first expiry, account (remembered on this browser) ---------- */
let L = null, LAD = null;
const FK = "od.acFilt";
let F = (() => { try { return JSON.parse(localStorage.getItem(FK)) || {}; } catch (e) { return {}; } })();
const expKey = (t) => new Date(t.firstExp).toLocaleDateString("en-CA", {timeZone: "America/New_York"});  // expiry date in New York (16:00 ET is next morning in Sydney)
const expTxt = (k) => window.dexp(Date.parse(k + "T12:00:00-05:00"));
const KEYS = {sym: (t) => t.underlying, exp: expKey, acct: (t) => t.acctLabel};
const pass = (t, skip) => Object.entries(KEYS).every(([k, f]) => k === skip || !F[k] || f(t) === F[k]);
const pick = (Rk) => Rk && {...Rk, trades: Rk.trades.filter((t) => pass(t))};
const active = () => Object.values(F).some(Boolean);

function filters() {
  const el = $("acFilt"); if (!el) return;
  if (!L || !L.Rk) { el.innerHTML = ""; return; }
  const T = L.Rk.trades;
  Object.keys(KEYS).forEach((k) => { if (F[k] && !T.some((t) => KEYS[k](t) === F[k])) delete F[k]; });  // a filter whose trades have closed
  const box = (k, label, txt = (v) => v) => {
    const n = {}; T.filter((t) => pass(t, k)).forEach((t) => { const v = KEYS[k](t); if (v) n[v] = (n[v] || 0) + 1; });
    return `<label class="small">${label} <select data-f="${k}"><option value="">All</option>${Object.keys(n).sort().map((v) => `<option value="${esc(v)}"${F[k] === v ? " selected" : ""}>${esc(txt(v))} (${n[v]})</option>`).join("")}</select></label>`;
  };
  el.innerHTML = `${box("sym", "Ticker")}${box("exp", "Expiry", expTxt)}${box("acct", "Account")}
    ${active() ? `<button type="button" class="ghost" id="acFClear">Clear filters</button><span class="small muted">showing ${pick(L.Rk).trades.length} of ${T.length} open trades · releases and data checks are not filtered</span>` : `<span class="small muted">filters apply to the trade lists and the A14 ladder (ticker)</span>`}`;
  el.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => { F[s.dataset.f] = s.value || undefined; save(); render(); }));
  const c = $("acFClear"); if (c) c.addEventListener("click", () => { F = {}; save(); render(); });
}
const save = () => { try { localStorage.setItem(FK, JSON.stringify(F)); } catch (e) {} };

function render() {
  filters();
  const V = pick(L.Rk);
  doToday(V); orders(V); coming(V, L.Rd); ladder();
}

async function load() {
  const host = $("acDo"); if (!host) return;
  if (!host.firstChild) ["acDo", "acNew"].forEach((id) => { $(id).innerHTML = `<div class="state loading">Reading your trades…</div>`; });
  $("acWhen").textContent = new Date().toLocaleString([], {weekday: "long", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"});
  const [Rk, Rd, Fr, Sn] = await Promise.all([
    window.riskActions ? window.riskActions().catch(() => null) : null,
    api("/api/readiness").catch(() => null), api("/api/freshness").catch(() => null),
    window.DESK_CLOUD ? null : api("/api/snapshot").catch(() => null), window.loadHeads ? window.loadHeads().catch(() => null) : null]);
  L = {Rk, Rd}; LAD = null;
  headline(Rd); render(); entries(Rd); checks(Rk, Fr, Sn); conditions(); matrix(Rd);
  if (window.renderHeads) window.renderHeads(Rk);
  logPlans(Rk); api("/api/journal/due").then(journalLine).catch(() => {});  // apart from the rest: the first build takes a few seconds
  api("/api/a14/rules").catch(() => ({error: "A14 rules unavailable"})).then((d) => { LAD = d; ladder(); });
}

/* what Trade plan said today, for Journal > Discipline: without this, no fill can be scored against the call. Laptop only. */
let planSent = 0;
function logPlans(Rk) {
  if (window.DESK_CLOUD || !Rk || Date.now() - planSent < 9e5) return; planSent = Date.now();
  const items = Rk.trades.filter((t) => t.plan).map((t) => ({key: t.id, act: t.plan.act, label: t.plan.label, adj: t.plan.adj ? t.plan.adj.ok : null, pct: t.totalPct}));
  if (items.length) fetch("/api/journal/plan", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({items})}).catch(() => {});
}
/* owed to the journal: losses waiting for a post-mortem, and a winning streak, which is when size tends to creep */
function journalLine(J) {
  const n = J.due.length, hot = J.streak >= J.streak_n;
  if (window.navBadge) navBadge("journal", n ? String(n) : "", n ? "wrn" : "");
  $("acJournal").innerHTML = [hot ? `<div class="small">⚠ <b>${J.streak} straight wins</b>: overconfidence shows up here. The readiness bar still sets the size.</div>` : "",
    n ? `<div class="small">⚠ <b>${n} big ${n === 1 ? "loss needs a post-mortem" : "losses need a post-mortem"}</b> ${go("journal", "Review", "Review")}</div>` : ""].join("");
}

/* the size call as one sentence; structures that differ from it are named, since they can sit a step below */
function headline(Rd) {
  if (!Rd || Rd.error) { $("acHead").innerHTML = ""; return; }
  const diff = {};
  Rd.strategies.filter((s) => s.size !== Rd.size).forEach((s) => { (diff[s.size] = diff[s.size] || []).push(s.name); });
  const rest = Object.entries(diff).map(([z, n]) => `${n.join(", ")}: ${WORD[z]}`).join(" · ");
  $("acHead").innerHTML = `<b class="${SIZE_CLS[Rd.size] || ""}">${esc(Rd.size)}</b><span>for new trades today${rest ? ` · ${esc(rest)}` : ""}</span> <a href="#" class="small" data-ready="1">why →</a>`;
}

const subBtn = (n) => [...$("acMore").previousElementSibling.children].find((b) => b.dataset.n === n);

function doToday(Rk) {
  if (!Rk) { $("acDo").innerHTML = `<div class="state">${window.DESK_CLOUD ? "Your trades are locked. <button type=\"button\" class=\"unlockBtn\">Unlock snapshot</button>" : "Open trades unavailable: is a ONE report in Documents?"}</div>`; return; }
  const P = Rk.trades.filter((t) => t.plan && t.plan.act !== "hold").sort((a, b) => a.plan.pri - b.plan.pri || (a.totalPct ?? 0) - (b.totalPct ?? 0));
  const held = Rk.trades.filter((t) => t.plan && t.plan.act === "hold").length, noCard = Rk.trades.filter((t) => !t.plan).length;
  if (window.navBadge) { navBadge("actions", P.length ? String(P.length) : "", P.length ? "wrn" : ""); navBadge("risk", String(L.Rk.trades.length)); }
  $("acDoMeta").textContent = `${Rk.trades.length}${active() ? ` of ${L.Rk.trades.length}` : ""} open trades · ${P.length} need something · ${held} on hold${noCard ? ` · ${noCard} without card rules` : ""}`;
  if (!P.length) { $("acDo").innerHTML = `<div class="state">Nothing to do on ${active() ? "the filtered" : "open"} trades: every carded trade is between its stop and target. ${go("risk", "Trade plan", "Trade plan")}</div>`; return; }
  const folded = (t, i) => i >= 5 && !["exit", "decide"].includes(t.plan.act);  // never fold an Exit or Decide away
  $("acDo").innerHTML = `<div class="capped"><div class="tbl"><table><thead><tr><th>Do</th><th>Trade</th><th class="n" title="dot = total now · red line = hard stop · dashed = decide line · green line = target">Total · stop → target</th><th title="days in trade · short strikes in σ · whether an adjustment is allowed">Health</th><th>Why</th><th>Order to use</th><th></th></tr></thead><tbody>${
    P.map((t, i) => { const q = t.plan, [k, word] = ACT[q.act] || ["", q.label];
      const use = q.act === "exit" ? `close now${q.stopPx ? ` · combo ~${q.stopPx.px.toFixed(2)}` : ""}`
        : q.act === "close" ? `close now · target order ${order(q.order)}`
        : q.act === "slow" ? `close at the next close ≥ 0%${q.order ? ` · or keep the target order ${order(q.order)}` : ""}`
        : `adjust: <span class="chip">${esc(q.adj.ok)}</span>${q.how ? ` <span class="small muted">${esc(q.how)}</span>` : ""}`;
      return `<tr${folded(t, i) ? ` class="xrow"` : ""}><td><span class="chip ${k}">${esc(word)}</span></td><td>${esc(t.name)} <span class="small muted">${esc(t.acctLabel || "")}</span></td>
        <td class="n ${cls(t.totalPct)}"><b>${pctS(t.totalPct)}</b> <span class="small muted">${money(t.pnlNow)}</span><br>${window.planBullet ? window.planBullet(t) : ""}</td><td style="min-width:150px"><div class="hline">${window.healthBits ? window.healthBits(t).join("") : ""}</div></td><td class="small" style="white-space:normal;min-width:240px">${esc(q.why)}</td><td class="small" style="white-space:normal;min-width:200px">${use}</td>
        <td><a href="#" class="small" data-trade="${esc(t.id)}">detail →</a></td></tr>`; }).join("")}</tbody></table></div>${P.some(folded) ? `<button type="button" class="ghost" data-cap="Show all ${P.length}">Show all ${P.length}</button>` : ""}</div>`;
}

/* ---------- market conditions: one row per signal from the other tabs (desk/conditions.py) ---------- */
const TABLINK = {"Market": "market", "Term structure": "today", "Skew & IV": "skew", "Expected moves": "em", "Seasonality": "season"};
const EFF = {helps: ["pos", "helps"], hurts: ["neg", "hurts"], neutral: ["", "neutral"], thin: ["muted", "few entries"], none: ["muted", "no data"], "n/a": ["muted", "n/a"]};
let condTries = 0;

async function conditions() {
  const el = $("acCond"); if (!el) return;
  const C = await api("/api/conditions").catch((e) => ({error: e.message}));
  if (!C || C.running || C.error) {
    el.innerHTML = `<div class="state">${C && C.error ? esc(C.error) : "Backtest computing (under a minute after an update)…"}</div>`;
    if (C && C.running && condTries++ < 8) setTimeout(conditions, 15000);
    return;
  }
  const S = STRUCTS, tally = Object.fromEntries(S.map((s) => [s, {helps: 0, hurts: 0}]));
  let lastTab = "";
  const body = C.rows.map((r) => {
    const head = r.tab !== lastTab ? `<tr><td colspan="${S.length + 3}" style="padding-top:10px"><b>${esc(r.tab)}</b> ${go(TABLINK[r.tab], "open tab")}</td></tr>` : "";
    lastTab = r.tab;
    const cells = S.map((s) => { const c = r.cells[s] || {}, [k, word] = EFF[c.effect] || ["muted", "–"];
      if (tally[s][c.effect] !== undefined) tally[s][c.effect]++;
      const tint = c.effect === "helps" ? "var(--up)" : c.effect === "hurts" ? "var(--down)" : null;
      return `<td class="n" title="${esc(c.bucket ? `today's bucket ${c.bucket}` : "")}"${tint ? ` style="background:color-mix(in srgb, ${tint} 10%, transparent)"` : ""}>${c.dist && c.dist.length ? sparkBars(c.dist.map((x) => ({label: x.b, v: x.avg, n: x.n, sel: x.sel})), {label: `${s}: average by ${r.label} bucket`}) + "<br>" : ""}<span class="chip ${k}">${word}</span>${ok(c.avg) ? `<br><span class="small ${cls(c.avg)}">${pctS(c.avg)}</span><span class="small muted"> vs ${pctS(c.base)} · </span>${nTag(c.n)}` : ""}</td>`; }).join("");
    return `${head}<tr><td style="padding-left:14px">${esc(r.label)}</td><td class="small mono">${esc(r.reading)}</td>${cells}<td class="small muted" style="white-space:normal;min-width:180px">${esc(r.in_size)}</td></tr>`;
  }).join("");
  const sizeRow = `<tr style="border-top:2px solid var(--line)"><td><b>Size call</b> <span class="small muted">readiness bar</span></td><td class="small">market: <b>${esc(C.size)}</b></td>${S.map((s) => { const st = C.strategies[s];
    return `<td class="n"><b class="${SIZE_CLS[st && st.size] || ""}">${esc(st ? st.size : "–")}</b><br><span class="small muted">${tally[s].helps} help · ${tally[s].hurts} hurt</span></td>`; }).join("")}<td></td></tr>`;
  const f21 = C.season && C.season.fwd21;
  el.innerHTML = `<div class="tbl"><table><thead><tr><th>Signal</th><th>Today${C.date ? ` <span class="muted">(${esc(C.date)})</span>` : ""}</th>${S.map((s) => `<th class="n">${s}</th>`).join("")}<th>In the size call?</th></tr></thead><tbody>${body}${sizeRow}</tbody></table></div>
    <div class="kv mini" style="margin-top:8px">${C.odds.map((o) => `<div><span class="lbl">${esc(o.name)}</span><b class="${o.dd5 > C.base_dd5 * 1.3 ? "neg" : o.dd5 < C.base_dd5 * 0.85 ? "pos" : ""}">${ok(o.dd5) ? o.dd5.toFixed(0) + "%" : "–"}</b>${ok(o.dd5) && window.oddsBar ? window.oddsBar(o.dd5, C.base_dd5) : ""}<span class="small muted">chance of a 5% SPX drop in 21 sessions (normally ${C.base_dd5.toFixed(0)}%) · ${esc(o.reading || "")}</span></div>`).join("")}
      ${f21 ? `<div><span class="lbl">Seasonality, next 21 sessions</span><b>${f21.up.toFixed(0)}% up</b><span class="small muted">avg ${pctS(f21.mean)}, worst ${pctS(f21.worst)} over the last ${f21.n} years · ${esc(C.season.cycle || "")} year</span></div>` : ""}
      <div><span class="lbl">High-impact releases, 3 days</span><b class="${C.events.length || (C.events_feed && C.events_feed.state === "unavailable") ? "wrn" : ""}">${C.events.length ? [...new Set(C.events.map((e) => e.title))].length + ([...new Set(C.events.map((e) => e.title))].length > 1 ? " releases" : " release") : C.events_feed && C.events_feed.state === "unavailable" ? "feed unavailable" : "none"}</b><span class="small muted">${esc([...new Set(C.events.map((e) => e.title))].join(", ") || "calendars step down into CPI, FOMC, payrolls, PCE, GDP")}</span></div></div>
    <p class="note">The bars in each cell are the average per bucket of that signal, low to high (today's bucket solid, hover for numbers). Each cell compares entries made in today's bucket of that signal with all entries of that structure since 2009: <b>helps</b> = at least ${C.rules.edge} point better than the structure's average, <b>hurts</b> = at least ${C.rules.edge} point worse, <b>few entries</b> = under ${C.rules.min_n} in the bucket. The signals overlap (high IV percentile, flat term structure and a falling index tend to come together), so count them as evidence, not votes: the size call above is the readiness bar's, and the last column says which signals feed it. The trend row uses today's term-structure band, as the size rule does. A14: ${esc(C.basis.A14)}. Calendars: ${esc(C.basis.Calendar)}. The model prices one fixed skew shape, so the SKEW, VVIX and IV-percentile rows show what those markets went on to do, not their effect on prices.</p>`;
}

/* ---------- decision matrix: readiness rules (desk/readiness.py matrix) x backtest cells ---------- */
const STEPS = ["Stand aside", "Quarter size", "Half size", "Three-quarter size", "Full size"];
const SHORT = {"Stand aside": "aside", "Quarter size": "¼", "Half size": "½", "Three-quarter size": "¾", "Full size": "full"};
const BANDS = [["steep", "Steep contango", "under 0.834"], ["normal", "Normal", "0.834–0.90"], ["flat", "Flat", "0.90–1.00"], ["backwardation", "Backwardation", "1.00+"]];
const STRUCTS = ["A14 SPX", "A14 RUT", "Calendar SPX", "Calendar RUT"];
let BT = null, btTries = 0;

async function matrix(Rd) {
  const el = $("acMatrix"); if (!el) return;
  if (!Rd || Rd.error || !Rd.matrix) { el.innerHTML = `<div class="state">Readiness unavailable.</div>`; return; }
  BT = await api("/api/backtest").catch(() => null);
  matrixRender(Rd);
  if (BT && !BT.matrix && !BT.error && btTries++ < 8) setTimeout(() => matrix(Rd), 20000);  // first run after an update computes in the background
}

let MX = null, mxAll = false;
window.renderMatrix = matrix;
document.addEventListener("click", (e) => { if (e.target.id === "acMxAll") { mxAll = !mxAll; matrixRender(MX); } });

function matrixRender(Rd) {
  const size = Rd.size, cur = Rd.ivts_band.band;
  MX = Rd;
  const trendOf = (s) => (Rd.trends[s.split(" ")[1]] || {}).short_up ? "above" : "below";
  const cell = (s, b, t) => {
    const steps = Rd.matrix[s.split(" ")[0]][b][t];
    const sz = steps === null ? "Stand aside" : STEPS[Math.max(0, STEPS.indexOf(size) - steps)];
    const chip = steps === null ? `<span class="chip neg">stand aside</span>`
      : `<span class="chip ${steps ? "wrn" : "pos"}">${steps ? `−${steps} step${steps > 1 ? "s" : ""}` : "no step"} → ${SHORT[sz]}</span>`;
    const r = BT && BT.matrix && BT.matrix[s] && BT.matrix[s].cells[b] && BT.matrix[s].cells[b][t];
    const now = b === cur && t === trendOf(s);
    const tint = r ? `background:color-mix(in srgb, ${r.avg >= 0 ? "var(--up)" : "var(--down)"} ${Math.round(Math.min(Math.abs(r.avg) / 5, 1) * 28)}%, transparent);` : "";
    return `<td class="n" style="${tint}${now ? "outline:2px solid var(--accent);outline-offset:-2px" : ""}">${chip}<br><span class="small ${r ? cls(r.avg) : "muted"}">${r ? `${pctS(r.avg)} · ${Math.round(100 * r.win)}% won` : BT && BT.matrix ? "no entries" : ""}</span>${r ? ` ${nTag(r.n)}` : ""}</td>`;
  };
  const rows = BANDS.filter(([b]) => mxAll || b === cur).flatMap(([b, name, rng]) => ["above", "below"].map((t, k) => `<tr${b === cur ? ` style="background:color-mix(in srgb, var(--accent) 7%, transparent)"` : ""}>${k ? "" : `<td rowspan="2"><b>${name}</b><br><span class="small muted">VIX/VIX3M ${rng}</span></td>`}
    <td class="small">${t} 20-day avg</td>${STRUCTS.map((s) => cell(s, b, t)).join("")}</tr>`)).join("");
  $("acMatrix").innerHTML = `<p class="small" style="margin:0 0 6px">Today: VIX/VIX3M <b>${fmt(Rd.ivts, 3)}</b> (${esc(Rd.ivts_band.label)}) · VIX9D/VIX <b class="${ok(Rd.front) && Rd.front >= 0.9 ? "wrn" : ""}">${fmt(Rd.front, 3)}</b> · SPX ${trendOf("A14 SPX")} and RUT ${trendOf("A14 RUT")} their 20-day averages · market size <b>${esc(size)}</b> (${esc(Rd.why)}).</p>
    <div class="tbl"><table><thead><tr><th>Term structure</th><th>Index vs</th>${STRUCTS.map((s) => `<th class="n">${s}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    <p><button type="button" class="ghost" id="acMxAll">${mxAll ? "Show today's rows only" : "Show all 8 rows"}</button></p>
    <p class="note">How to read it: the market size (from the drop odds in the readiness bar) is the starting point; each cell shows the steps the term-structure, trend and front-of-curve rules take off it at today's VIX9D/VIX, and the size that leaves today. A14s take one more step with VIX9D/VIX at 0.90+ in a steep or normal term structure (the cells' results are for all VIX9D/VIX readings). Other flags on top: thin RUT premium (RVX 3 pts or less above VIX) steps RUT A14s down, a high-impact release within 3 days steps calendars down. Results: A14 = 45 DTE, your median shape, revised exits (target 7%, stop −20%, time and pace), % of max loss; calendars = 15/22 DTE ATM put calendar, target 5%, stop −15%, % of the debit. The model uses one fixed skew shape, so it shows the term-structure and trend effect, not that day's skew.</p>`;
}

function entries(Rd) {
  if (!Rd || Rd.error) { $("acNew").innerHTML = `<div class="state">${esc((Rd && Rd.error) || "Readiness unavailable")}</div>`; return; }
  const open = Rd.strategies.filter((s) => s.size !== "Stand aside");
  $("acNewMeta").innerHTML = `market size: <b class="${SIZE_CLS[Rd.size] || ""}">${esc(Rd.size)}</b>`;
  $("acNew").innerHTML = `<div class="kv mini">${Rd.strategies.map((s) => `<div><span class="lbl">${esc(s.name)}</span><b class="${SIZE_CLS[s.size] || ""}">${esc(s.size)}</b>${sizeMeter(s.size)}<span class="small muted">${esc(s.notes[0] || "")}</span></div>`).join("")}</div>
    <p class="small">${open.length ? `Open for new trades: <b>${open.map((s) => esc(s.name)).join(", ")}</b>. ` : `<b>No new entries today.</b> ${esc(Rd.why)}.`} <a href="#" class="small" data-ready="1">why →</a></p>`;
}

/* the A14 ladder: ids open per ticker and account against the cap, today's window, and the id the rules open next */
function ladder() {
  const el = $("acLadder"); if (!LAD) { el.innerHTML = `<div class="state small">Reading the A14 ladder…</div>`; return; }
  if (LAD.error) { el.innerHTML = `<div class="state">${esc(LAD.error)}</div>`; return; }
  const P = LAD.rule, accts = Object.keys(LAD.navs), known = !!(L.Rk && L.Rk.trades), day = window.nyDay(), syms = ["SPX", "RUT"].filter((u) => !F.sym || F.sym === u);
  const openIn = (u, a) => (known ? L.Rk.trades : []).filter((t) => t.strategy === "A14" && t.underlying === u && t.acctLabel === a).map((t) => window.dteOf(t.firstExp)).sort((x, y) => y - x);
  const strip = (D, n) => bulletSvg(n ? n.dte : null, {w: 190, lo: 0, hi: Math.max(60, ...D), color: "var(--accent)", label: `${D.length} open: ${D.join(", ")} DTE · entry band ${P.dte_lo}–${P.dte_hi} · out at ${P.time_dte}`,
    zones: [{from: P.dte_lo, to: P.dte_hi, color: "var(--accent)"}], marks: [{v: P.time_dte, color: "var(--warn)", label: `out at ${P.time_dte} DTE`}, ...D.map((v) => ({v, color: "var(--ink)", width: 1.5, label: `${v} DTE`}))]});
  const etToday = new Date().toLocaleDateString("en-CA", {timeZone: "America/New_York"});
  const entryTxt = new Date(LAD.entry_next + "T12:00:00Z").toLocaleDateString("en-AU", {weekday: "short", day: "numeric", month: "short", timeZone: "UTC"});
  const expiry = (e) => new Date(Date.UTC(+e.slice(0, 4), +e.slice(4, 6) - 1, +e.slice(6))).toLocaleDateString("en-AU", {day: "numeric", month: "short", timeZone: "UTC"});
  const row = (u) => { const n = LAD.next[u], D = accts.map((a) => openIn(u, a)), most = Math.max(0, ...D.map((x) => x.length));
    const size = ((L.Rd && L.Rd.strategies) || []).find((s) => s.name === `A14 ${u}`), step = size ? size.size : null, lots = n && step ? n.lots[step] : null;
    const state = !known ? ["", "Ids unknown"] : most > P.cap ? ["wrn", "⚠ Over the cap"] : most === P.cap ? ["muted", "At the cap"] : step === "Stand aside" ? ["muted", "Stand aside"] : LAD.entry_next === etToday ? ["pos", "✓ Entry today"] : ["muted", `◔ Entry ${entryTxt}`];
    const shift = n && n.tilt ? `tilt ${n.tilt > 0 ? "+" : "−"}${Math.abs(n.tilt)} sd, index ${pctS(n.vs20)} vs 20-day` : "centred";
    return `<tr><td><b>${u}</b><br><span class="chip ${state[0]}">${state[1]}</span></td>
      ${accts.map((a, k) => `<td><b class="mono ${D[k].length > P.cap ? "wrn" : ""}">${known ? D[k].length : "–"}</b> <span class="small muted">of ${P.cap}</span> ${strip(D[k], n)}</td>`).join("")}
      <td>${n ? `${expiry(n.expiry)} <span class="small muted">${n.dte}d</span> <span class="mono">${Math.round(n.upper)}/${Math.round(n.short)}/${Math.round(n.lower)}</span><br><span class="small muted">${esc(shift)}</span>` : `<span class="small muted">No Friday expiry in ${P.dte_lo}–${P.dte_hi} DTE on the fetched chain</span>`}</td>
      <td class="n">${n ? `${money(n.risk)}<br><span class="small muted">${Math.abs(n.credit).toFixed(2)} ${n.credit >= 0 ? "credit" : "debit"}</span>` : "–"}</td>
      <td class="n">${ok(lots) ? `<b class="${lots ? "" : "wrn"}">${lots}</b> <span class="small muted">at ${esc(WORD[step] || step)}</span><br><span class="small muted">full size ${n.lots["Full size"]}</span>` : "–"}</td>
      <td class="n small">${n && lots ? accts.map((a) => `${esc(a)} ${(100 * lots * n.risk * P.stop / 100 / LAD.navs[a]).toFixed(2)}%`).join("<br>") : "–"}</td></tr>`; };
  $("acLadMeta").textContent = `${window.DAYS[day]} in New York: ${P.windows.includes((day + 6) % 7) ? "a window day for adjustments" : "no adjustments today; targets and stops still count"}${LAD.chain_ts ? ` · next id priced on the ${new Date(LAD.chain_ts).toLocaleString([], {weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})} chain` : ""}`;
  el.innerHTML = `<div class="tbl"><table><thead><tr><th>Ticker</th>${accts.map((a) => `<th>${esc(a)} ids</th>`).join("")}<th>Next id</th><th class="n">Risk a lot</th><th class="n">Lots</th><th class="n">Loss at −${P.stop}%</th></tr></thead><tbody>${syms.map(row).join("")}</tbody></table></div>
    <p class="note">Bars are open ids by DTE, the dot is the next id, the shaded band the ${P.dte_lo}–${P.dte_hi} DTE entry window and the amber line the ${P.time_dte} DTE exit. Same lots in every account, sized on the smallest NAV: ${money(LAD.worst)} of worst case an id at full size, ${money(LAD.stop_usd)} at the stop. ${go("guide", "A14 rules", "A14 rules")} ${go("a14", "A14 scanner", "Scanner")}</p>`;
}

function orders(Rk) {
  subBtn("Orders & alerts").hidden = !Rk;
  if (!Rk) { $("acOrders").innerHTML = ""; return; }
  const P = Rk.trades.filter((t) => t.plan && (t.plan.order || t.plan.at)), none = Rk.trades.filter((t) => !t.plan);
  $("acOrdMeta").textContent = `one GTC target close and two price alerts for each of the ${P.length} of ${Rk.trades.length} open trades with card rules`;
  if (!P.length) { $("acOrders").innerHTML = `<div class="state">No carded trades${active() ? " in the filter" : ""}.</div>`; return; }
  $("acOrders").innerHTML = `<div class="tbl"><table><thead><tr><th>Trade</th><th class="n">GTC target close</th><th class="n">Alert: decide</th><th class="n">Alert: stop</th><th title="dot = index now; orange = decide alert, red = stop alert; scale −10% to +6% from spot">How far</th></tr></thead><tbody>${
    P.sort((a, b) => a.underlying.localeCompare(b.underlying) || a.firstExp - b.firstExp).map((t) => { const q = t.plan;
      return `<tr><td class="small">${esc(t.name)} <span class="muted">${esc(t.acctLabel || "")}</span></td><td class="n small">${order(q.order)}</td><td class="n small">${lv(q.at && q.at.decide, t.underlying)}</td><td class="n small">${lv(q.at && q.at.stop, t.underlying)}</td><td>${dist(t)}</td></tr>`; }).join("")}</tbody></table></div>
    ${none.length ? `<p class="small"><b>${none.length} open trade${none.length > 1 ? "s" : ""} without card rules</b>, so no target or alerts here: ${none.map((t) => `${esc(t.name)} <span class="muted">(${esc(t.strategy)}, ${esc(t.acctLabel || "")})</span>`).join(" · ")}.</p>` : ""}
    <p class="note">Limits are per combo: 2× at 9.45 means two of the combo shown, $1,890 for the position. Twins can show different multiples when their legs differ (one has split a short across two strikes, say), so compare the $ a lot. Target orders are valid until you adjust the trade; re-enter after any adjustment. Alert levels assume the move happens today with IVs unchanged; refresh marks to update them. Card rules exist for A14, Allantis, HV7, TimeEdge, TimeZone, Triple Cal and Flyagonal. ${go("risk", "Trade plan", "Trade plan")}</p>`;
}

function coming(Rk, Rd) {
  const items = [], H = window.HEADS, end = H && H.coming_to ? Date.parse(H.coming_to) : Date.now() + 3 * 864e5, week = H && H.week_to ? Date.parse(H.week_to) : end,
    top = ["Payrolls", "CPI", "FOMC", "Election"], future = (e) => { const t = Date.parse(e.date); return t >= Date.now() && (t <= end || (top.includes(e.kind) && t <= week)); };
  const rule = new Set((Rd && Rd.events || []).map((e) => e.title));  // the releases the calendar step-down reads
  const nyDay = (iso) => new Date(iso).toLocaleDateString("en-CA", {timeZone: "America/New_York"});
  const byDay = {};  // one line per US day: high-impact in bold, medium after it
  (H ? H.macro : (Rd && Rd.events || []).map((e) => ({...e, importance: 1}))).filter(future).forEach((e) => { const d = byDay[nyDay(e.date)] = byDay[nyDay(e.date)] || {when: e.date, hi: [], med: [], rule: false};
    (e.importance >= 1 ? d.hi : d.med).push(e.title.replace(" (schedule)", "")); if (rule.has(e.title)) d.rule = true; });
  Object.values(byDay).forEach((d) => items.push({when: d.when, txt: `${d.hi.length ? `<b>${esc([...new Set(d.hi)].join(", "))}</b> ` : ""}${d.med.length ? `<span class="small muted" title="${esc([...new Set(d.med)].join(", "))}">${d.hi.length ? "and " : ""}${[...new Set(d.med)].length} medium</span> ` : ""}${d.rule ? `<span class="small muted">no new calendars into it</span>` : ""}`}));
  if (H) H.earnings.filter((e) => e.top && Date.parse(e.when) <= end).forEach((e) => items.push({when: e.when, txt: `<b>${esc(e.sym)}</b> <span class="small muted">reports ${esc(e.session)}${e.firm ? "" : " (est.)"}, ${fmt(e.weight, 1)}% of SPX</span>`}));
  if (Rk) Rk.trades.forEach((t) => { const q = t.plan; if (!q || !ok(q.dte)) return;
    const left = ok(q.timeDte) ? q.dte - q.timeDte : null;
    if (ok(left) && left >= 0 && left <= 3) items.push({when: new Date(Date.now() + left * 864e5).toISOString(), txt: `${esc(t.name)} <span class="small muted">reaches its ${q.timeDte} DTE time stop ${left === 0 ? "today" : `in ${left} day${left > 1 ? "s" : ""}`}</span>`});
    else if (q.dte <= 3) items.push({when: new Date(Date.now() + q.dte * 864e5).toISOString(), txt: `${esc(t.name)} <span class="small muted">first expiry in ${q.dte} days</span>`}); });
  items.sort((a, b) => String(a.when).localeCompare(String(b.when)));
  const note = H ? H.feed_note : Rd && Rd.events_feed ? Rd.events_feed.note : "Calendar feed unavailable.";
  $("acComing").innerHTML = (note ? `<div class="state err" style="margin-bottom:6px">${esc(note)}</div>` : "") + (items.length ? `<ul class="small" style="margin:0;padding-left:18px">${items.map((i) => `<li><span class="mono muted">${esc(new Date(i.when).toLocaleDateString([], {weekday: "short", day: "numeric", month: "short", timeZone: "America/New_York"}))}</span> ${i.txt}</li>`).join("")}</ul>`
    : note ? "" : `<div class="state">No medium or high-impact releases or time stops in the next 3 trading days.</div>`);
}

function checks(Rk, Fr, Sn) {
  const bad = [];
  if (Fr) Fr.sources.filter((x) => x.stale).forEach((x) => bad.push(`<b>${esc(x.name)}</b> is older than the last close <span class="muted">(${esc(x.what)})</span>`));
  if (Rk && Rk.one_fresh && Rk.one_fresh.stale) bad.push(`<b>ONE report</b> is ${Rk.one_fresh.age_h != null ? Math.round(Rk.one_fresh.age_h) + "h old" : "missing"}${Rk.one_fresh.fills_since ? ` and IBKR has ${Rk.one_fresh.fills_since} fills since` : ""}: export it so the plan sees your latest trades`);
  if (Rk && Rk.marks_ts && Date.now() - Date.parse(Rk.marks_ts) > 18 * 3600e3) bad.push(`<b>TWS marks</b> are from ${esc(new Date(Rk.marks_ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"}))}: refresh them in the Risk grid for current totals and alert levels`);
  if (Rk && !Rk.marks_ts) bad.push("<b>No TWS marks yet</b>: press Refresh in the Risk grid with TWS running");
  if (Rk && Rk.missing && Rk.missing.length) bad.push(`<b>${Rk.missing.length} legs</b> had no TWS quote at the last refresh`);
  if (Rk && !Rk.detail_exported) bad.push("<b>No ONE Detail Report</b>: adjustment counts (used by the adjustment gates) are unknown");
  const H = window.HEADS;
  if (H) { Object.values(H.feeds).filter((f) => !f.ok).forEach((f) => bad.push(`<b>${esc(f.name)}</b>: ${f.note ? esc(f.note) : `feed unavailable, last good copy in use${f.err ? ` <span class="muted">(${esc(f.err)})</span>` : ""}`}`));
    if (H.known_to && Date.parse(H.known_to) - Date.now() < 60 * 864e5) bad.push(`<b>Known-events list</b> ends ${esc(H.known_to)}: add next year's CPI, payrolls and FOMC dates to KNOWN in desk/market.py`); }
  else bad.push("<b>Heads-up feeds</b> could not be read: event risk is unknown");
  if (Sn && !Sn.key_set) bad.push(`<b>Cloud snapshot passphrase not set</b>: your trades aren't on the GitHub copy yet ${go("rec", "Recorder")}`);
  if (Sn && Sn.error) bad.push(`<b>Cloud snapshot</b>: ${esc(Sn.error)}`);
  $("acChkMeta").textContent = bad.length ? `${bad.length} to look at` : "all current";
  subBtn("Data check").textContent = bad.length ? `Data check (${bad.length})` : "Data check";
  if (bad.length && !$("acMore")._cur) showSub($("acMore"), "Data check");
  $("acChecks").innerHTML = bad.length ? `<ul class="small" style="margin:0;padding-left:18px">${bad.map((b) => `<li>${b}</li>`).join("")}</ul>` : `<div class="state">All data current.</div>`;
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("#tab-actions a"); if (!a) return;
  e.preventDefault();
  if (a.dataset.trade) { showTab("risk"); setTimeout(() => window.riskOpen && window.riskOpen(a.dataset.trade), 300); return; }
  if (a.dataset.ready) { const b = document.getElementById("rdOpen"); if (b) b.click(); return; }
  if (a.dataset.go) { showTab(a.dataset.go); if (a.dataset.go === "rec") { const p = $("snapPanel"); if (p) setTimeout(() => p.scrollIntoView({behavior: "smooth"}), 200); } if (a.dataset.sub) { const host = document.querySelector(`#tab-${a.dataset.go} [data-subs]`); if (host && host._showSub) host._showSub(a.dataset.sub); } }
});
window.addEventListener("heads", () => { if (L) coming(pick(L.Rk), L.Rd); });
const rf = () => { const b = $("acReload"); if (b) b.addEventListener("click", () => { if (window.riskStale) window.riskStale(); load(); }); };
document.addEventListener("DOMContentLoaded", rf);
window.loadActions = load;
})();
