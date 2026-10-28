/* P&L and reconciliation tab (folded in from TWS Matcher). */
"use strict";
(() => {
const oneStale = (R) => { const f = R.one_fresh; if (!f || !f.stale) return "";
  return `<div class="state err" style="margin-bottom:6px"><b>ONE export is ${f.age_h != null ? Math.round(f.age_h) + "h old" : "missing"}${f.fills_since ? ` and IBKR has ${f.fills_since} fill${f.fills_since > 1 ? "s" : ""} since` : ""}</b> — differences below may just be trades not yet in the report. Export a fresh ONE Summary Report, then reload.</div>`; };
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const pctS = (v, d = 2) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const heat = (v, full) => !ok(v) ? "" : `background:color-mix(in srgb, var(${v >= 0 ? "--up" : "--down"}) ${Math.round(Math.min(Math.abs(v) / full, 1) * 45)}%, transparent)`;
const dlabel = (d) => new Date(d + "T12:00:00Z").toLocaleDateString([], {day: "numeric", month: "short", timeZone: "UTC"});
let W = null, T = null, R = null;

function strip() {
  const labels = (T && T.labels) || {};
  const accts = Object.keys((T && T.daily) || {});
  const tile = (l, b, sub, k = "") => `<div><span class="lbl">${l}</span><span class="big ${k}">${b}</span><span class="small muted">${sub}</span></div>`;
  if (!accts.length) { $("plStrip").innerHTML = tile("Today", "–", "press Refresh from TWS (TWS must be running)"); return; }
  let tot = 0, totNav = 0, totIb = 0;
  const ch = T.nav_change || {}, prior = T.prior || {};
  const tiles = accts.sort().map((a) => { const d = T.daily[a] || {}, nav = (T.nav || {})[a], v = ok(ch[a]) ? ch[a] : null;
    tot += v || 0; totNav += nav || 0; totIb += d.daily || 0;
    const since = prior[a] ? dlabel(prior[a].date) : "";
    return tile(`${labels[a] || a} · change in NAV`, money(v), `NAV ${money(nav)} ${(T.currency || {})[a] || ""} · ${pctS(nav && ok(v) ? 100 * v / (nav - v) : null)} since ${since} close<br>IBKR's own day P&L ${money(d.daily)}`, cls(v)); });
  $("plStrip").innerHTML = tile("All accounts · change in NAV", money(tot), `session ${T.session ? dlabel(T.session) : ""} · NAV ${money(totNav)}<br>IBKR's own day P&L ${money(totIb)}`, cls(tot)) + tiles.join("");
}

function weekly() {
  if (!W || !W.weeks.length) { $("plWeekly").innerHTML = `<div class="state">No daily P&L recorded yet.</div>`; return; }
  const pct = $("plUnit").value === "pct", A = W.accounts;
  const cell = (c) => { if (!c || c.pnl == null) return `<td class="n muted" title="no earlier NAV to compare with yet">–</td>`; const v = pct ? c.pct : c.pnl;
    const tip = c.daily.map((d) => `${dlabel(d.date)}: ${money(d.pnl)}`).join("\n");
    return `<td class="n mono" style="${heat(pct ? c.pct : c.pnl, pct ? 3 : 10000)}" title="${esc(tip)}">${pct ? pctS(v) : money(v)}</td>`; };
  let rows = "";
  W.weeks.forEach((w) => {
    const tot = A.reduce((s, a) => s + ((w.acct[a.id] || {}).pnl || 0), 0);
    const navs = A.reduce((s, a) => s + (((w.acct[a.id] || {}).end_nav || 0) - ((w.acct[a.id] || {}).pnl || 0)), 0);
    const totPct = navs ? 100 * tot / navs : null;
    const note = (w.notes || []).join(" · ");
    rows += `<tr><td>Week of ${dlabel(w.week)} ${note ? `<span class="small ${w.notes.some((n) => n.includes("not captured")) ? "wrn" : "muted"}" title="${esc(note)}">${esc(note.length > 70 ? note.slice(0, 68) + "…" : note)}</span>` : ""}</td>${A.map((a) => cell(w.acct[a.id])).join("")}
      <td class="n mono" style="${heat(pct ? totPct : tot, pct ? 3 : 20000)}"><b>${pct ? pctS(totPct) : money(tot)}</b></td></tr>`;
  });
  $("plWeekly").innerHTML = `<div class="chart" id="plWeekChart"></div><div class="tbl"><table><thead><tr><th>Week (US dates)</th>${A.map((a) => `<th class="n">${esc(a.label)}</th>`).join("")}<th class="n">All accounts</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  const wk = W.weeks.slice().sort((a, b) => a.week.localeCompare(b.week)).map((w) => {
    const tot = A.reduce((s, a) => s + ((w.acct[a.id] || {}).pnl || 0), 0), navs = A.reduce((s, a) => s + (((w.acct[a.id] || {}).end_nav || 0) - ((w.acct[a.id] || {}).pnl || 0)), 0);
    return {label: dlabel(w.week), v: pct ? (navs ? 100 * tot / navs : null) : tot / 1000,
      title: `Week of ${esc(dlabel(w.week))}: <b>${pct ? pctS(navs ? 100 * tot / navs : null) : money(tot)}</b>` + A.map((a) => `<div>${esc(a.label)} ${money((w.acct[a.id] || {}).pnl)}</div>`).join("")}; });
  barChart($("plWeekChart"), {label: "weekly P&L, all accounts", h: 150, unit: pct ? "%" : "k", items: wk});
  // monthly from the same daily rows
  const months = {};
  W.weeks.forEach((w) => A.forEach((a) => ((w.acct[a.id] || {}).daily || []).forEach((d) => {
    const m = d.date.slice(0, 7); const o = (months[m] = months[m] || {});
    const c = (o[a.id] = o[a.id] || {pnl: 0, first: null, days: 0}); c.pnl += d.pnl || 0; c.days++;
    if (!c.first || d.date < c.first.date) c.first = d; })));
  const mkeys = Object.keys(months).sort().reverse();
  $("plMonthly").innerHTML = `<div class="chart" id="plMonthChart"></div><div class="tbl"><table><thead><tr><th>Month</th>${A.map((a) => `<th class="n">${esc(a.label)}</th>`).join("")}<th class="n">All</th></tr></thead><tbody>${
    mkeys.map((m) => { const o = months[m], tot = A.reduce((s, a) => s + ((o[a.id] || {}).pnl || 0), 0);
      const lab = new Date(m + "-15T12:00:00Z").toLocaleDateString([], {month: "short", year: "numeric", timeZone: "UTC"});
      return `<tr><td>${lab} <span class="small muted">${Math.max(...A.map((a) => (o[a.id] || {}).days || 0))} days</span></td>${A.map((a) => { const c = o[a.id]; if (!c) return `<td class="n muted">–</td>`;
        const base = c.first && c.first.nav ? c.first.nav - (c.first.pnl || 0) : null, p = base ? 100 * c.pnl / base : null;
        return `<td class="n mono" style="${heat(pct ? p : c.pnl, pct ? 5 : 20000)}">${pct ? pctS(p) : money(c.pnl)}</td>`; }).join("")}
        <td class="n mono"><b>${money(tot)}</b></td></tr>`; }).join("")}</tbody></table></div><p class="note">P&amp;L is the change in each account's net liquidation value (base currency, AUD), so it includes the AUD/USD move on USD holdings. A day that was not captured folds into the next captured day; deposits and withdrawals are not reported by the TWS API, so add them under <span class="mono">risk.cash_flows</span> in config.json. History starts ${dlabel(W.first)}.</p>`;
  barChart($("plMonthChart"), {label: "monthly P&L, all accounts ($k)", h: 130, unit: "k", items: mkeys.slice().reverse().map((m) => { const tot = A.reduce((s, a) => s + ((months[m][a.id] || {}).pnl || 0), 0);
    return {label: new Date(m + "-15T12:00:00Z").toLocaleDateString([], {month: "short", timeZone: "UTC"}), v: tot / 1000, title: `${m}: <b>${money(tot)}</b>` + A.map((a) => `<div>${esc(a.label)} ${money((months[m][a.id] || {}).pnl)}</div>`).join("")}; })});
  const pal = ["var(--s2)", "var(--s3)", "var(--s1)", "var(--s4)"];
  lineChart($("plNav"), {label: "NAV per account", h: 220, series: A.map((a, k) => ({name: a.label, short: a.label, data: W.nav[a.id] || [], color: pal[k % 4], width: 1.8, dots: (W.nav[a.id] || []).length < 50})),
    fy: (v) => Math.abs(v) >= 1000 ? (v / 1000).toFixed(0) + "k" : v.toFixed(0), ft: (v) => money(v)});
  $("plNavLegend").innerHTML = legend(A.map((a, k) => [a.label, pal[k % 4]]));
}

function tickers() {
  const bt = (T && T.by_ticker) || {}, labels = (T && T.labels) || {};
  const accts = Object.keys(bt).sort(), since = T && T.marks_since;
  $("plTickerNote").textContent = since ? `Session ${dlabel(T.session)} vs the ${dlabel(since)} close` : "Marks start with this capture: the first day-on-day figures appear after the next session";
  $("plTicker").innerHTML = accts.length ? accts.map((a) => {
    const mag = (v) => Math.abs(ok(v.daily) ? v.daily : 0);
    const rows = Object.entries(bt[a]).sort((x, y) => mag(y[1]) - mag(x[1]));
    const tot = since ? rows.reduce((s, [, v]) => s + (v.daily || 0), 0) : null;
    const navc = (T.nav_change || {})[a], miss = rows.reduce((s, [, v]) => s + (v.missing || 0), 0);
    const off = since && ok(navc) && Math.abs(navc - tot) > Math.max(500, 0.3 * Math.abs(navc));
    return `<div class="card"><div class="hd"><span class="sym">${esc(labels[a] || a)}</span><span class="mono ${cls(tot)}">${money(tot)}</span></div>
      <div class="tbl"><table><thead><tr><th>Ticker</th><th class="n">Day P&amp;L</th><th class="n" title="IBKR's own per-contract daily P&amp;L, for reference">IBKR's</th><th class="n">Contracts</th></tr></thead><tbody>${
      rows.map(([k, v]) => `<tr><td>${esc(k)} ${hBarSvg(v.daily, Math.max(...rows.map(([, x]) => Math.abs(x.daily || 0)), 1), {w: 70, label: "day P&L vs the biggest mover"})}</td><td class="n ${cls(v.daily)}">${money(v.daily)}${v.missing ? ` <span class="wrn" title="${v.missing} contract(s) left out: no TWS value now or at the last close, so no fair comparison">*</span>` : ""}</td><td class="n small muted">${money(v.ibkr)}</td><td class="n small muted">${v.open} open${v.closed ? ` · ${v.closed} closed` : ""}</td></tr>`).join("")}
      ${since && ok((T.nav_change || {})[a]) ? `<tr><td class="muted">Other</td><td class="n muted" title="change in NAV minus the tickers above: cash interest, fees, AUD/USD, and contracts left out (*)">${money(T.nav_change[a] - tot)}</td><td></td><td class="n small muted">NAV change ${money(T.nav_change[a])}</td></tr>` : ""}</tbody></table></div>${off ? `<div class="state err small" style="margin-top:6px">Doesn't add up to the NAV change (${money(navc)})${miss ? `: ${miss} contract${miss > 1 ? "s" : ""} had no value at the last close or now` : ""}. Trust the NAV figure; the split by ticker is reliable once two complete closing captures exist.</div>` : ""}</div>`; }).join("")
    : `<div class="state">No data yet: press Refresh from TWS.</div>`;
}

function recon() {
  if (!R) return;
  $("rcMeta").textContent = R.marks_ts ? `positions from TWS ${new Date(R.marks_ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})} · ONE ${String(R.one_file || "").split(/[\\/]/).pop()}` : "no TWS data yet";
  const blocks = R.recon.map((r) => {
    const status = r.diffs.length ? `<span class="chip neg">${r.diffs.length} quantity difference${r.diffs.length > 1 ? "s" : ""}</span>` : `<span class="chip pos">Quantities match</span>`;
    const drift = r.drift.length ? `<span class="chip wrn">${r.drift.length} fill-price error${r.drift.length > 1 ? "s" : ""}</span>` : `<span class="chip pos">Prices match</span>`;
    const dtab = r.diffs.length ? `<div class="tbl"><table><thead><tr><th>Contract</th><th class="n">ONE qty</th><th class="n">IBKR qty</th><th>ONE trade</th><th>What to do</th></tr></thead><tbody>${
      r.diffs.map((d) => `<tr><td class="mono">${esc(d.symbol)}</td><td class="n">${d.one}</td><td class="n">${d.ibkr}</td><td class="small">${esc((d.trades || []).join(", ") || "–")}</td><td class="small">${d.one === 0 ? "In IBKR, not in ONE: import or enter the fill" : d.ibkr === 0 ? "In ONE, not in IBKR: closed/expired at the broker?" : "Quantity differs: check the last adjustment"}</td></tr>`).join("")}</tbody></table></div>` : "";
    const ptab = r.drift.length ? `<div class="tbl"><table><thead><tr><th>Contract</th><th class="n">Qty</th><th class="n">ONE price</th><th class="n">IBKR avg price</th><th class="n">P&amp;L effect</th><th>ONE trade</th></tr></thead><tbody>${
      r.drift.map((d) => `<tr><td class="mono">${esc(d.symbol)}</td><td class="n">${d.qty}</td><td class="n">${fmt(d.one_price)}</td><td class="n">${fmt(d.ibkr_price)}</td><td class="n ${cls(-d.dollars)}" title="positive = ONE shows more profit than the broker actually made">${d.dollars > 0 ? "+" : ""}${money(d.dollars)}</td><td class="small">${esc((d.trades || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">Positions opened entirely today, checked against today's actual fills: ONE recorded a different price than you were filled at. P&amp;L effect = ONE's P&amp;L minus the broker's for that leg (red = ONE overstates the profit).</p>` : "";
    const btab = (r.basis || []).length ? `<details><summary class="small muted">${r.basis.length} cost-basis difference${r.basis.length > 1 ? "s" : ""}: IBKR FIFO vs ONE moving average, nothing to fix</summary><div class="tbl"><table><thead><tr><th>Contract</th><th class="n">Qty</th><th class="n">ONE avg price</th><th class="n">IBKR FIFO price</th><th>ONE trade</th></tr></thead><tbody>${
      r.basis.map((d) => `<tr><td class="mono">${esc(d.symbol)}</td><td class="n">${d.qty}</td><td class="n">${fmt(d.one_price)}</td><td class="n">${fmt(d.ibkr_price)}</td><td class="small">${esc((d.trades || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">On a leg scaled into and partly closed without going flat, IBKR relieves lots first in, first out while ONE carries a moving average, so the open price must differ. The trade's lifetime P&amp;L is the same under both; only the split between realised and open P&amp;L moves. Same rule as TWS Matcher.</p></details>` : "";
    const stk = R.stocks.filter((x) => x.account === r.account);
    const st = stk.length ? `<details><summary class="small muted">${stk.length} stock/ETF holding${stk.length > 1 ? "s" : ""} at IBKR, expected (ONE tracks the option strategies)</summary><div class="row">${stk.map((x) => `<span class="tag">${esc(x.symbol)} ${x.qty} @ ${fmt(x.avg_price)}</span>`).join("")}</div></details>` : "";
    const clean = !r.diffs.length && !r.drift.length;
    return `<div class="acard ${clean ? "ok" : "diff"}"><div class="row" style="justify-content:space-between"><h3>${esc(r.label)} <span class="muted">${esc(r.account)} · ${r.matched} contracts match</span></h3><span class="chip ${clean ? "pos" : "neg"}">${clean ? "Match" : "Diff"}</span></div>
      <div class="row">${status}${drift}</div>${dtab}${ptab}${btab}${st}</div>`;
  });
  $("rcBody").innerHTML = oneStale(R) + (blocks.length ? `<div class="acctgrid">${blocks.join("")}</div>` : `<div class="state">No reconciliation yet: press Refresh from TWS.</div>`);
  // fills + ONE import
  const accts = [...new Set(R.fills.map((f) => f.account))];
  const today = new Date().toLocaleDateString("en-CA", {timeZone: "Australia/Sydney"});
  $("oneImport").innerHTML = `<span class="lbl">ONE import file</span><input type="date" id="oiDate" value="${today}">${
    Object.entries(R.labels).map(([id, lab]) => `<a class="btnlink" href="/api/one-import/${encodeURIComponent(id)}.csv?date=${today}" data-acct="${esc(id)}">${esc(lab)} CSV</a>`).join("")}
    <span class="small muted">IBKR Flex format that ONE imports (fills on that Sydney date). ONE's "link trades into positions" step is still manual.</span>`;
  $("oiDate").addEventListener("change", () => document.querySelectorAll("#oneImport a[data-acct]").forEach((a) => { a.href = `/api/one-import/${encodeURIComponent(a.dataset.acct)}.csv?date=${$("oiDate").value}`; }));
  const df = new Intl.DateTimeFormat(undefined, {weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"});
  $("rcFills").innerHTML = R.fills.length ? `<div class="tbl"><table><thead><tr><th>Time (yours)</th><th>Account</th><th>Contract</th><th>Side</th><th class="n">Qty</th><th class="n">Price</th><th class="n">Comm.</th><th>ONE</th><th>ONE trade</th></tr></thead><tbody>${
    R.fills.map((f) => `<tr><td class="mono small">${f.time_utc ? df.format(new Date(f.time_utc)) : "–"}</td><td>${esc(f.label)}</td><td class="mono small">${esc(f.local_symbol || f.symbol)}</td><td class="${f.side === "BOT" ? "pos" : "neg"}">${f.side === "BOT" ? "Buy" : "Sell"}</td>
      <td class="n">${f.qty}</td><td class="n">${fmt(f.price)}</td><td class="n">${fmt(f.commission)}</td>
      <td><span class="chip ${f.status === "in ONE" ? "pos" : f.status === "not in ONE" ? "neg" : "muted"}">${esc(f.status)}</span></td><td class="small">${esc(f.one_trades.join(", ") || "–")}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="state">No fills recorded in the last 7 days yet. Fills are captured whenever the app refreshes from TWS (TWS itself only returns today's).</div>`;
}

async function load() {
  try {
    [W, T, R] = await Promise.all(["/api/pnl/weekly", "/api/pnl/today", "/api/recon"].map((u) => fetch(u).then((r) => r.json())));
    $("plMeta").textContent = T && T.ts ? `TWS data ${new Date(T.ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})}` : "no TWS data yet";
    strip(); weekly(); tickers(); recon();
  } catch (e) { $("plWeekly").innerHTML = `<div class="state err">${esc(e.message || e)}</div>`; }
}
$("plUnit").addEventListener("change", weekly);
$("plRefresh").addEventListener("click", async () => {
  const b = $("plRefresh"); b.disabled = true; b.textContent = "Refreshing…";
  await fetch("/api/risk/refresh", {method: "POST"});
  for (let i = 0; i < 120; i++) { await new Promise((r) => setTimeout(r, 2000)); const s = await (await fetch("/api/risk/status")).json(); if (!s.running) break; }
  b.disabled = false; b.textContent = "Refresh from TWS"; load();
});
window.loadPnl = load;
})();
