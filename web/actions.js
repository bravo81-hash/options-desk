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
  render(); entries(Rd); checks(Rk, Fr, Sn);
  ideas(Rd);  // last: the scanner can take a few seconds the first time after a new chain
}

function doToday(Rk) {
  if (!Rk) { $("acDo").innerHTML = `<div class="state">${window.DESK_CLOUD ? "Unlock your snapshot (top bar) to see your trades." : "Open trades unavailable: is the ONE Summary Report in Documents?"}</div>`; return; }
  const P = Rk.trades.filter((t) => t.plan && t.plan.act !== "hold").sort((a, b) => a.plan.pri - b.plan.pri || (a.totalPct ?? 0) - (b.totalPct ?? 0));
  const held = Rk.trades.filter((t) => t.plan && t.plan.act === "hold").length, noCard = Rk.trades.filter((t) => !t.plan).length;
  $("acDoMeta").textContent = `${Rk.trades.length}${active() ? ` of ${L.Rk.trades.length}` : ""} open trades · ${P.length} need something · ${held} on hold${noCard ? ` · ${noCard} without card rules` : ""}`;
  if (!P.length) { $("acDo").innerHTML = `<div class="state">Nothing to do on ${active() ? "the filtered" : "open"} trades: every carded trade is between its stop and target. ${go("risk", "Trade plan", "Trade plan")}</div>`; return; }
  $("acDo").innerHTML = `<div class="tbl"><table><thead><tr><th>Do</th><th>Trade</th><th class="n">Total</th><th>Why</th><th>Order to use</th><th></th></tr></thead><tbody>${
    P.map((t) => { const q = t.plan, [k, word] = ACT[q.act] || ["", q.label];
      const use = q.act === "exit" ? `close now${q.stopPx ? ` · combo ~${q.stopPx.px.toFixed(2)}` : ""}`
        : q.act === "close" ? `close now · target order ${order(q.order)}`
        : q.act === "slow" ? `close at the next close ≥ 0%${q.order ? ` · or keep the target order ${order(q.order)}` : ""}`
        : `adjust: <span class="chip">${esc(q.adj.ok)}</span>${q.how ? ` <span class="small muted">${esc(q.how)}</span>` : ""}`;
      return `<tr><td><span class="chip ${k}">${esc(word)}</span></td><td>${esc(t.name)} <span class="small muted">${esc(t.acctLabel || "")}</span></td>
        <td class="n ${cls(t.totalPct)}"><b>${pctS(t.totalPct)}</b> <span class="small muted">${money(t.pnlNow)}</span></td><td class="small" style="white-space:normal;min-width:240px">${esc(q.why)}</td><td class="small" style="white-space:normal;min-width:200px">${use}</td>
        <td><a href="#" class="small" data-trade="${esc(t.id)}">detail →</a></td></tr>`; }).join("")}</tbody></table></div>`;
}

function entries(Rd) {
  if (!Rd || Rd.error) { $("acNew").innerHTML = `<div class="state">${esc((Rd && Rd.error) || "Readiness unavailable")}</div>`; return; }
  const open = Rd.strategies.filter((s) => s.size !== "Stand aside");
  $("acNewMeta").innerHTML = `market size: <b class="${SIZE_CLS[Rd.size] || ""}">${esc(Rd.size)}</b>`;
  $("acNew").innerHTML = `<div class="kv mini">${Rd.strategies.map((s) => `<div><span class="lbl">${esc(s.name)}</span><b class="${SIZE_CLS[s.size] || ""}">${esc(s.size)}</b><span class="small muted">${esc(s.notes[0] || "")}</span></div>`).join("")}</div>
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
  $("acOrders").innerHTML = `<div class="tbl"><table><thead><tr><th>Trade</th><th class="n">GTC target close</th><th class="n">Alert: decide</th><th class="n">Alert: stop</th></tr></thead><tbody>${
    P.sort((a, b) => a.underlying.localeCompare(b.underlying) || a.firstExp - b.firstExp).map((t) => { const q = t.plan;
      return `<tr><td class="small">${esc(t.name)} <span class="muted">${esc(t.acctLabel || "")}</span></td><td class="n small">${order(q.order)}</td><td class="n small">${lv(q.at && q.at.decide, t.underlying)}</td><td class="n small">${lv(q.at && q.at.stop, t.underlying)}</td></tr>`; }).join("")}</tbody></table></div>
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
