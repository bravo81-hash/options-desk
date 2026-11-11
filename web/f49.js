/* F49: the far-OTM put tent scanner (desk/f49.py). Three candidates per ticker off the fetched chain: the rule's shorts one straddle
   below the index, one a little nearer, one a little further. Reference only: nothing here is an order. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const day = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-AU", {weekday: "short", day: "numeric", month: "short", timeZone: "UTC"});
const expiry = (e) => new Date(Date.UTC(+e.slice(0, 4), +e.slice(4, 6) - 1, +e.slice(6))).toLocaleDateString("en-AU", {day: "numeric", month: "short", timeZone: "UTC"});
const SIZE_CLS = {"Full size": "pos", "Three-quarter size": "sz", "Half size": "sz", "Quarter size": "sz", "Stand aside": "neg"};
let F = null, pick = {SPX: null, RUT: null};

function chart(sym) {
  const S = F.scan[sym], c = S && S.cands && S.cands.find((x) => x.x === pick[sym]) || (S && S.cands && S.cands.find((x) => x.rule)) || (S && S.cands && S.cands[0]);
  const el = $(`f49Chart${sym}`); if (!el || !c) return;
  const pts = (ys) => c.curve.xs.map((x, i) => [x, ys[i]]);
  xyChart(el, {h: 230, dots: false, label: `${sym} ${c.upper}/${c.short}/${c.lower} profit and loss a lot by index level`,
    vlines: [{x: S.spot, color: "var(--ink)", label: `${sym} now ${fmt(S.spot, 0)}`}, {x: c.short, color: "var(--warn)", label: `shorts ${fmt(c.short, 0)}`}],
    series: [{name: "Today", color: "var(--accent)", pts: pts(c.curve.now)}, {name: `At ${F.card.time_dte} DTE`, color: "var(--up)", pts: pts(c.curve.d14)},
      {name: "At expiry", color: "var(--muted)", dash: "4 3", pts: pts(c.curve.exp)}]});
  $(`f49Leg${sym}`).innerHTML = `<span class="small"><b style="color:var(--accent)">━</b> today · <b style="color:var(--up)">━</b> at ${F.card.time_dte} DTE, the time stop · <b style="color:var(--muted)">┅</b> at expiry (never held that long) · US$ a lot, <b>${c.upper}/${c.short}/${c.lower}</b></span>`;
}

function block(sym) {
  const S = F.scan[sym];
  if (!S) return "";
  if (!S.cands || !S.cands.length) return `<h3>${sym}</h3><div class="state">${esc(S.note || "No candidates.")}</div>`;
  const accts = Object.keys(F.navs || {});
  const row = (c) => { const on = (pick[sym] ?? 1) === c.x, lots = c.lots;
    const nav = (n) => accts.map((a) => `${esc(a)} ${(100 * n * c.risk / F.navs[a]).toFixed(1)}%`).join(" · ");
    return `<tr class="click${on ? " sel" : ""}" data-sym="${sym}" data-x="${c.x}" tabindex="0">
      <td>${c.rule ? `<span class="chip sz">the rule</span>` : `<span class="small muted">${c.x < 1 ? "nearer" : "further"}</span>`}<br><span class="small muted">${c.x}× straddle</span></td>
      <td><b class="mono">${c.upper}/${c.short}/${c.lower}</b><br><span class="small muted">shorts ${fmt(c.below_pct, 1)}% from ${sym} · wings ${c.U}/${c.L}</span></td>
      <td class="n"><b>${fmt(c.credit, 2)}</b> <span class="small muted">mid</span><br><span class="small ${ok(c.credit_nat) && c.credit_nat < 0 ? "wrn" : "muted"}">${ok(c.credit_nat) ? `${fmt(Math.abs(c.credit_nat), 2)} ${c.credit_nat >= 0 ? "credit" : "debit"} at bid/ask` : "no bid/ask"}${c.quoted ? "" : " · model price"}</span></td>
      <td class="n">${money(c.risk)}<br><span class="small muted">credit ${fmt(c.credit_pct, 1)}% of it</span></td>
      <td class="n">${c.delta > 0 ? "+" : ""}${fmt(c.delta, 1)}<br><span class="small muted">θ ${money(c.theta)}/day</span></td>
      <td class="n neg">${money(c.at_shorts.now)}<br><span class="small muted">in 2 wks ${money(c.at_shorts.wk2)} · IV +5: ${money(c.at_shorts.wk2_iv5)}</span></td>
      <td class="n ${c.at_shorts.d14 < 0 ? "neg" : "pos"}">${money(c.at_shorts.d14)}<br><span class="small muted">target +${F.card.target}% = ${money(c.target_usd)}</span></td>
      <td class="n">${ok(lots) ? `<b class="${lots ? "" : "wrn"}">${lots}</b>` : "–"} <span class="small muted">${S.size ? "at " + esc(S.size.toLowerCase()) : "size unread"}</span><br><span class="small muted">full size ${c.lots_full ?? "–"}${lots ? ` · ${nav(lots)} of NAV` : ""}</span></td></tr>`; };
  return `<h3 style="margin:10px 0 4px">${sym} <span class="small muted">${fmt(S.spot, 0)} · ${expiry(S.expiry)}, ${S.dte} days · straddle ${fmt(S.straddle, 1)} at ${fmt(S.straddle_k, 0)} = ${fmt(S.em_pct, 1)}% of the index</span>
      ${S.size ? `<span class="chip ${SIZE_CLS[S.size] || ""}">${esc(S.size.toLowerCase())}</span>` : ""}</h3>
    ${S.note ? `<p class="small wrn">${esc(S.note)}</p>` : ""}
    <div class="tbl"><table><thead><tr><th>Shorts</th><th>Strikes</th><th class="n">Credit a lot</th><th class="n">Worst case a lot</th><th class="n" title="US$ per index point, a lot">Delta</th>
      <th class="n" title="profit or loss a lot if the index were at the shorts: today, and in two weeks with and without IV 5 points higher">If the index is at the shorts now</th><th class="n">…at ${F.card.time_dte} DTE</th><th class="n">Lots</th></tr></thead>
      <tbody>${S.cands.map(row).join("")}</tbody></table></div>
    <div class="chart" id="f49Chart${sym}"></div><div id="f49Leg${sym}"></div>`;
}

function render() {
  const el = $("f49Body"); if (!el) return;
  if (!F) { el.innerHTML = `<div class="state loading">Pricing the tent…</div>`; return; }
  if (F.error) { el.innerHTML = `<div class="state">${esc(F.error)}</div>`; return; }
  const C = F.card, any = Object.values(F.scan || {}).some((s) => s.cands && s.cands.length);
  $("f49Meta").textContent = F.chain_ts ? `priced on the ${new Date(F.chain_ts).toLocaleString([], {weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})} chain` : "no chain fetched yet";
  const capTxt = ok(F.cap_pct) ? `all F49 worst cases under <b>${F.cap_pct}%</b> of NAV, per account` : `<b class="wrn">no F49 cap set</b>: set one on the Rules page before the first trade`;
  el.innerHTML = `<div class="kv mini">
      <div><span class="lbl">Shape</span><b>1 / −2 / 1 puts</b><span class="small muted">shorts one straddle below the index, about 0.8 sd</span></div>
      <div><span class="lbl">Entry</span><b>${F.entry_day ? "Today" : day(F.entry_next)}</b><span class="small muted">Fridays, the expiry nearest ${C.entry_dte} days (${C.dte_lo}–${C.dte_hi}) · at most ${C.cap} a ticker</span></div>
      <div><span class="lbl">Exits</span><b>+${C.target}% · below the shorts · ${C.time_dte} DTE</b><span class="small muted">whichever comes first · never adjusted</span></div>
      <div><span class="lbl">Size</span><b>${C.worst_nav}% of NAV an id</b><span class="small muted">worst case at full size, scaled by the readiness bar · same lots in every account</span></div>
      <div><span class="lbl">Your cap</span><span class="small">${capTxt}</span></div></div>
    ${any ? "" : `<div class="state">${F.chain_ts ? "" : "No chain yet: press Fetch chain from TWS on this tab (TWS must be running)."}</div>`}
    ${["SPX", "RUT"].map(block).join("")}
    <p class="note"><b>How to read it.</b> The middle row is the rule; the other two show what moving the shorts a tenth of a straddle does. <i>Credit at bid/ask</i> is what a fill with no price improvement pays: the tested edge assumes mid, so a fill near bid/ask can remove it.
      <i>If the index is at the shorts</i> is the trade's main risk: it loses there until the last two weeks, which is why the card closes on a close below the shorts. The +${C.target}% target is rarely reached first (9% of trades in the model); most trades end at the ${C.time_dte} DTE time stop with about 4–5% of the worst case.
      <b>Evidence, plainly:</b> SPX 2009–2026 in the desk's model, skew refitted on 18 recorded days: +4.6% a year, 10.5% deepest fall, 82% winners averaging +3.6% against losers averaging −7.7%. With the desk's older skew it was +1.8% a year; with doubled costs +0.4%. These figures are SPX only. It is thin: treat the first trades as a trial at the smallest size.</p>`;
  ["SPX", "RUT"].forEach(chart);
  el.querySelectorAll("tr[data-x]").forEach((tr) => tr.addEventListener("click", () => { pick[tr.dataset.sym] = +tr.dataset.x; render(); }));
}

window.loadF49 = async () => { render(); F = await api("/api/f49").catch(() => ({error: "F49 scanner unavailable"})); render(); };
})();
