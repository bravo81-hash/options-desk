/* Expected moves and the A14 (put BWB) scanner. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const MONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const xd = (e) => `${+e.slice(6, 8)} ${MONS[+e.slice(4, 6) - 1]}${e.slice(0, 4) !== String(new Date().getFullYear()) ? " " + e.slice(2, 4) : ""}`;
const big = (v) => Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v >= 100 ? v.toFixed(0) : v.toFixed(2);
const err = (e) => `<div class="state err">${esc(e.message || e)}</div>`;
const when = (ts) => ts ? new Date(ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"}) : "never";

/* ================================================================ expected moves */
let EM = null;
function legSummary(legs) {
  const by = {};
  legs.forEach((l) => { if (!ok(l.strike)) return; const k = `${l.strike}${l.right}`; by[k] = by[k] || {k: l.strike, r: l.right, q: 0}; by[k].q += l.qty; });
  return Object.values(by).filter((x) => Math.abs(x.q) > 1e-9).sort((a, b) => b.k - a.k);
}
function emCard(sym, v) {
  if (v.error && !v.expiries) return `<section class="panel c12" data-sub="${esc(sym)}"><header><h2>${esc(sym)}</h2></header><div class="state">${esc(v.error)}</div></section>`;
  const S = v.spot, rows = v.expiries || [];
  const tr = rows.map((e) => {
    const legs = legSummary(e.legs || []);
    const chips = legs.map((l) => { const z = ok(e.sd) ? (l.k - S) / e.sd : null;
      return `<span class="tag ${l.q < 0 ? "neg" : "pos"}" title="${l.q > 0 ? "+" : ""}${l.q} ${l.k}${l.r} · ${pctS(100 * (l.k / S - 1))} from spot">${l.q > 0 ? "+" : ""}${l.q} ${big(l.k)}${l.r} <b>${sgn(z, 1)}σ</b></span>`; }).join(" ");
    return `<tr class="${e.held ? "held" : ""}"><td>${xd(e.expiry)}${e.held ? ` <span class="chip">held</span>` : ""}</td><td class="n">${e.dte}</td><td class="n">${ok(e.iv) ? (100 * e.iv).toFixed(1) + "%" : "–"}</td>
      <td class="n">${ok(e.straddle) ? big(e.straddle) : "–"}</td><td class="n"><b>±${ok(e.sd) ? big(e.sd) : "–"}</b> <span class="muted">${ok(e.sd) ? "(" + (100 * e.sd / S).toFixed(1) + "%)" : ""}</span></td>
      <td class="n mono small">${ok(e.sd) ? `${big(S - e.sd)} – ${big(S + e.sd)}` : "–"}</td><td class="n mono small muted">${ok(e.sd) ? `${big(S - 2 * e.sd)} – ${big(S + 2 * e.sd)}` : "–"}</td>
      <td class="small">${chips || ""}</td></tr>`; }).join("");
  return `<section class="panel c12" data-sub="${esc(sym)}"><header><h2>${esc(sym)} <span class="mono">${big(S)}</span> ${v.currency && v.currency !== "USD" ? `<span class="muted small">${v.currency}</span>` : ""}</h2>
    <span class="small muted">1 day ±${ok(v.day_sd) ? big(v.day_sd) + " (" + (100 * v.day_sd / S).toFixed(2) + "%)" : "–"} · straddle ≈ 0.8σ</span></header>
    <div class="two stack"><div class="chart" id="cone-${esc(sym)}"></div>
    <div class="tbl"><table><thead><tr><th>Expiry</th><th class="n">DTE</th><th class="n">ATM IV</th><th class="n">Straddle</th><th class="n">1σ move</th><th class="n">1σ range</th><th class="n">2σ range</th><th>Your strikes (σ from spot)</th></tr></thead><tbody>${tr}</tbody></table></div></div></section>`;
}
function cone(el, S, rows) {
  const pts = rows.filter((e) => ok(e.sd) && e.dte > 0);
  if (!pts.length) { el.innerHTML = `<div class="state">No implied vols.</div>`; return; }
  mount(el, (W) => {
    const H = 260, mL = 54, mR = 12, mT = 10, mB = 24, pw = W - mL - mR, ph = H - mT - mB;
    const xMax = Math.max(...pts.map((e) => e.dte)) * 1.03;
    // sigma at any DTE from total variance interpolation (flat at the ends)
    const vAt = (d) => { const a = pts.filter((e) => e.dte <= d).pop() || pts[0], b = pts.find((e) => e.dte >= d) || pts[pts.length - 1];
      const va = (a.sd / S) ** 2, vb = (b.sd / S) ** 2; if (a === b) return Math.sqrt(va * d / a.dte); return Math.sqrt(va + (vb - va) * (d - a.dte) / (b.dte - a.dte)); };
    const strikes = pts.flatMap((e) => legSummary(e.legs || []).map((l) => ({d: e.dte, k: l.k, q: l.q, r: l.r, e: e.expiry})));
    const top = S * (1 + 2.3 * vAt(xMax)), bot = S * (1 - 2.6 * vAt(xMax));
    const lo = Math.min(bot, ...strikes.map((s) => s.k)), hi = Math.max(top, ...strikes.map((s) => s.k));
    const X = (d) => mL + d / xMax * pw, Y = (v) => mT + ph - (v - lo) * ph / (hi - lo);
    const ds = []; for (let i = 0; i <= 60; i++) ds.push(xMax * i / 60);
    const band = (m) => { const up = ds.map((d) => `${X(d).toFixed(1)},${Y(S * (1 + m * vAt(d))).toFixed(1)}`), dn = ds.map((d) => `${X(d).toFixed(1)},${Y(S * (1 - m * vAt(d))).toFixed(1)}`).reverse(); return up.concat(dn).join(" "); };
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="expected-move cone">`;
    niceTicks(lo, hi, 5).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--grid)"/><text x="${mL - 6}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${big(v)}</text>`; });
    niceTicks(0, xMax, Math.max(2, Math.floor(pw / 70))).forEach((v) => { if (v >= 0 && v <= xMax) s += `<text x="${X(v).toFixed(1)}" y="${H - 6}" text-anchor="middle">${v}d</text>`; });
    s += `<polygon points="${band(2)}" fill="var(--s1)" opacity=".08"/><polygon points="${band(1)}" fill="var(--s1)" opacity=".16"/>`;
    s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(S).toFixed(1)}" y2="${Y(S).toFixed(1)}" stroke="var(--accent)" stroke-dasharray="3 3"/>`;
    pts.forEach((e) => { s += `<line x1="${X(e.dte).toFixed(1)}" x2="${X(e.dte).toFixed(1)}" y1="${Y(S - e.sd).toFixed(1)}" y2="${Y(S + e.sd).toFixed(1)}" stroke="var(--s1)" stroke-width="1" opacity=".5"/>`; });
    strikes.forEach((x, i) => { s += `<circle class="sk" data-i="${i}" cx="${X(x.d).toFixed(1)}" cy="${Y(x.k).toFixed(1)}" r="${Math.min(7, 3 + Math.abs(x.q) / 4)}" fill="${x.q < 0 ? "var(--down)" : "var(--up)"}" fill-opacity=".8" stroke="var(--panel)" stroke-width="1.5"/>`; });
    el.innerHTML = s + `</svg>${legend([["±1σ", "var(--s1)", 1], ["±2σ", "color-mix(in srgb, var(--s1) 40%, var(--panel))", 1], ["short strikes", "var(--down)", 1], ["long strikes", "var(--up)", 1], ["spot", "var(--accent)"]])}`;
    bindTip(el, ".sk", (n) => { const x = strikes[+n.dataset.i], sd = S * vAt(x.d); return `<div>${xd(x.e)} · ${x.d} DTE</div><div>${x.q > 0 ? "+" : ""}${x.q} × ${big(x.k)}${x.r}</div><div>${pctS(100 * (x.k / S - 1))} · <b>${sgn((x.k - S) / sd, 2)}σ</b></div>`; });
  });
}
async function loadEm() {
  try {
    EM = await api("/api/em");
    const syms = Object.keys(EM.symbols || {});
    $("emMeta").textContent = EM.ts ? `from TWS ${when(EM.ts)}${EM.running ? " · refreshing…" : ""}` : (EM.running ? "fetching from TWS…" : "no data yet");
    if (!syms.length) { $("emBody").innerHTML = `<div class="state">Press Refresh from TWS (TWS must be running). It also refreshes each weekday after the 15:40 ET recording.</div>`; return; }
    const order = ["SPX", "RUT"].filter((s) => syms.includes(s)).concat(syms.filter((s) => !["SPX", "RUT"].includes(s)).sort());
    $("emBody").innerHTML = order.map((s) => emCard(s, EM.symbols[s])).join("");
    initSubtabs($("emBody"));
    order.forEach((s) => { const v = EM.symbols[s]; if (v.expiries) cone($("cone-" + s), v.spot, v.expiries); });
  } catch (e) { $("emBody").innerHTML = err(e); }
}
async function poll(statusUrl, done, metaEl) {
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const s = await api(statusUrl).catch(() => null);
    if (s && metaEl) metaEl.textContent = (s.log || []).slice(-1)[0] || "working…";
    if (s && !s.running) break;
  }
  done();
}
$("emRefresh").addEventListener("click", async () => {
  $("emRefresh").disabled = true; $("emMeta").textContent = "fetching from TWS…";
  await api("/api/em/refresh", {method: "POST"});
  await poll("/api/em", loadEm, $("emMeta"));
  $("emRefresh").disabled = false;
});

/* ================================================================ A14 scanner */
let A = null, HIST = null, ST = null, sortKey = "hist_day", pick = null, cellFilter = null;
let BT = null, IVB = null;  // 2009–2026 backtest odds by DTE and VIX/VIX3M band (Evidence → Since 2009), today's band
async function btLoad() {
  const [b, r] = await Promise.all([api("/api/backtest").catch(() => null), api("/api/readiness").catch(() => null)]);
  BT = b && b.odds ? b : null; IVB = r && r.ivts_band ? r.ivts_band : null;
}
function btOdds(sym, dte) {
  if (!BT || !IVB || !BT.odds[sym]) return null;
  const d = Object.keys(BT.odds[sym]).map(Number).reduce((a, x) => (Math.abs(x - dte) < Math.abs(a - dte) ? x : a));
  const o = BT.odds[sym][String(d)][IVB.band];
  return o ? {d, ...o} : null;
}
const trendOf = (sym) => ST && ST.now && ST.now[sym];
const upTrend = (tr) => tr && tr.vs_sma20 > 0;
function trendBanner() {
  if (!ST || !ST.now) { $("a14Trend").innerHTML = ""; return; }
  const bt = ST.by_trend || {}, a = bt.above || {}, b = bt.below || {};
  const card = (sym) => { const tr = ST.now[sym]; if (!tr) return "";
    const up = upTrend(tr);
    return `<div><span class="lbl">${sym} short-term trend (20-day)</span><b class="${up ? "pos" : "wrn"}">${up ? "Above" : "Below"} 20-day avg</b>
      <span class="small muted">${pctS(tr.vs_sma20, 1)} vs 20-day average · ${pctS(tr.ret5, 1)} over 5 sessions (${esc(tr.date)})</span>
      <span class="small">${up ? `like your better entries: A14s entered above it averaged <b>${fmt(a.ret, 1)}%</b> (${a.n})` : `your A14s entered below it averaged <b>${fmt(b.ret, 1)}%</b> (${b.n}) vs ${fmt(a.ret, 1)}% above it: consider waiting for an up day, or keep the short close to spot`}</span></div>`; };
  const bd = ST.by_dte || {};
  const dteCard = `<div><span class="lbl">Your closed A14s · return per day held</span><span class="small">${["≤21", "22–45", "46–70", "71+"].filter((k) => bd[k]).map((k) => `${k} DTE <b>${fmt(bd[k].per_day, 2)}%</b>/day (${fmt(bd[k].ret, 1)}% over ${Math.round(bd[k].dit)}d, n ${bd[k].n})`).join("<br>")}</span></div>`;
  const sp = ST.speed, bm = (sp && sp.by_month) || [];
  const paceCard = sp ? `<div><span class="lbl">Your A14 pace by entry month · target ${fmt(sp.target, 2)}%/day</span><span class="small">${bm.map((m) => `${new Date(m.month + "-15").toLocaleDateString([], {month: "short"})} <b class="${m.per_day >= sp.target ? "pos" : m.per_day < sp.slow ? "neg" : ""}">${fmt(m.per_day, 2)}%</b>/day · entry ${Math.round(m.dte)} DTE · held ${Math.round(m.dit)}d (n ${m.n})`).join("<br>")}</span></div>` : "";
  const btCard = BT && IVB && IVB.band !== "unknown" ? `<div><span class="lbl">Since 2009 · A14s entered in today's term structure (${esc(IVB.label)})</span><span class="small">${["SPX", "RUT"].map((u) => `${u} ` + [14, 21, 30, 45, 60].map((d) => { const o = BT.odds[u] && BT.odds[u][String(d)] && BT.odds[u][String(d)][IVB.band]; return o ? `${d}d <b class="${o.avg > 0 ? "pos" : "neg"}">${pctS(o.avg)}</b>` : ""; }).join(" · ")).join("<br>")}<br><span class="muted">avg per trade, % of margin, your exits with the −20% stop (model, after costs) · Evidence → Since 2009</span></span></div>` : "";
  $("a14Trend").innerHTML = `<div class="kv">${card("SPX")}${card("RUT")}${btCard}${dteCard}${paceCard}</div>`;
}
const SORTS = {hist_day: "Since 2009: return per day held, your exits", hist_avg: "Since 2009: average return per trade", exp_day: "Model E/risk per day held (today's odds)", exp_risk: "E[P&L] at exit / risk", stress_risk: "Stress loss / risk (smallest first)", theta_risk: "Theta / risk", pop_h: "P(profit) at exit", ror: "Max profit / risk"};
function params() {
  const q = new URLSearchParams({sym: $("a14Sym").value, dte_min: $("a14Dmin").value, dte_max: $("a14Dmax").value, exit: $("a14Exit").value,
    vol: $("a14Vol").value, min_credit: $("a14Cr").value, up_lo: $("a14UpLo").value, up_hi: $("a14UpHi").value});
  if ($("a14Vol").value === "custom") q.set("vol_custom", $("a14VolC").value);
  return q;
}
async function scan() {
  $("a14Table").innerHTML = `<div class="state">Scanning…</div>`;
  try {
    A = await api("/api/a14/scan?" + params());
    if (A.error) { $("a14Meta").textContent = ""; $("a14Heat").innerHTML = ""; $("a14Table").innerHTML = err(A.error); return; }
    const m = Object.entries(A.symbols).map(([s, v]) => `${s} ${big(v.spot)} · RV20 ${ok(v.rv20) ? (100 * v.rv20).toFixed(1) + "%" : "–"}`).join(" · ");
    const hold = (A.params && A.params.hold) || {}, ex = A.params && A.params.exit_days;
    $("a14Meta").textContent = `chain from TWS ${when(A.ts)} · ${m} · ${A.count} candidates · ${A.hist && !A.hist.error ? `history: since 2009, today's band ${A.hist.label.toLowerCase()}, your exits (${A.hist.rule})` : "history scores unavailable"} · model odds: exit ${ex === "auto" ? "at your typical hold: " + Object.entries(hold).map(([k, v]) => `${k} DTE ${Math.round(v)}d`).join(", ") + " (14d where no history)" : "after " + ex + " days"}`;
    if (!ST) { [ST] = await Promise.all([api("/api/a14/stats").catch(() => null), btLoad()]); trendBanner(); }
    cellFilter = null; heat(); table(); if (!HIST) history();
  } catch (e) { $("a14Table").innerHTML = err(e); }
}
function heat() {
  const rows = A.heat.map((h) => ({key: h.sym + "|" + h.expiry, label: `${h.sym} ${xd(h.expiry)}`}));
  const buckets = [...new Set(A.heat.flatMap((h) => Object.keys(h.cells).map(Number)))].sort((a, b) => b - a);
  const cols = buckets.map((b) => ({key: String(b), label: `${b}%`}));
  const cells = new Map();
  A.heat.forEach((h) => Object.entries(h.cells).forEach(([b, v]) => cells.set(`${h.sym}|${h.expiry}|${Number(b)}`, {v: v.exp_risk, title: `${h.sym} ${xd(h.expiry)} · short ${b}% from spot<br>best ${esc(v.label)}: E/risk <b>${fmt(v.exp_risk, 1)}%</b>`,
    sel: cellFilter && cellFilter.row === h.sym + "|" + h.expiry && cellFilter.b === Number(b)})));
  heatmap($("a14Heat"), {label: "best expected return by expiry and short strike", rows, cols, cells, center: 0,
    onClick: (r, c) => { cellFilter = cellFilter && cellFilter.row === r && cellFilter.b === Number(c) ? null : {row: r, b: Number(c)}; heat(); table(); }});
  $("a14HeatNote").textContent = "rows = expiry · columns = short strike % from spot · colour = best E[P&L at exit]/risk · click to filter the table";
}
const histTxt = (c) => { const b = c.hist_basis === "band" ? `entered in today's term structure (${esc(A.hist.label.toLowerCase())})` : "on every Friday";
  return `this shape, rebuilt at ${c.dte} DTE ${b} since 2009 and managed with your exits, returned <b>${fmt(c.hist_day, 3)}%</b> of margin per day held: ${pctS(c.hist_avg)} a trade over ${fmt(c.hist_days, 0)} days, target hit ${Math.round(100 * c.hist_ptgt)}%, stop ${Math.round(100 * c.hist_pstop)}%`; };
const WHY = {
  hist_day: histTxt, hist_avg: histTxt,
  exp_risk: (c) => `expected P&L on your exit date (${c.h}d) is <b>${fmt(c.exp_risk, 1)}%</b> of the risk`,
  exp_day: (c) => `expected return is <b>${fmt(c.exp_day, 2)}%</b> of risk per day held over ${c.h} days (your typical hold for ${c.dte} DTE unless you set the exit)`,
  stress_risk: (c) => `in the stress (index −5%, IV +5 pts by day ${c.h}) the P&L is <b>${money(c.stress_h)}</b>, ${Math.round(c.stress_risk)}% of the risk`,
  theta_risk: (c) => `time decay earns <b>${fmt(c.theta_risk, 2)}%</b> of the risk per day (${money(c.theta)}/day per lot)`,
  pop_h: (c) => `<b>${Math.round(100 * c.pop_h)}%</b> chance of being in profit on your exit date`,
  ror: (c) => `max profit is <b>${fmt(c.ror, 2)}x</b> the risk if the index pins the short strike at expiry`,
};
const pace = (v) => { const sp = ST && ST.speed; if (!sp || !ok(v)) return null; return v >= sp.target ? "fast" : v < sp.slow ? "slow" : "ok"; };
function rankWhy(c, rank, total) {
  const pros = [], cons = [], tr = trendOf(c.sym), sp = ST && ST.speed, pc = pace(c.exp_day);
  if (pc === "fast") pros.push(`fast capital: ${fmt(c.exp_day, 2)}%/day expected, at or above your ${fmt(sp.target, 2)}%/day target`);
  if (pc === "slow") cons.push(`slow capital: ${fmt(c.exp_day, 2)}%/day expected, under half your ${fmt(sp.target, 2)}%/day target; margin tied up ${c.h} days`);
  if (c.credit >= 0) pros.push(`credit ${sgn(c.credit, 2)}: nothing lost if the market rallies`); else cons.push(`debit ${fmt(-c.credit, 2)}: a rally loses that`);
  if (c.pop_h >= 0.75) pros.push(`high odds: ${Math.round(100 * c.pop_h)}% P(profit) at exit`); else if (c.pop_h < 0.5) cons.push(`below-even odds: ${Math.round(100 * c.pop_h)}% P(profit) at exit`);
  if (c.theta > 0) pros.push(`earns ${money(c.theta)} a day from time decay`); else cons.push(`negative theta today (${money(c.theta)}/day): needs the market to come to it`);
  if (c.usual) pros.push("shaped like your past A14 entries");
  const bo = ok(c.hist_avg) ? null : btOdds(c.sym, c.dte);
  if (ok(c.hist_avg) && !sortKey.startsWith("hist")) (c.hist_avg > 0 ? pros : cons).push(histTxt(c));
  if (ok(c.hist_big) && c.hist_big >= 0.03) cons.push(`since 2009, ${Math.round(100 * c.hist_big)}% of these lost over half the margin (worst case for this shape: gaps through the −20% stop)`);
  if (bo) (bo.avg > 0 ? pros : cons).push(`since 2009, ${c.sym} A14s entered at about ${bo.d} DTE in today's term structure (${IVB.label.toLowerCase()}) averaged ${pctS(bo.avg)} of margin with your exits, ${Math.round(100 * bo.win)}% winners (${bo.n} trades, model)`);
  if (tr && ST.by_trend) (upTrend(tr) ? pros : cons).push(upTrend(tr) ? `${c.sym} above its 20-day average (your better entry condition)` : `${c.sym} below its 20-day average (your A14s averaged ${fmt(ST.by_trend.below.ret, 1)}% vs ${fmt(ST.by_trend.above.ret, 1)}% above it)`);
  if (ok(c.stress_risk) && c.stress_risk < -50) cons.push(`fragile: the stress (−5%, IV +5) costs ${money(c.stress_h)}, ${Math.round(-c.stress_risk)}% of risk`);
  if (ok(c.down1sd_h) && c.down1sd_h < -0.5 * c.risk) cons.push(`a 1σ drop by exit costs ${money(c.down1sd_h)} (${Math.round(100 * -c.down1sd_h / c.risk)}% of risk)`);
  if (c.short_sd > -0.15) cons.push("short strike at the money: the profit zone is narrow and close");
  if (c.dte <= 14) cons.push(`${c.dte} days to expiry: fast gamma, little room to adjust`);
  const li = (a) => a.map((x) => `<li>${x}</li>`).join("");
  return `<div><b>#${rank} of ${total}</b> by ${esc(SORTS[sortKey])}</div><div style="max-width:340px">${WHY[sortKey] ? WHY[sortKey](c) : ""}.</div>
    ${pros.length ? `<div style="margin-top:4px"><b class="pos">For</b><ul style="margin:2px 0;padding-left:16px">${li(pros)}</ul></div>` : ""}
    ${cons.length ? `<div><b class="wrn">Watch</b><ul style="margin:2px 0;padding-left:16px">${li(cons)}</ul></div>` : ""}`;
}
function table() {
  let list = A.candidates.slice();
  if ($("a14Usual").checked) list = list.filter((c) => c.usual);
  if (cellFilter) list = list.filter((c) => c.sym + "|" + c.expiry === cellFilter.row && Math.round(c.short_pct * 2) / 2 === cellFilter.b);
  list.sort((a, b) => (b[sortKey] ?? -1e9) - (a[sortKey] ?? -1e9));
  const total = list.length;
  list = list.slice(0, 40);
  const th = (k, t, tip) => `<th class="n ${k === sortKey ? "sorted" : ""}" data-k="${k}" title="${esc(tip || "")}" style="cursor:pointer">${t}</th>`;
  $("a14Table").innerHTML = list.length ? `<div class="tbl"><table><thead><tr><th class="n" title="rank by the chosen metric · hover a badge for why">#</th><th>Expiry</th><th>Strikes (upper / short / lower)</th><th class="n">Wings</th><th class="n" title="per lot, points; + = credit">Credit</th>
    <th class="n">Max profit</th><th class="n">Risk</th>${th("ror", "Profit/risk")}<th class="n">θ/day</th><th class="n">Δ</th><th class="n">Vega</th>
    ${th("theta_risk", "θ/risk", "theta per day as % of risk")}${th("exp_risk", "E/risk", "expected P&L at the exit date as % of risk")}${th("exp_day", "E/risk per day", "expected return at the exit date, as % of risk, divided by the days held (your typical hold for that entry DTE): compares short and long expiries on capital use")}${th("hist_day", "Since 2009 %/day", "this shape rebuilt on past Fridays at the same DTE (today's VIX/VIX3M band when it has 80+ entries) and managed with your trade-plan exits: return per day held, % of margin")}${th("hist_avg", "Since 2009 avg", "average return per trade, % of margin, after costs")}<th class="n" title="share of past entries that hit the target / the −20% stop">Target / stop</th>${th("stress_risk", "Stress", "P&L by the exit date if the index falls 5% and every strike's IV rises 5 points, $ per lot")}${th("pop_h", "P(profit)", "probability of a profit at the exit date")}<th class="n" title="spot range (from today) where the position is in profit at the exit date">Profit zone at exit</th><th class="n" title="short strike distance in implied standard deviations to expiry">Short σ</th></tr></thead><tbody>${
    list.map((c, i) => `<tr data-i="${i}" class="${pick && pick.sym === c.sym && pick.expiry === c.expiry && pick.upper === c.upper && pick.short === c.short && pick.lower === c.lower ? "sel" : ""}" style="cursor:pointer">
      <td class="n"><span class="rank" data-i="${i}">${i + 1}</span></td><td>${c.sym} ${xd(c.expiry)} <span class="muted">${c.dte}d ${esc(c.cls || "")}</span>${c.usual ? ` <span class="chip">your usual</span>` : ""}${pace(c.exp_day) === "fast" ? ` <span class="chip pos" title="expected ${fmt(c.exp_day, 2)}%/day ≥ your ${fmt(ST.speed.target, 2)}%/day target">fast</span>` : pace(c.exp_day) === "slow" ? ` <span class="chip neg" title="expected ${fmt(c.exp_day, 2)}%/day, under half your target">slow</span>` : ""}${trendOf(c.sym) ? ` <span class="chip ${upTrend(trendOf(c.sym)) ? "pos" : "wrn"}" title="${c.sym} ${pctS(trendOf(c.sym).vs_sma20, 1)} vs its 20-day average">${upTrend(trendOf(c.sym)) ? "trend ↑" : "below 20d"}</span>` : ""}</td>
      <td class="mono">${big(c.upper)} / ${big(c.short)} / ${big(c.lower)} <span class="muted small">${pctS(c.upper_pct)} / ${pctS(c.short_pct)}</span></td>
      <td class="n mono">${c.U}/${c.L}</td><td class="n mono ${cls(c.credit)}">${sgn(c.credit, 2)}</td><td class="n">${money(c.max_profit)}</td><td class="n">${money(c.risk)}</td><td class="n">${fmt(c.ror, 2)}</td>
      <td class="n ${cls(c.theta)}">${money(c.theta)}</td><td class="n">${fmt(c.delta, 1)}</td><td class="n">${fmt(c.vega, 0)}</td>
      <td class="n">${fmt(c.theta_risk, 2)}%</td><td class="n ${cls(c.exp_risk)}"><b>${fmt(c.exp_risk, 1)}%</b></td><td class="n">${fmt(c.exp_day, 2)}%</td><td class="n ${cls(c.hist_day)}" title="${esc(c.hist_basis === "band" ? `${(c.hist_band || {}).n} past entries in today's band; all entries: ${pctS(c.hist_all && c.hist_all.avg)} a trade` : "all past entries (today's band has too few)")}">${hBarSvg(c.hist_day, Math.max(...A.candidates.map((x) => Math.abs(x.hist_day || 0)), 0.05), {w: 50, label: "since-2009 return per day vs the best setup"})} <b>${fmt(c.hist_day, 3)}%</b></td><td class="n ${cls(c.hist_avg)}" title="${esc(`5th percentile ${pctS(c.hist_p5)} · ${fmt(c.hist_days, 0)} days held on average`)}">${pctS(c.hist_avg)}</td><td class="n small">${ok(c.hist_ptgt) ? `${Math.round(100 * c.hist_ptgt)}% / ${Math.round(100 * c.hist_pstop)}%` : "–"}</td><td class="n ${c.stress_risk < -50 ? "neg" : ""}" title="${Math.round(c.stress_risk)}% of risk">${money(c.stress_h)}</td><td class="n">${ok(c.pop_h) ? Math.round(100 * c.pop_h) + "%" : "–"}</td>
      <td class="n small">${ok(c.tent_lo) ? pctS(c.tent_lo) : "–"} to ${ok(c.tent_hi) ? pctS(c.tent_hi) : "no upside loss"}</td><td class="n">${fmt(c.short_sd, 2)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="state">Nothing matches. Loosen the filters (credit, DTE, upper-long range) or untick "your usual shapes only".</div>`;
  bindTip($("a14Table"), ".rank", (n) => rankWhy(list[+n.dataset.i], +n.dataset.i + 1, total));
  $("a14Table").querySelectorAll("th[data-k]").forEach((h) => h.addEventListener("click", () => { sortKey = h.dataset.k; $("a14Sort").value = sortKey; table(); }));
  $("a14Table").querySelectorAll("tbody tr").forEach((r) => r.addEventListener("click", () => { pick = list[+r.dataset.i]; table(); detail(); }));
}
async function detail() {
  const c = pick; if (!c) return;
  $("a14DetailPanel").hidden = false;
  $("a14Detail").innerHTML = `<div class="state">Loading…</div>`;
  const q = new URLSearchParams({sym: c.sym, expiry: c.expiry, u: c.upper, s: c.short, l: c.lower, exit: $("a14Exit").value});
  const r = await api("/api/a14/curve?" + q).catch((e) => ({error: e.message}));
  if (r.error) { $("a14Detail").innerHTML = err(r.error); return; }
  const kpi = (l, v, sub = "", k = "") => `<div><span class="lbl">${l}</span><b class="${k}">${v}</b><span class="small muted">${sub}</span></div>`;
  $("a14Detail").innerHTML = `<h3 style="margin:0 0 8px">${c.sym} ${xd(c.expiry)} · +1 ${big(c.upper)}P / −2 ${big(c.short)}P / +1 ${big(c.lower)}P <span class="muted small">per lot</span></h3>
    <div class="kv" style="margin-bottom:10px">${kpi("Credit", sgn(c.credit, 2) + " pts", c.credit >= 0 ? "no upside risk" : "debit = upside risk")}${kpi("Max profit", money(c.max_profit), "at the short strike, at expiry")}
    ${kpi("Risk", money(c.risk), "below the lower wing")}${kpi("θ / day", money(c.theta), `${fmt(c.theta_risk, 2)}% of risk`, cls(c.theta))}${kpi("Δ · vega", `${fmt(c.delta, 1)} · ${fmt(c.vega, 0)}`, "$ per point · $ per vol point")}
    ${kpi(`At exit (${r.h}d)`, money(c.exp_h), `expected · P(profit) ${Math.round(100 * c.pop_h)}%`, cls(c.exp_h))}${kpi("−1σ at exit", money(c.down1sd_h), `spot −${(100 * r.em_h / r.spot).toFixed(1)}% by the exit date`, cls(c.down1sd_h))}${kpi("Stress at exit", money(c.stress_h), `−5% and IV +5 pts · ${Math.round(-c.stress_risk)}% of risk`, c.stress_risk < -50 ? "neg" : cls(c.stress_h))}</div>
    <div class="chart" id="a14Chart"></div>${legend([["today", "var(--s1)"], [`after ${r.h} days`, "var(--accent)"], [`after ${r.h} days, IV +5 pts`, "var(--down)"], ["at expiry", "var(--faint)"], ["±1σ to expiry", "var(--s1)", 1]])}`;
  const xs = r.S, S0 = r.spot;
  window.riskChart($("a14Chart"), {label: "BWB risk graph", h: 280, xs, spot: S0, nowPnl: 0, ticks: 5,
    fx: (v, long) => long ? `${c.sym} ${big(v)} (${pctS(100 * (v / S0 - 1))})` : big(v),
    series: [{name: "at expiry", ys: r.expiry, color: "var(--faint)", width: 1.4}, {name: `after ${r.h} days`, ys: r.exit, color: "var(--accent)", width: 2.2, fill: true}, {name: `after ${r.h} days, IV +5 pts`, ys: r.stress, color: "var(--down)", width: 1.6, dash: "5 3"}, {name: "today", ys: r.now, color: "var(--s1)", width: 1.6}],
    bands: [[S0 - r.em, S0 + r.em]]});
}
function history() {
  api("/api/a14/history").then((h) => {
    HIST = h;
    const T = (h.trades || []).filter((t) => ok(t.U));
    if (!T.length) { $("a14Hist").innerHTML = `<div class="state">No A14 trades with a single-BWB entry found in the ONE report.</div>`; return; }
    const grp = {};
    T.forEach((t) => { const b = t.dte <= 21 ? "≤21 DTE" : t.dte <= 45 ? "22–45 DTE" : t.dte <= 70 ? "46–70 DTE" : "71+ DTE"; const k = `${t.und} · ${b}`;
      const g = (grp[k] = grp[k] || {n: 0, closed: 0, win: 0, ret: 0, pnl: 0, short: 0, U: [], L: []}); g.n++; g.short += t.short_pct || 0; g.U.push(t.U); g.L.push(t.L);
      if (t.status === "Closed") { g.closed++; g.ret += t.ret || 0; g.pnl += t.pnl || 0; if ((t.pnl || 0) > 0) g.win++; } });
    const mode = (a) => { const c = {}; a.forEach((x) => { c[x] = (c[x] || 0) + 1; }); return Object.entries(c).sort((x, y) => y[1] - x[1])[0][0]; };
    $("a14Hist").innerHTML = `<div class="tbl"><table><thead><tr><th>Group</th><th class="n">Trades</th><th class="n">Closed</th><th class="n">Win rate</th><th class="n">Avg return</th><th class="n">Closed P&amp;L</th><th class="n">Avg short</th><th class="n">Usual wings</th></tr></thead><tbody>${
      Object.entries(grp).sort().map(([k, g]) => `<tr><td>${esc(k)}</td><td class="n">${g.n}</td><td class="n">${g.closed}</td><td class="n">${g.closed ? Math.round(100 * g.win / g.closed) + "%" : "–"}</td><td class="n">${g.closed ? fmt(g.ret / g.closed, 1) + "%" : "–"}</td><td class="n ${cls(g.pnl)}">${money(g.pnl)}</td><td class="n">${pctS(g.short / g.n)}</td><td class="n mono">${mode(g.U)}/${mode(g.L)}</td></tr>`).join("")}</tbody></table></div>
      <details><summary class="small">All ${T.length} entries</summary><div class="tbl"><table><thead><tr><th>Entry (US)</th><th>Trade</th><th class="n">DTE</th><th>Strikes</th><th class="n">Upper / short</th><th class="n">Wings</th><th class="n">Days held</th><th class="n">Adj.</th><th class="n">P&amp;L</th><th class="n">Return</th></tr></thead><tbody>${
      T.slice().reverse().map((t) => `<tr><td>${esc(t.entry)}</td><td class="small">${esc(t.name)} <span class="muted">${esc(t.status)}</span></td><td class="n">${t.dte}</td><td class="mono">${big(t.upper)}/${big(t.short)}/${big(t.lower)}</td><td class="n small">${pctS(t.upper_pct)} / ${pctS(t.short_pct)}</td><td class="n mono">${t.U}/${t.L}</td><td class="n">${t.dit}</td><td class="n">${t.adjustments}</td><td class="n ${cls(t.pnl)}">${money(t.pnl)}</td><td class="n ${cls(t.ret)}">${fmt(t.ret, 1)}%</td></tr>`).join("")}</tbody></table></div></details>
      <p class="note">From ONE (June onwards; the OptionStrat export has no legs). Entry structure = the legs opened in the first 10 minutes; "Adj." counts later leg changes. Open trades show ONE's realised P&amp;L only.</p>`;
  }).catch((e) => { $("a14Hist").innerHTML = err(e); });
}
$("a14Form").addEventListener("submit", (e) => { e.preventDefault(); scan(); });
$("a14Sort").addEventListener("change", () => { sortKey = $("a14Sort").value; if (A && A.candidates) table(); });
$("a14Usual").addEventListener("change", () => { if (A && A.candidates) table(); });
$("a14Vol").addEventListener("change", () => { $("a14VolC").hidden = $("a14Vol").value !== "custom"; });
$("a14Fetch").addEventListener("click", async () => {
  $("a14Fetch").disabled = true; $("a14Meta").textContent = "fetching the SPX/RUT put chains from TWS (about a minute)…";
  await api("/api/a14/refresh", {method: "POST"});
  await poll("/api/a14/status", scan, $("a14Meta"));
  $("a14Fetch").disabled = false;
});
$("a14Sort").innerHTML = Object.entries(SORTS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
$("a14Sort").value = sortKey;

window.loadEm = loadEm;
window.loadA14 = scan;
})();
