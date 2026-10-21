/* Today's pick: calendar vs A14 BWB, SPX vs RUT, on one screen. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const MONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const xd = (e) => `${+e.slice(6, 8)} ${MONS[+e.slice(4, 6) - 1]}`;
const big = (v) => Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : (+v).toFixed(0);
const NAME = {calendar: "Put calendar (time spread)", bwb: "A14 put BWB (single expiry)"};

function setupLine(b) {
  if (!b) return "–";
  return b.structure === "calendar"
    ? `${b.sym} ${big(b.strike)}P · sell ${xd(b.front)} / buy ${xd(b.back)} <span class="muted">(${b.fdte}/${b.bdte} DTE, strike ${sgn(b.strike_pct, 1)}%)</span>`
    : `${b.sym} ${big(b.upper)} / ${big(b.short)} / ${big(b.lower)} · ${xd(b.expiry)} <span class="muted">(${b.dte} DTE, wings ${b.U}/${b.L})</span>`;
}
function cost(b) {
  return b.structure === "calendar" ? `debit ${fmt(b.debit, 2)}` : (b.credit >= 0 ? `credit ${fmt(b.credit, 2)}` : `debit ${fmt(-b.credit, 2)}`);
}
function readyChip(c) {
  const R = window.READY; if (!R) return "";
  const s = R.strategies.find((x) => x.name === `${c.structure === "bwb" ? "A14" : "Calendar"} ${c.sym}`); if (!s) return "";
  return `<span class="chip" title="${esc(s.notes.join(" · "))}" style="color:${{"Full size": "var(--up)", "Three-quarter size": "var(--accent)", "Half size": "var(--warn)"}[s.size] || "var(--down)"}">${esc(s.size)}</span>`;
}
function cell(c) {
  const b = c.best;
  if (!b) return `<div class="pcell"><h3>${c.sym} · ${NAME[c.structure]}</h3><div class="state">No candidates in the chain.</div></div>`;
  const checks = c.checks.map((k) => `<li><span class="${k.ok ? "pos" : "neg"}">${k.ok ? "✓" : "✕"}</span> ${esc(k.text)}</li>`).join("");
  const alts = (c.alts || []).map((a) => `<li>${setupLine(a)} · <b>${fmt(a.exp_day, 2)}%</b>/day</li>`).join("");
  return `<div class="pcell ${c.rank === 1 ? "top" : ""}">
    <div class="row" style="justify-content:space-between"><h3>${c.sym} · ${NAME[c.structure]}</h3><span>${readyChip(c)} <span class="rank">#${c.rank ?? "–"}</span></span></div>
    <div class="mono" style="font-size:13.5px">${setupLine(b)}</div>
    <div class="kv mini">
      <div><span class="lbl">Edge / day</span><b class="${cls(b.exp_day)}">${fmt(b.exp_day, 2)}%</b><span class="small muted">of risk, per day held</span></div>
      <div><span class="lbl">At exit (${b.h}d)</span><b class="${cls(b.exp_h)}">${money(b.exp_h)}</b><span class="small muted">${fmt(b.exp_risk, 1)}% of risk · P(profit) ${Math.round(100 * b.pop_h)}%</span></div>
      <div><span class="lbl">Risk / lot</span><b>${money(b.risk)}</b><span class="small muted">${cost(b)}</span></div>
      <div><span class="lbl">θ · vega</span><b>${money(b.theta)} · ${fmt(b.vega, 0)}</b><span class="small muted">per day · per vol pt</span></div>
      <div><span class="lbl">−1σ by exit</span><b class="${cls(b.down1sd_h)}">${money(b.down1sd_h)}</b><span class="small muted">${b.structure === "calendar" ? `IVs −2 pts: ${money(b.iv_drop2)}` : "spot falls 1σ"}</span></div>
    </div>
    <ul class="checks">${checks}</ul>
    ${alts ? `<details><summary class="small muted">Next best</summary><ul class="small" style="margin:4px 0;padding-left:16px">${alts}</ul></details>` : ""}
  </div>`;
}
async function load() {
  window.loadVixCond($("vcBody"), false);
  $("pkBody").innerHTML = `<div class="state">Working out today's pick…</div>`;
  try {
    const q = new URLSearchParams({exit: $("pkExit").value, vol: $("pkVol").value});
    const P = await api("/api/pick?" + q);
    if (P.error) { $("pkBody").innerHTML = `<div class="state err">${esc(P.error)}</div>`; return; }
    $("pkMeta").textContent = `chain from TWS ${new Date(P.chain_ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})} · VIX/VIX3M ${fmt(P.ivts, 3)} · SPX ${sgn(P.trend.SPX && P.trend.SPX.vs_sma20, 1)}% / RUT ${sgn(P.trend.RUT && P.trend.RUT.vs_sma20, 1)}% vs 20-day average`;
    const get = (sym, st) => P.cells.find((c) => c.sym === sym && c.structure === st);
    const top = P.pick && get(P.pick.sym, P.pick.structure);
    const second = P.cells.filter((c) => c.rank === 2)[0];
    const why = top ? [
      `${top.checks_passed} of ${top.checks_n} of your own rules pass`,
      `model edge ${fmt(top.best.exp_day, 2)}% of risk per day held (${fmt(top.best.exp_risk, 1)}% by the exit date, P(profit) ${Math.round(100 * top.best.pop_h)}%)`,
      second && second.best ? `runner-up: ${second.sym} ${NAME[second.structure].toLowerCase()} at ${fmt(second.best.exp_day, 2)}%/day with ${second.checks_passed}/${second.checks_n} rules` : "",
    ].filter(Boolean) : [];
    const banner = top ? `<div class="pickbar"><div><span class="lbl">Today's pick</span><span class="big">${top.sym} · ${NAME[top.structure]}</span>
        <div class="mono">${setupLine(top.best)}</div></div><ul>${why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : "";
    const allFail = P.cells.every((c) => !c.checks_ok);
    $("pkBody").innerHTML = banner + (allFail ? `<div class="state err">None of the four passes all of your own rules today: consider smaller size or waiting.</div>` : "") +
      `<div class="pgrid"><div class="phead"></div><div class="phead">Put calendar · time spread</div><div class="phead">A14 put BWB · single expiry</div>
        <div class="pside">SPX</div>${cell(get("SPX", "calendar"))}${cell(get("SPX", "bwb"))}
        <div class="pside">RUT</div>${cell(get("RUT", "calendar"))}${cell(get("RUT", "bwb"))}</div>
      <p class="note">Ranking: setups that pass all your own rules come first, then by model edge per day held. Both structures are priced from the same TWS chain and smile, held for the same exit days (a calendar at most to the day before its front expiry), with odds from a lognormal at ${P.vol_basis === "iv" ? "implied" : "20-day realised"} vol, which understates crash risk. The model holds IVs still; calendars are long vega and lose if IVs fall (see "IVs −2 pts"), BWBs are short vega. Your rules: calendars — VIX/VIX3M above 0.834 (your calendar-family trades: ${P.cal_record.above.n} above it made ${money(P.cal_record.above.pnl)}, ${P.cal_record.below.n} at or below lost ${money(-P.cal_record.below.pnl)}) and the TimeEdge / Triple / TimeZone gates; A14 — index above its 20-day average (${fmt(P.a14_trend.above.ret, 1)}% vs ${fmt(P.a14_trend.below.ret, 1)}%). A shortlist, not an instruction.</p>`;
  } catch (e) { $("pkBody").innerHTML = `<div class="state err">${esc(e.message || e)}</div>`; }
}
$("pkForm").addEventListener("submit", (e) => { e.preventDefault(); load(); });
$("pkFetch").addEventListener("click", async () => {
  $("pkFetch").disabled = true; $("pkMeta").textContent = "fetching the SPX/RUT chains from TWS (about a minute)…";
  await api("/api/a14/refresh", {method: "POST"});
  for (let i = 0; i < 90; i++) { await new Promise((r) => setTimeout(r, 3000)); const s = await api("/api/a14/status").catch(() => null); if (s && !s.running) break; }
  $("pkFetch").disabled = false; load();
});
window.loadPick = load;
window.addEventListener("readiness", () => { if ($("pkBody").innerHTML.includes("pcell")) load(); });
})();
