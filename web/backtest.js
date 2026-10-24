/* Evidence → Since 2009: the model backtest of your A14 and TimeEdge rules (desk/backtest.py). */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const pc = (v) => ok(v) ? `${Math.round(100 * v)}%` : "–";
const BAND = {steep: "Steep ≤ 0.834", normal: "Normal 0.834–0.90", flat: "Flat 0.90–1.00", backwardation: "Backwardation ≥ 1"};
let B = null, sel = "SPX|45";

const avgCell = (s, extra = "") => s ? `<td class="n ${cls(s.avg)}" title="${esc(`${s.n} trades · median ${pctS(s.median)} · p5 ${pctS(s.p5)} · worst ${pctS(s.worst)} · ${fmt(s.days, 0)} days held · ${fmt(s.per_day, 3)}%/day · stop hit ${pc(s.stop)} · target ${pc(s.target)}${ok(s.years_pos) ? ` · positive in ${pc(s.years_pos)} of ${s.years} years` : ""}`)}"><b>${pctS(s.avg)}</b>${extra}</td>` : `<td class="n">–</td>`;

async function loadBacktest(force) {
  const host = $("btSummary");
  if (!host) return;
  try {
    B = await api("/api/backtest" + (force ? "?force=1" : ""));
    if (B.error && !B.a14) { host.innerHTML = errBox(B.error); return; }
    if (!B.a14) { host.innerHTML = `<div class="state">Running the backtest (about 10 seconds)…</div>`; setTimeout(() => loadBacktest(), 4000); return; }
    render();
  } catch (e) { host.innerHTML = errBox(e); }
}

function row(u, dte) { return (B.a14[u] || []).find((r) => r.dte === dte); }

function render() {
  $("btMeta").textContent = `${B.from} → ${B.to} · built ${new Date(B.built).toLocaleString([], {day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})}`;
  const G = B.cal.gates, s45 = row("SPX", 45), s21 = row("SPX", 21), r60 = row("RUT", 60);
  const tile = (lbl, val, sub, c = "") => `<div><span class="lbl">${lbl}</span><b class="${c}">${val}</b><span class="small muted">${sub}</span></div>`;
  $("btSummary").innerHTML = `<div class="kv">
    ${tile("Calendars · old gate (0.834–1.00)", pctS(G.old.avg), `per trade · ${pc(G.old.win)} winners · positive in ${pc(G.old.years_pos)} of years`, cls(G.old.avg))}
    ${tile("Calendars · new gate (&lt; 0.90, uptrend)", pctS(G.new.avg), `per trade · ${pc(G.new.win)} winners · positive in ${pc(G.new.years_pos)} of years`, cls(G.new.avg))}
    ${tile("A14 SPX 45 · stop −10% → −20%", `${pctS(s45.card.avg)} → ${pctS(s45.plan.avg)}`, `stop hit ${pc(s45.card.stop)} → ${pc(s45.plan.stop)} of trades`, cls(s45.plan.avg - s45.card.avg))}
    ${tile("A14 SPX 45 · VIX/VIX3M &lt; 0.90 only", pctS(s45.gated.plan.avg), `vs ${pctS(s45.plan.avg)} entering every Friday (−20% stop)`, cls(s45.gated.plan.avg))}
    ${tile("A14 with no stop · SPX 21 / 45", `${pctS(s21.nostop.avg)} / ${pctS(s45.nostop.avg)}`, `but ${pc(s21.nostop.big_loss)} / ${pc(s45.nostop.big_loss)} of trades lost over half the margin`, "wrn")}
  </div>
  <ul class="small">
    <li><b>Calendars:</b> the old "avoid VIX/VIX3M ≤ 0.834" rule came from your June 2–4 2026 losses. The backtest reproduces those three days (${B.cal.june.filter((j) => j.date >= "2026-06-02" && j.date <= "2026-06-04").map((j) => pctS(j.ret, 0)).join(", ")}), but over 17 years steep contango was the <i>best</i> calendar zone. The losing zones are VIX/VIX3M 0.90+ and the index below its 20-day average. The readiness bar, calendar gates and Today's pick now use that rule.</li>
    <li><b>A14 entry:</b> the term structure matters more than any exit rule. Entries with VIX/VIX3M 0.90+ lost on average at every DTE; the readiness bar now sizes A14 down there (backwardation: stand aside).</li>
    <li><b>A14 stop:</b> −10% of margin was hit in ${pc(Math.min(...["SPX", "RUT"].flatMap((u) => B.a14[u].filter((r) => r.dte <= 60).map((r) => r.card.stop))))}–${pc(Math.max(...["SPX", "RUT"].flatMap((u) => B.a14[u].filter((r) => r.dte <= 60).map((r) => r.card.stop))))} of A14s (14–60 DTE), mostly on VIX pops that later reverted. −20% did better on SPX at 14–60 DTE and about the same on RUT; the Trade plan now uses −20% for A14. No stop at all averages best, but that average is paid for by full max losses (Feb 2018, Aug 2015, Feb 2020, Feb 2025: all entered in calm markets, so no entry filter catches them).</li>
    <li><b>Re-centring:</b> mechanical re-centring (at the decide line or on every 1.5% move) did worse than leaving the trade alone after costs, and was roughly a wash before them. The model can't see the skew, timing and judgment behind your own adjustments, which helped in 2026; it says only that adjusting by rule is not an edge by itself.</li>
    <li><b>DTE:</b> with a stop, 45 DTE (SPX and RUT) held up best; 14–30 DTE A14s were negative on average over the full history, positive only in calm stretches like 2026.</li>
  </ul>
  <p class="note">How: every Friday since ${B.from.slice(0, 4)}, your median A14 shape (in units of the implied move, from your ONE trades) is priced daily with the model that matched your ONE fills — Black-76, ATM vol from the CBOE VIX9D/VIX/VIX3M/VIX6M/VIX1Y curve (RUT scaled by RVX/VIX), your fitted put skew — and the exits replayed on daily closes. TimeEdge = ATM put calendar, 15 / 22 DTE, every weekday, card exits (+${B.cal.rule.tp}% / −${B.cal.rule.sl}%, out ${B.cal.rule.time_dte} DTE). Costs: $1.36 a contract a side plus a quarter point a combo a side (RUT 0.15), so all results are after costs. Returns are % of max loss (ONE margin) for A14 and % of the debit for calendars. Limits: daily closes only (no intraday stops), no bid/ask beyond the cost estimate, no event bumps in single expiries; checked against your recorded chains, the model's daily P&amp;L swings are about 80% of the real ones on SPX (correlation 0.85) and 95% on RUT (0.93). Treat differences under about 1% of margin as noise. Hover any figure for the full distribution.</p>`;

  // A14: rules × DTE
  const R = ["card", "plan", "nostop", "hold"];
  $("btRules").innerHTML = `<div class="tbl"><table><thead><tr><th>Entry</th><th class="n" title="median entry debit (pts) / max loss ($ per lot)">Debit / risk</th>${R.map((k) => `<th class="n">${esc(B.rules[k])}</th>`).join("")}<th class="n" title="revised plan, entries with VIX/VIX3M below 0.90 only">−20%, VIX/VIX3M &lt; 0.90</th><th class="n" title="share of calendar years with a positive average, revised plan">Years +</th></tr></thead><tbody>${
    ["SPX", "RUT"].flatMap((u) => B.a14[u].map((r) => `<tr><td>${u} ${r.dte} DTE <span class="small muted">target +${r.tp}%</span></td><td class="n small">${fmt(-r.credit, 2)} / $${Math.round(r.risk).toLocaleString()}</td>${R.map((k) => avgCell(r[k], `<span class="small muted"> · ${pc(r[k].win)}</span>`)).join("")}${avgCell(r.gated.plan, `<span class="small muted"> · ${pc(r.gated.plan.win)}</span>`)}<td class="n">${pc(r.plan.years_pos)}</td></tr>`)).join("")}</tbody></table></div>
    <p class="note">Average return per trade (% of margin) and winners. All rules: target +5% (entered at 21 DTE or less) or +7%, out at 2 DTE, slow trades (under 0.2%/day after 3 weeks) closed at the next green close; "Hold to 2 DTE" has no target or stop. Hover for the median, 5th percentile, worst trade, days held, %/day and stop rate.</p>`;

  // A14 by band
  const opts = ["SPX|21", "SPX|45", "RUT|21", "RUT|45"].filter((k) => { const [u, d] = k.split("|"); const r = row(u, +d); return r && r.bands; });
  if (!opts.includes(sel)) sel = opts[0];
  $("btBandSel").innerHTML = opts.map((k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${k.replace("|", " ")} DTE</option>`).join("");
  const [u, d] = sel.split("|"), rb = row(u, +d);
  $("btBands").innerHTML = `<div class="tbl"><table><thead><tr><th>VIX/VIX3M at entry</th><th class="n">Trades</th><th class="n">Stop −10%</th><th class="n">Stop −20%</th><th class="n">No stop</th><th class="n">No stop: lost &gt; 50%</th></tr></thead><tbody>${
    Object.keys(BAND).filter((b) => rb.bands.plan[b]).map((b) => `<tr><td>${BAND[b]}</td><td class="n">${rb.bands.plan[b].n}</td>${avgCell(rb.bands.card[b])}${avgCell(rb.bands.plan[b])}${avgCell(rb.bands.nostop[b])}<td class="n">${pc(rb.bands.nostop[b].big_loss)}</td></tr>`).join("")}
    ${["above", "below"].filter((k) => rb.trend[k]).map((k) => `<tr><td>${u} ${k} its 20-day average</td><td class="n">${rb.trend[k].n}</td><td class="n">–</td>${avgCell(rb.trend[k])}<td class="n">–</td><td class="n">–</td></tr>`).join("")}</tbody></table></div>`;
  $("btWorst").innerHTML = `<div class="tbl"><table><thead><tr><th>Entered</th><th class="n">Return</th><th class="n">VIX</th><th class="n">VIX/VIX3M</th><th>Trend</th></tr></thead><tbody>${
    (rb.worst || []).map((w) => `<tr><td class="mono small">${w.date}</td><td class="n neg">${pctS(w.ret, 0)}</td><td class="n">${fmt(w.vix, 1)}</td><td class="n">${fmt(w.ivts, 3)} <span class="small muted">${esc(w.band)}</span></td><td class="small">${esc(w.trend)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">The ten worst ${u} ${d}-DTE A14s with no stop: almost all were entered with VIX in the low teens and the term structure calm, a week or two before a shock. Entry filters don't catch these; a stop and position size do.</p>`;

  // calendars
  const C = B.cal, mx = Math.max(...C.fine.map((f) => Math.abs(f.avg)), 1);
  $("btCal").innerHTML = `<div class="tbl"><table><thead><tr><th>VIX/VIX3M at entry</th><th class="n">Trades</th><th class="n">Avg</th><th></th><th class="n">Winners</th><th class="n">Stop hit</th></tr></thead><tbody>${
    C.fine.map((f) => `<tr><td class="mono small">${f.lo.toFixed(3)} – ${f.hi > 2 ? "" : f.hi.toFixed(3)}</td><td class="n">${f.n}</td>${avgCell(f)}<td style="width:30%"><span style="display:inline-block;height:8px;width:${Math.round(48 * Math.abs(f.avg) / mx)}%;margin-left:${f.avg < 0 ? 50 - Math.round(48 * Math.abs(f.avg) / mx) : 50}%;background:${f.avg >= 0 ? "var(--up)" : "var(--down)"}"></span></td><td class="n">${pc(f.win)}</td><td class="n">${pc(f.stop)}</td></tr>`).join("")}
    ${["above", "below"].filter((k) => C.trend[k]).map((k) => `<tr><td>SPX ${k} its 20-day average</td><td class="n">${C.trend[k].n}</td>${avgCell(C.trend[k])}<td></td><td class="n">${pc(C.trend[k].win)}</td><td class="n">${pc(C.trend[k].stop)}</td></tr>`).join("")}</tbody></table></div>
    <div class="tbl"><table><thead><tr><th>Entry rule</th><th class="n">Trades</th><th class="n">Avg</th><th class="n">Winners</th><th class="n">Years +</th></tr></thead><tbody>${
    Object.values(C.gates).map((g) => `<tr><td>${esc(g.label)}</td><td class="n">${g.n}</td>${avgCell(g)}<td class="n">${pc(g.win)}</td><td class="n">${pc(g.years_pos)} <span class="small muted">of ${g.years}</span></td></tr>`).join("")}</tbody></table></div>
    <p class="note">SPX ATM put calendar, 15 / 22 DTE, entered every weekday, median debit $${C.debit.toLocaleString()}; returns % of the debit after costs. Model around your June losses: ${C.june.map((j) => `${j.date.slice(5)} (${j.ivts.toFixed(2)}) ${pctS(j.ret, 0)}`).join(" · ")}. Your own calendars entered at 0.90+ in late June mostly won small amounts; the 17-year sample is the better guide.</p>`;

  // managed
  $("btManaged").innerHTML = Object.entries(B.managed).map(([k, m]) => `<h3 class="small">${esc(k)} DTE</h3><div class="tbl"><table><thead><tr><th>Management</th><th class="n">Avg</th><th class="n">Winners</th><th class="n">Worst</th><th class="n">Adj. / trade</th></tr></thead><tbody>${
    ["static", "decide", "move", "move_nostop"].filter((k) => m[k]).map((k) => m[k]).map((v) => `<tr><td>${esc(v.label)}</td>${avgCell(v)}<td class="n">${pc(v.win)}</td><td class="n ${v.worst < -100 ? "neg" : ""}">${pctS(v.worst, 0)}</td><td class="n">${fmt(v.adj, 1)}</td></tr>`).join("")}</tbody></table></div>`).join("") +
    `<p class="note">Re-centre = close the BWB and open the same shape around today's close, same expiry, while more than 10 days remain; never when the trade is +3% or better. Each costs a combo side on 8 contracts. Without a stop, repeated re-centring in a selloff lost several times the original margin. Your own adjustments in 2026 (roll out on down moves, roll shorts up on up moves) are not modelled; the Trade plan's adjustment gates still come from them.</p>`;
}

window.loadBacktest = loadBacktest;
document.addEventListener("DOMContentLoaded", () => {
  const s = $("btBandSel"); if (s) s.addEventListener("change", () => { sel = s.value; render(); });
  const r = $("btRefresh"); if (r) r.addEventListener("click", () => loadBacktest(true));
});
})();
