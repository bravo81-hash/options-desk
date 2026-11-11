/* The 130-day structure (desk/longdated.py): an SPX put butterfly about 130 days out plus a call calendar into the next monthly,
   rebuilt each day on the recorded surface. Shows what it costs, what moves it, and where its two main drivers (the gap between
   the two expiries' IVs, and put skew) stand against history. A timing reference: no rule, no size, no order. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const sgn = (v) => ok(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + "$" + Math.abs(Math.round(v)).toLocaleString() : "–";
const expiry = (e) => e ? new Date(Date.UTC(+e.slice(0, 4), +e.slice(4, 6) - 1, +e.slice(6))).toLocaleDateString("en-AU", {day: "numeric", month: "short", year: "2-digit", timeZone: "UTC"}) : "–";
const day = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-AU", {day: "numeric", month: "short", timeZone: "UTC"});
const nth = (n) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"}`;
let L = null;

/* where a stand-in sits: lowest, middle or highest third of its history, and what followed days like it */
function third(S) { return S.now <= S.cuts[0] ? "low" : S.now <= S.cuts[1] ? "mid" : "high"; }
function reading(S, goodLow) {
  const t = third(S), a = S.after[t];
  const k = t === "mid" ? ["sz", "middle third"] : (t === "low") === goodLow ? ["pos", `${t === "low" ? "lowest" : "highest"} third: has tended to move in the structure's favour`] : ["neg", `${t === "low" ? "lowest" : "highest"} third: has tended to move against it`];
  return {t, a, cls: k[0], txt: k[1]};
}

function bars(B) {
  const rows = [["Front-expiry IVs up 1 point, back unchanged", B.front_up1, "the gap between the two expiries narrowing by a point"], ["Back-expiry IV up 1 point, front unchanged", B.back_up1, "the gap widening by a point"],
    ["IV at the lowest put alone up 1 point", B.skew_up1, "put skew steepening"], ["Every IV up 1 point together", B.vega, "a parallel move: the two sides nearly cancel"],
    ["SPX −5% with IVs +5, today", B.scen.down5, ""], ["SPX +5% with IVs −3, in 30 days", B.scen.up5_30, ""], ["Nothing moves for 30 days", B.scen.flat30, "30 days of theta"], ["One day of theta", B.theta, ""]];
  const mx = Math.max(...rows.map((r) => Math.abs(r[1] || 0)), 1);
  return `<div class="tbl"><table><thead><tr><th>If this happens</th><th class="n">US$ a lot</th><th style="width:44%">Size against the others</th></tr></thead><tbody>${rows.map(([name, v, note]) => { const w = Math.abs(v) / mx * 50;
    return `<tr><td>${esc(name)}${note ? `<br><span class="small muted">${esc(note)}</span>` : ""}</td><td class="n ${v > 0 ? "pos" : v < 0 ? "neg" : ""}"><b>${sgn(v)}</b></td>
      <td><span class="rstrack" style="width:100%;display:inline-block;vertical-align:middle"><i style="${v >= 0 ? `left:50%;width:${w}%;background:var(--up)` : `left:${50 - w}%;width:${w}%;background:var(--down)`}"></i></span></td></tr>`; }).join("")}</tbody></table></div>`;
}

function render() {
  const el = $("ldBody"); if (!el) return;
  if (!L) { el.innerHTML = `<div class="state loading">Pricing the structure…</div>`; return; }
  if (L.error) { el.innerHTML = `<div class="state">${esc(L.error)}</div>`; return; }
  const B = L.build, S = L.standins || {}, H = L.history || [], f = L.defs;
  $("ldMeta").textContent = `on the ${day(L.date)} recorded surface · SPX ${fmt(L.spot, 0)} · model prices, not quotes`;
  const leg = (l) => `<tr><td>${l.q > 0 ? "Buy" : "Sell"} ${Math.abs(l.q)}</td><td><b class="mono">${fmt(l.strike, 0)} ${l.right === "P" ? "put" : "call"}</b></td><td>${l.back && B.back_est ? `about ${fmt(B.back_dte, 0)} days` : expiry(l.back ? L.back : L.front)}${l.back && B.back_est ? ` <span class="chip wrn" title="the next monthly isn't in the recording yet, so this leg is priced on the front expiry's IV at its strike, ${B.back_dte} days out">estimated</span>` : ""}</td>
    <td class="n">${fmt(100 * Math.abs(l.delta), 0)}Δ</td><td class="n">${fmt(l.iv, 1)}%</td></tr>`;
  const slope = S.slope ? reading(S.slope, true) : null, skew = S.skew ? reading(S.skew, true) : null, O = L.own;
  const tile = (lbl, big, cls, sub) => `<div><span class="lbl">${lbl}</span><b class="${cls || ""}">${big}</b><span class="small muted">${sub}</span></div>`;
  const evid = (S, r, unit, what) => `After days in the lowest third it rose over the next ${f.ahead} sessions ${S.after.low.up}% of the time (${S.after.low.chg > 0 ? "+" : ""}${S.after.low.chg}${unit} on average); after the highest third, ${S.after.high.up}% (${S.after.high.chg > 0 ? "+" : ""}${S.after.high.chg}${unit}). ${what}`;
  el.innerHTML = `<div class="kv mini">
      ${tile("Cost a lot", money(B.cost), "", `butterfly ${money(B.cost_fly)} + call calendar ${money(B.cost_cal)} · the most it can lose`)}
      ${tile("Theta", `${money(B.theta)} a day`, "", `${fmt(B.theta_pct, 2)}% of the cost a day`)}
      ${tile("Expiry gap, stand-in", slope ? `${fmt(S.slope.now, 2)} pts` : "–", slope ? slope.cls : "", slope ? `VIX6M less VIX3M · ${nth(S.slope.pct)} percentile since 2009 · ${slope.txt}` : "no history")}
      ${tile("Put skew, stand-in", skew ? fmt(S.skew.now, 0) : "–", skew ? skew.cls : "", skew ? `CBOE SKEW · ${nth(S.skew.pct)} percentile since 2009 · ${skew.txt}` : "no history")}
      ${tile("Desk's own skew", `${fmt(B.skew, 2)} pts`, "", `IV at the lowest put less the top put · ${nth(O.skew.pct)} percentile of ${O.skew.n} recorded days`)}
      ${tile("Desk's own gap", ok(B.gap) ? `${fmt(B.gap, 2)} pts` : "not recorded yet", ok(B.gap) ? "" : "wrn", ok(B.gap) ? `back less front IV at the call strikes · ${O.gap.n} recorded days` : `the ${B.back_dte}-day monthly isn't in the recording: from the next daily recording it will be`)}</div>
    <div class="grid" style="margin-top:8px">
      <div class="c5"><h3 style="margin:0 0 4px">The legs today <span class="small muted">delta of the whole ${B.delta > 0 ? "+" : ""}${fmt(B.delta, 1)}</span></h3>
        <div class="tbl"><table><thead><tr><th></th><th>Strike</th><th>Expiry</th><th class="n">Delta</th><th class="n">IV</th></tr></thead><tbody>${B.legs.map(leg).join("")}</tbody></table></div>
        <p class="small muted">Front expiry: the monthly nearest ${f.front} days (${B.front_dte} today). The long call's strike is the one that brings the whole position nearest zero delta; when it lands on the short call's strike, the call side is a plain calendar.</p></div>
      <div class="c7"><h3 style="margin:0 0 4px">Profit and loss a lot by SPX level</h3><div class="chart" id="ldPay"></div>
        <span class="small"><b style="color:var(--accent)">━</b> today · <b style="color:var(--warn)">━</b> in 30 days · <b style="color:var(--up)">━</b> in 60 days · <b style="color:var(--muted)">┅</b> at the front expiry, cut off at the top: it peaks near <span id="ldPeak"></span> at the short puts · every strike keeping today's IV</span></div>
    </div>
    <h3 style="margin:12px 0 4px">What moves it</h3>${bars(B)}
    <div class="grid" style="margin-top:10px">
      <div class="c6"><h3 style="margin:0 0 4px">Expiry gap stand-in: VIX6M less VIX3M, two years</h3><div class="chart" id="ldSlope"></div>
        <p class="small muted">${S.slope ? evid(S.slope, slope, " pts", "A rising slope is the back expiry gaining on the front, which is what the call calendar is paid for.") : ""}</p></div>
      <div class="c6"><h3 style="margin:0 0 4px">Put skew stand-in: CBOE SKEW, two years</h3><div class="chart" id="ldSkew"></div>
        <p class="small muted">${S.skew ? evid(S.skew, skew, "", "Steepening skew lifts the lowest put, which helps the butterfly; flattening hurts it.") : ""}</p></div>
      <div class="c12"><h3 style="margin:0 0 4px">The desk's own record: ${H.length} recorded days</h3><div class="chart" id="ldHist"></div>
        <span class="small"><b style="color:var(--accent)">━</b> skew, vol points (left) · <b style="color:var(--up)">━</b> theta, US$ a day ÷ 3 · <b style="color:var(--warn)">━</b> expiry gap, vol points × 5, on the days both monthlies were recorded</span></div>
    </div>
    <p class="note"><b>How to read it for timing.</b> Theta is the smallest line in the table: a one-point change in the gap between the two expiries is worth about ${Math.round(Math.abs(B.front_up1) / Math.max(B.theta, 0.1) / 21)} months of it. So the two readings that matter are the expiry gap (you buy the back month and sell the front: better when the back is cheap against the front, the stand-in in its lowest third) and put skew (better when flat, the stand-in in its lowest third).
      <b>What this is not.</b> The thirds are from the stand-ins, not from this structure: VIX6M less VIX3M covers 3 to 6 months, not these two expiries, and SKEW is a 30-day measure. The desk's own figures have ${H.length} days behind them, too few to rank. No timing rule here has been tested on the structure itself, and the cost shown moves by several hundred dollars when a strike steps 25 points, so judge the gap and skew, not the cost. Prices are from the fitted smile; five long-dated legs will cost more than this to get in and out of.</p>`;
  // the expiry line peaks far above the others (the butterfly's full width): cut it so today's and the 30- and 60-day lines can be read
  const near = [...B.curve.now, ...B.curve.d30, ...B.curve.d60], cap = Math.max(...near.map(Math.abs)) * 2.5, peak = Math.max(...B.curve.exp);
  const pts = (ys, cut) => B.curve.xs.map((x, i) => [x, cut ? Math.max(-cap, Math.min(cap, ys[i])) : ys[i]]);
  xyChart($("ldPay"), {h: 240, dots: false, label: "130-day structure profit and loss a lot by SPX level",
    vlines: [{x: L.spot, color: "var(--ink)", label: `SPX ${fmt(L.spot, 0)}`}, {x: B.legs[1].strike, color: "var(--muted)", label: `short puts ${fmt(B.legs[1].strike, 0)}`}, {x: B.legs[3].strike, color: "var(--muted)", label: `calls ${fmt(B.legs[3].strike, 0)}`}],
    series: [{name: "At the front expiry", color: "var(--muted)", dash: "4 3", pts: pts(B.curve.exp, true)}, {name: "In 60 days", color: "var(--up)", pts: pts(B.curve.d60)}, {name: "In 30 days", color: "var(--warn)", pts: pts(B.curve.d30)}, {name: "Today", color: "var(--accent)", pts: pts(B.curve.now)}]});
  $("ldPeak").textContent = money(peak);
  const std = (id, S, name, fy) => S && lineChart($(id), {h: 170, label: name, fy, endLabels: false, refs: [{y: S.cuts[0], label: "lowest third below"}, {y: S.cuts[1], label: "highest third above"}],
    series: [{name, color: "var(--accent)", width: 2, data: S.series}]});
  std("ldSlope", S.slope, "VIX6M less VIX3M, vol points", (v) => `${v}`); std("ldSkew", S.skew, "CBOE SKEW index", (v) => `${v}`);
  if (H.length > 1) lineChart($("ldHist"), {h: 170, label: "the structure's skew, theta and expiry gap on each recorded day", endLabels: false, fy: (v) => `${v}`,
    series: [{name: "Skew, vol points", color: "var(--accent)", width: 2, data: H.map((r) => ({d: r.date, v: r.skew}))}, {name: "Theta, US$ a day ÷ 3", color: "var(--up)", width: 1.5, data: H.map((r) => ({d: r.date, v: +(r.theta / 3).toFixed(2)}))},
      {name: "Expiry gap, vol points × 5", color: "var(--warn)", width: 1.5, data: H.filter((r) => ok(r.gap)).map((r) => ({d: r.date, v: +(r.gap * 5).toFixed(2)}))}]});
}

window.loadLong = async () => { render(); L = await api("/api/longdated").catch(() => ({error: "130-day structure unavailable"})); render(); };
})();
