/* Actions: everything that needs doing today, on one screen. Each item links to the tab with the detail. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const SIZE_CLS = {"Full size": "pos", "Three-quarter size": "pos", "Half size": "wrn", "Quarter size": "wrn", "Stand aside": "neg"};
const ACT = {exit: ["neg", "Exit"], decide: ["neg", "Decide"], close: ["pos", "Close"], slow: ["wrn", "Exit at next green"]};
const go = (tab, text, sub) => `<a href="#" class="small" data-go="${tab}"${sub ? ` data-sub="${esc(sub)}"` : ""}>${esc(text)} →</a>`;
const order = (o) => o ? `${o.side} ${o.units}× at <b class="mono">${o.px.toFixed(2)}</b>` : "–";
const dist = (t) => { const q = t.plan, a = q && q.at, pc = (x) => ok(x) && ok(t.spot) ? 100 * (x / t.spot - 1) : null;
  if (!a || !ok(t.spot)) return "";
  const m = [[a.decide, "var(--warn)", "decide"], [a.stop, "var(--down)", "stop"]].flatMap(([L, c, nm]) => !L || L.past ? [] : [[L.dn, "↓"], [L.up, "↑"]].filter(([x]) => ok(x)).map(([x, d]) => ({v: pc(x), color: c, label: `${nm} ${d} ${Math.round(x)} (${pctS(pc(x))} from spot)`})));
  return bulletSvg(0, {w: 150, lo: -10, hi: 6, color: "var(--accent)", label: "index now (dot) and its alert levels, % from spot",
    zones: [{from: -10, to: 6, color: "var(--soft)"}], marks: m.filter((x) => ok(x.v))});
};
const lv = (L, u) => !L ? "–" : L.past ? "already past" : [L.dn ? `${u} ↓ <b class="mono">${Math.round(L.dn).toLocaleString()}</b>` : null, L.up ? `↑ <b class="mono">${Math.round(L.up).toLocaleString()}</b>` : null].filter(Boolean).join(" · ") || "beyond −25% / +15%";

/* ---------- filters: ticker, first expiry, account (remembered on this browser) ---------- */
let L = null, SCAN = null;
const FK = "od.acFilt";
let F = (() => { try { return JSON.parse(localStorage.getItem(FK)) || {}; } catch (e) { return {}; } })();
const expKey = (t) => new Date(t.firstExp).toLocaleDateString("en-CA", {timeZone: "America/New_York"});  // expiry date in New York (16:00 ET is next morning in Sydney)
const expTxt = (k) => new Date(k + "T12:00:00").toLocaleDateString([], {day: "numeric", month: "short", year: "2-digit"});
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
    ${active() ? `<button type="button" class="ghost" id="acFClear">Clear filters</button><span class="small muted">showing ${pick(L.Rk).trades.length} of ${T.length} open trades · releases and data checks are not filtered</span>` : `<span class="small muted">filters apply to the trade lists and the A14 shapes (ticker)</span>`}`;
  el.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => { F[s.dataset.f] = s.value || undefined; save(); render(); }));
  const c = $("acFClear"); if (c) c.addEventListener("click", () => { F = {}; save(); render(); });
}
const save = () => { try { localStorage.setItem(FK, JSON.stringify(F)); } catch (e) {} };

function render() {
  filters();
  const V = pick(L.Rk);
  doToday(V); orders(V); coming(V, L.Rd); ideasRender();
}

async function load() {
  const host = $("acDo"); if (!host) return;
  $("acWhen").textContent = new Date().toLocaleString([], {weekday: "long", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"});
  const [Rk, Rd, Fr, Sn] = await Promise.all([
    window.riskActions ? window.riskActions().catch(() => null) : null,
    api("/api/readiness").catch(() => null), api("/api/freshness").catch(() => null),
    window.DESK_CLOUD ? null : api("/api/snapshot").catch(() => null)]);
  L = {Rk, Rd}; SCAN = null;
  render(); entries(Rd); checks(Rk, Fr, Sn); conditions(); matrix(Rd);
  ideas(Rd);  // last: the scanner can take a few seconds the first time after a new chain
}

function doToday(Rk) {
  if (!Rk) { $("acDo").innerHTML = `<div class="state">${window.DESK_CLOUD ? "Unlock your snapshot (top bar) to see your trades." : "Open trades unavailable: is the ONE Summary Report in Documents?"}</div>`; return; }
  const P = Rk.trades.filter((t) => t.plan && t.plan.act !== "hold").sort((a, b) => a.plan.pri - b.plan.pri || (a.totalPct ?? 0) - (b.totalPct ?? 0));
  const held = Rk.trades.filter((t) => t.plan && t.plan.act === "hold").length, noCard = Rk.trades.filter((t) => !t.plan).length;
  $("acDoMeta").textContent = `${Rk.trades.length}${active() ? ` of ${L.Rk.trades.length}` : ""} open trades · ${P.length} need something · ${held} on hold${noCard ? ` · ${noCard} without card rules` : ""}`;
  if (!P.length) { $("acDo").innerHTML = `<div class="state">Nothing to do on ${active() ? "the filtered" : "open"} trades: every carded trade is between its stop and target. ${go("risk", "Trade plan", "Trade plan")}</div>`; return; }
  $("acDo").innerHTML = `<div class="tbl"><table><thead><tr><th>Do</th><th>Trade</th><th class="n" title="dot = total now · red line = hard stop · dashed = decide line · green line = target">Total · stop → target</th><th>Why</th><th>Order to use</th><th></th></tr></thead><tbody>${
    P.map((t) => { const q = t.plan, [k, word] = ACT[q.act] || ["", q.label];
      const use = q.act === "exit" ? `close now${q.stopPx ? ` · combo ~${q.stopPx.px.toFixed(2)}` : ""}`
        : q.act === "close" ? `close now · target order ${order(q.order)}`
        : q.act === "slow" ? `close at the next close ≥ 0%${q.order ? ` · or keep the target order ${order(q.order)}` : ""}`
        : `adjust: <span class="chip">${esc(q.adj.ok)}</span>${q.how ? ` <span class="small muted">${esc(q.how)}</span>` : ""}`;
      return `<tr><td><span class="chip ${k}">${esc(word)}</span></td><td>${esc(t.name)} <span class="small muted">${esc(t.acctLabel || "")}</span></td>
        <td class="n ${cls(t.totalPct)}"><b>${pctS(t.totalPct)}</b> <span class="small muted">${money(t.pnlNow)}</span><br>${window.planBullet ? window.planBullet(t) : ""}</td><td class="small" style="white-space:normal;min-width:240px">${esc(q.why)}</td><td class="small" style="white-space:normal;min-width:200px">${use}</td>
        <td><a href="#" class="small" data-trade="${esc(t.id)}">detail →</a></td></tr>`; }).join("")}</tbody></table></div>`;
}

/* ---------- market conditions: one row per signal from the other tabs (desk/conditions.py) ---------- */
const TABLINK = {"Market": "market", "Term structure": "today", "Skew & IV": "skew", "Expected moves": "em", "Seasonality": "season"};
const EFF = {helps: ["pos", "helps"], hurts: ["neg", "hurts"], neutral: ["", "neutral"], thin: ["muted", "few entries"], none: ["muted", "no data"], "n/a": ["muted", "n/a"]};
let condTries = 0;

async function conditions() {
  const el = $("acCond"); if (!el) return;
  const C = await api("/api/conditions").catch((e) => ({error: e.message}));
  if (!C || C.running || C.error) {
    el.innerHTML = `<div class="state">${C && C.error ? esc(C.error) : "Backtest computing (about 10 seconds after an update)…"}</div>`;
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
      return `<td class="n" title="${esc(c.bucket ? `today's bucket ${c.bucket}` : "")}"${tint ? ` style="background:color-mix(in srgb, ${tint} 10%, transparent)"` : ""}>${c.dist && c.dist.length ? sparkBars(c.dist.map((x) => ({label: x.b, v: x.avg, n: x.n, sel: x.sel})), {label: `${s}: average by ${r.label} bucket`}) + "<br>" : ""}<span class="chip ${k}">${word}</span>${ok(c.avg) ? `<br><span class="small ${cls(c.avg)}">${pctS(c.avg)}</span><span class="small muted"> vs ${pctS(c.base)} · n ${c.n}</span>` : ""}</td>`; }).join("");
    return `${head}<tr><td style="padding-left:14px">${esc(r.label)}</td><td class="small mono">${esc(r.reading)}</td>${cells}<td class="small muted" style="white-space:normal;min-width:180px">${esc(r.in_size)}</td></tr>`;
  }).join("");
  const sizeRow = `<tr style="border-top:2px solid var(--line)"><td><b>Size call</b> <span class="small muted">readiness bar</span></td><td class="small">market: <b>${esc(C.size)}</b></td>${S.map((s) => { const st = C.strategies[s];
    return `<td class="n"><b class="${SIZE_CLS[st && st.size] || ""}">${esc(st ? st.size : "–")}</b><br><span class="small muted">${tally[s].helps} help · ${tally[s].hurts} hurt</span></td>`; }).join("")}<td></td></tr>`;
  const f21 = C.season && C.season.fwd21;
  el.innerHTML = `<div class="tbl"><table><thead><tr><th>Signal</th><th>Today${C.date ? ` <span class="muted">(${esc(C.date)})</span>` : ""}</th>${S.map((s) => `<th class="n">${s}</th>`).join("")}<th>In the size call?</th></tr></thead><tbody>${body}${sizeRow}</tbody></table></div>
    <div class="kv mini" style="margin-top:8px">${C.odds.map((o) => `<div><span class="lbl">${esc(o.name)}</span><b class="${o.dd5 > C.base_dd5 * 1.3 ? "neg" : o.dd5 < C.base_dd5 * 0.85 ? "pos" : ""}">${ok(o.dd5) ? o.dd5.toFixed(0) + "%" : "–"}</b>${ok(o.dd5) && window.oddsBar ? window.oddsBar(o.dd5, C.base_dd5) : ""}<span class="small muted">chance of a 5% SPX drop in 21 sessions (normally ${C.base_dd5.toFixed(0)}%) · ${esc(o.reading || "")}</span></div>`).join("")}
      ${f21 ? `<div><span class="lbl">Seasonality, next 21 sessions</span><b>${f21.up.toFixed(0)}% up</b><span class="small muted">avg ${pctS(f21.mean)}, worst ${pctS(f21.worst)} over the last ${f21.n} years · ${esc(C.season.cycle || "")} year</span></div>` : ""}
      <div><span class="lbl">High-impact releases, 3 days</span><b class="${C.events.length ? "wrn" : ""}">${C.events.length ? [...new Set(C.events.map((e) => e.title))].length + " releases" : "none"}</b><span class="small muted">${esc([...new Set(C.events.map((e) => e.title))].join(", ") || "calendars step down into CPI, FOMC, payrolls, PCE, GDP")}</span></div></div>
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

function matrixRender(Rd) {
  const size = Rd.size, cur = Rd.ivts_band.band;
  const trendOf = (s) => (Rd.trends[s.split(" ")[1]] || {}).short_up ? "above" : "below";
  const cell = (s, b, t) => {
    const steps = Rd.matrix[s.split(" ")[0]][b][t];
    const sz = steps === null ? "Stand aside" : STEPS[Math.max(0, STEPS.indexOf(size) - steps)];
    const chip = steps === null ? `<span class="chip neg">stand aside</span>`
      : `<span class="chip ${steps ? "wrn" : "pos"}">${steps ? `−${steps} step${steps > 1 ? "s" : ""}` : "no step"} → ${SHORT[sz]}</span>`;
    const r = BT && BT.matrix && BT.matrix[s] && BT.matrix[s].cells[b] && BT.matrix[s].cells[b][t];
    const now = b === cur && t === trendOf(s);
    const tint = r ? `background:color-mix(in srgb, ${r.avg >= 0 ? "var(--up)" : "var(--down)"} ${Math.round(Math.min(Math.abs(r.avg) / 5, 1) * 28)}%, transparent);` : "";
    return `<td class="n" style="${tint}${now ? "outline:2px solid var(--accent);outline-offset:-2px" : ""}">${chip}<br><span class="small ${r ? cls(r.avg) : "muted"}">${r ? `${pctS(r.avg)} · ${Math.round(100 * r.win)}% won` : BT && BT.matrix ? "no entries" : "computing…"}</span>${r ? ` <span class="small muted">n ${r.n}</span>` : ""}</td>`;
  };
  const rows = BANDS.flatMap(([b, name, rng]) => ["above", "below"].map((t, k) => `<tr${b === cur ? ` style="background:color-mix(in srgb, var(--accent) 7%, transparent)"` : ""}>${k ? "" : `<td rowspan="2"><b>${name}</b><br><span class="small muted">VIX/VIX3M ${rng}</span></td>`}
    <td class="small">${t} 20-day avg</td>${STRUCTS.map((s) => cell(s, b, t)).join("")}</tr>`)).join("");
  $("acMatrix").innerHTML = `<p class="small" style="margin:0 0 6px">Today: VIX/VIX3M <b>${fmt(Rd.ivts, 3)}</b> (${esc(Rd.ivts_band.label)}) · SPX ${trendOf("A14 SPX")} and RUT ${trendOf("A14 RUT")} their 20-day averages · market size <b>${esc(size)}</b> (${esc(Rd.why)}).</p>
    <div class="tbl"><table><thead><tr><th>Term structure</th><th>Index vs</th>${STRUCTS.map((s) => `<th class="n">${s}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">How to read it: the market size (from the drop odds in the readiness bar) is the starting point; each cell shows the steps the term-structure and trend rules take off it, and the size that leaves today. Other flags on top: thin RUT premium (RVX within 3 pts of VIX) steps RUT A14s down, a high-impact release within 3 days steps calendars down. Results: A14 = 45 DTE, your median shape, revised exits (target 7%, stop −20%, time and pace), % of max loss; calendars = 15/22 DTE ATM put calendar, target 5%, stop −15%, % of the debit. The model uses one fixed skew shape, so it shows the term-structure and trend effect, not that day's skew.</p>`;
}

function entries(Rd) {
  if (!Rd || Rd.error) { $("acNew").innerHTML = `<div class="state">${esc((Rd && Rd.error) || "Readiness unavailable")}</div>`; return; }
  const open = Rd.strategies.filter((s) => s.size !== "Stand aside");
  $("acNewMeta").innerHTML = `market size: <b class="${SIZE_CLS[Rd.size] || ""}">${esc(Rd.size)}</b>`;
  $("acNew").innerHTML = `<div class="kv mini">${Rd.strategies.map((s) => `<div><span class="lbl">${esc(s.name)}</span><b class="${SIZE_CLS[s.size] || ""}">${esc(s.size)}</b>${sizeMeter(s.size)}<span class="small muted">${esc(s.notes[0] || "")}</span></div>`).join("")}</div>
    <p class="small">${open.length ? `Open for new trades: <b>${open.map((s) => esc(s.name)).join(", ")}</b>. Best shapes below.` : `<b>No new entries today.</b> ${esc(Rd.why)}.`} <a href="#" class="small" data-ready="1">why →</a></p>`;
}

async function ideas(Rd) {
  const want = Rd && !Rd.error ? Rd.strategies.filter((x) => x.name.startsWith("A14") && x.size !== "Stand aside").map((x) => x.name.split(" ")[1]) : [];
  $("acIdeas").innerHTML = `<div class="state">Ranking A14 shapes on history…</div>`;
  const A = await api("/api/a14/scan?sym=SPX,RUT&vol=rv20").catch(() => null);
  SCAN = {A, want}; ideasRender();
}

function ideasRender() {
  const el = $("acIdeas"); if (!SCAN) return;
  const {A, want} = SCAN;
  if (!A || A.error || !A.candidates) { el.innerHTML = `<div class="state">${esc((A && A.error) || "No A14 chain yet.")} ${go("a14", "A14 scanner", "Scanner")}</div>`; return; }
  const pickN = (u) => A.candidates.filter((c) => c.sym === u && ok(c.hist_day)).sort((a, b) => b.hist_day - a.hist_day).slice(0, 2);
  const syms = ["SPX", "RUT"].filter((u) => !F.sym || F.sym === u);
  if (!syms.length) { el.innerHTML = `<div class="state small">No A14 scan for ${esc(F.sym)}.</div>`; return; }
  const rows = syms.flatMap((u) => pickN(u).map((c) => ({...c, live: want.includes(u)})));
  el.innerHTML = `<div class="tbl"><table><thead><tr><th>Best A14 shape on history</th><th class="n">Credit</th><th class="n">Risk</th><th class="n">Since 2009</th><th class="n">Target / stop</th></tr></thead><tbody>${
    rows.map((c) => `<tr class="${c.live ? "" : "muted"}"><td>${c.sym} ${esc(String(c.expiry).slice(4, 6) + "/" + String(c.expiry).slice(6))} <span class="small muted">${c.dte}d</span> <span class="mono">${Math.round(c.upper)}/${Math.round(c.short)}/${Math.round(c.lower)}</span>${c.live ? "" : ` <span class="chip">stand aside</span>`}</td>
      <td class="n mono ${cls(c.credit)}">${c.credit > 0 ? "+" : ""}${c.credit.toFixed(2)}</td><td class="n">${money(c.risk)}</td><td class="n ${cls(c.hist_avg)}">${pctS(c.hist_avg)} <span class="small muted">${c.hist_day.toFixed(2)}%/d</span></td>
      <td class="n small">${Math.round(100 * c.hist_ptgt)}% / ${Math.round(100 * c.hist_pstop)}%</td></tr>`).join("")}</tbody></table></div>
    <p class="note">Top two per index by return per day held since 2009 in today's term structure, with your exits. Greyed = the readiness bar says stand aside for that index. ${go("a14", "A14 scanner", "Scanner")}</p>`;
}

function orders(Rk) {
  if (!Rk) { $("acOrders").innerHTML = ""; return; }
  const P = Rk.trades.filter((t) => t.plan && (t.plan.order || t.plan.at));
  if (!P.length) { $("acOrders").innerHTML = `<div class="state">No carded trades${active() ? " in the filter" : ""}.</div>`; return; }
  $("acOrders").innerHTML = `<div class="tbl"><table><thead><tr><th>Trade</th><th class="n">GTC target close</th><th class="n">Alert: decide</th><th class="n">Alert: stop</th><th title="dot = index now; orange = decide alert, red = stop alert; scale −10% to +6% from spot">How far</th></tr></thead><tbody>${
    P.sort((a, b) => a.underlying.localeCompare(b.underlying) || a.firstExp - b.firstExp).map((t) => { const q = t.plan;
      return `<tr><td class="small">${esc(t.name)} <span class="muted">${esc(t.acctLabel || "")}</span></td><td class="n small">${order(q.order)}</td><td class="n small">${lv(q.at && q.at.decide, t.underlying)}</td><td class="n small">${lv(q.at && q.at.stop, t.underlying)}</td><td>${dist(t)}</td></tr>`; }).join("")}</tbody></table></div>
    <p class="note">Target orders are valid until you adjust the trade; re-enter after any adjustment. Alert levels assume the move happens today with IVs unchanged; refresh marks to update them. ${go("risk", "Trade plan", "Trade plan")}</p>`;
}

function coming(Rk, Rd) {
  const items = [];
  const byDay = {};  // one line per day of high-impact releases
  (Rd && Rd.events || []).forEach((e) => { const d = new Date(e.date).toDateString(); (byDay[d] = byDay[d] || {when: e.date, t: []}).t.push(e.title); });
  Object.values(byDay).forEach((d) => items.push({when: d.when, txt: `<b>${esc([...new Set(d.t)].join(", "))}</b> <span class="small muted">high-impact: no new calendars into it</span>`}));
  if (Rk) Rk.trades.forEach((t) => { const q = t.plan; if (!q || !ok(q.dte)) return;
    const left = ok(q.timeDte) ? q.dte - q.timeDte : null;
    if (ok(left) && left >= 0 && left <= 3) items.push({when: new Date(Date.now() + left * 864e5).toISOString(), txt: `${esc(t.name)} <span class="small muted">reaches its ${q.timeDte} DTE time stop ${left === 0 ? "today" : `in ${left} day${left > 1 ? "s" : ""}`}</span>`});
    else if (q.dte <= 7) items.push({when: new Date(Date.now() + q.dte * 864e5).toISOString(), txt: `${esc(t.name)} <span class="small muted">first expiry in ${q.dte} days</span>`}); });
  items.sort((a, b) => String(a.when).localeCompare(String(b.when)));
  $("acComing").innerHTML = items.length ? `<ul class="small" style="margin:0;padding-left:18px">${items.map((i) => `<li><span class="mono muted">${esc(new Date(i.when).toLocaleDateString([], {weekday: "short", day: "numeric", month: "short"}))}</span> ${i.txt}</li>`).join("")}</ul>`
    : `<div class="state">No high-impact releases or time stops in the next 3 days.</div>`;
}

function checks(Rk, Fr, Sn) {
  const bad = [];
  if (Fr) Fr.sources.filter((x) => x.stale).forEach((x) => bad.push(`<b>${esc(x.name)}</b> is older than the last close <span class="muted">(${esc(x.what)})</span>`));
  if (Rk && Rk.one_fresh && Rk.one_fresh.stale) bad.push(`<b>ONE Summary Report</b> is ${Rk.one_fresh.age_h != null ? Math.round(Rk.one_fresh.age_h) + "h old" : "missing"}${Rk.one_fresh.fills_since ? ` and IBKR has ${Rk.one_fresh.fills_since} fills since` : ""}: export it so the plan sees your latest trades`);
  if (Rk && Rk.marks_ts && Date.now() - Date.parse(Rk.marks_ts) > 18 * 3600e3) bad.push(`<b>TWS marks</b> are from ${esc(new Date(Rk.marks_ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"}))}: refresh them in the Risk grid for current totals and alert levels`);
  if (Rk && !Rk.marks_ts) bad.push("<b>No TWS marks yet</b>: press Refresh in the Risk grid with TWS running");
  if (Rk && Rk.missing && Rk.missing.length) bad.push(`<b>${Rk.missing.length} legs</b> had no TWS quote at the last refresh`);
  if (Rk && !Rk.detail_exported) bad.push("<b>No ONE Detail Report</b>: adjustment counts (used by the adjustment gates) are unknown");
  if (Sn && !Sn.key_set) bad.push(`<b>Cloud snapshot passphrase not set</b>: your trades aren't on the GitHub copy yet ${go("rec", "Recorder")}`);
  if (Sn && Sn.error) bad.push(`<b>Cloud snapshot</b>: ${esc(Sn.error)}`);
  $("acChecks").innerHTML = bad.length ? `<ul class="small" style="margin:0;padding-left:18px">${bad.map((b) => `<li>${b}</li>`).join("")}</ul>` : `<div class="state">All data current.</div>`;
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("#tab-actions a"); if (!a) return;
  e.preventDefault();
  if (a.dataset.trade) { showTab("risk"); setTimeout(() => window.riskOpen && window.riskOpen(a.dataset.trade), 300); return; }
  if (a.dataset.ready) { const b = document.getElementById("rdOpen"); if (b) b.click(); return; }
  if (a.dataset.go) { showTab(a.dataset.go); if (a.dataset.go === "rec") { const p = $("snapPanel"); if (p) setTimeout(() => p.scrollIntoView({behavior: "smooth"}), 200); } if (a.dataset.sub) { const host = document.querySelector(`#tab-${a.dataset.go} [data-subs]`); if (host && host._showSub) host._showSub(a.dataset.sub); } }
});
const rf = () => { const b = $("acReload"); if (b) b.addEventListener("click", load); };
document.addEventListener("DOMContentLoaded", rf);
window.loadActions = load;
})();
