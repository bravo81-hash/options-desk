/* Trade readiness bar (top of every tab) and its detail pop-up. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const COL = {"Full size": "var(--up)", "Three-quarter size": "var(--accent)", "Half size": "var(--accent)", "Quarter size": "var(--accent)", "Stand aside": "var(--down)"};
const SHORT = {"Full size": "full", "Three-quarter size": "¾", "Half size": "½", "Quarter size": "¼", "Stand aside": "stand aside"};
const ORDER = ["Stand aside", "Quarter size", "Half size", "Three-quarter size", "Full size"];
const pc = (v) => ok(v) ? Math.round(v) + "%" : "–";
const sg = (v, d = 1) => ok(v) ? (v > 0 ? "+" : "") + Number(v).toFixed(d) : "–";

/* drop odds on the size scale: teal full, blue ¾, amber ½, red stand aside; grey tick = normal */
const oddsBar = (v, base) => bulletSvg(v, {w: 160, lo: 0, hi: 45, color: v >= 30 ? "var(--down)" : v >= 23 ? "var(--warn)" : v >= 17 ? "var(--accent)" : "var(--up)",
  label: `${Math.round(v)}% chance of a 5% drop (normally ${Math.round(base)}%)`,
  zones: [{from: 0, to: 17, color: "var(--up)"}, {from: 17, to: 23, color: "var(--accent)"}, {from: 23, to: 30, color: "var(--warn)"}, {from: 30, to: 45, color: "var(--down)"}],
  marks: [{v: base, color: "var(--muted)", width: 1.5, label: `normally ${Math.round(base)}%`}]});

window.oddsBar = oddsBar;

function detail(R) {
  const rows = R.inputs.map((i) => `<tr class="${i.dd5 === R.risk ? "held" : ""}"><td>${esc(i.name)}</td><td class="small">${esc(i.reading)}</td>
    <td class="n"><b style="color:${i.dd5 >= 30 ? "var(--down)" : i.dd5 >= 23 ? "var(--warn)" : i.dd5 >= 17 ? "var(--accent)" : "var(--up)"}">${pc(i.dd5)}</b></td><td>${ok(i.dd5) ? oddsBar(i.dd5, R.base) : ""}</td><td class="n small muted">${i.n ?? "–"} since ${esc((i.since || "").slice(0, 4))}</td></tr>`).join("");
  const strat = R.strategies.map((s) => `<tr><td><b>${esc(s.name)}</b></td><td><b style="color:${COL[s.size]}">${esc(s.size)}</b><br>${sizeMeter(s.size)}</td><td class="small">${s.notes.map(esc).join("<br>")}</td></tr>`).join("");
  const T = R.trends, B = R.ivts_band;
  $("rdBody").innerHTML = `
    <div class="kv mini" style="margin-bottom:8px">
      <div><span class="lbl">Size for new premium selling</span><b style="color:${COL[R.size]}">${esc(R.size)}</b><span class="small muted">${esc(R.why)}</span></div>
      <div><span class="lbl">VIX/VIX3M</span><b>${ok(R.ivts) ? R.ivts.toFixed(3) : "–"}</b><span class="small muted">${esc(B.label)} · A14: ${esc(B.a14)} · calendars: ${esc(B.cal)}</span></div>
      <div><span class="lbl">Short-term trend (20-day)</span><b>SPX ${sg(T.SPX.short)}% · RUT ${sg(T.RUT.short)}%</b><span class="small muted">vs each index's 20-day average</span></div>
      <div><span class="lbl">Long-term trend (200-day)</span><b>SPX ${sg(T.SPX.long)}%</b><span class="small muted">vs its 200-day average</span></div>
    </div>
    <h3>By structure</h3>
    <div class="tbl"><table><thead><tr><th>Structure</th><th>Size</th><th>Why</th></tr></thead><tbody>${strat}</tbody></table></div>
    <h3 style="margin-top:10px">What sets it · chance SPX fell 5%+ within 21 sessions after days like today (normally ${pc(R.base)})</h3>
    <div class="tbl"><table><thead><tr><th>Input</th><th>Reading now</th><th class="n">5% drop</th><th title="teal full size · blue ¾ · amber ½ · red stand aside · grey tick = normal">On the size scale</th><th class="n">History</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${R.opportunities.length ? `<p class="small"><b style="color:var(--up)">Opportunities active:</b> ${R.opportunities.map(esc).join(" · ")}</p>` : ""}
    ${R.events.length ? `<p class="small"><b style="color:var(--warn)">Releases in the next 3 days:</b> ${R.events.map((e) => esc(e.title + " " + e.date.slice(5, 16).replace("T", " "))).join(" · ")}</p>` : ""}
    <p class="note">Each input gives its own historical odds; the verdict uses the highest one (they overlap, so adding them would double count): under 17% full size, 17–23% three-quarter, 23–30% half, 30%+ or any sit-out condition (HYG −1.5% day, VIX 40+) stand aside. Structures then step down for your own rules and the 2009–2026 backtest: A14 below the 20-day average (except with VIX/VIX3M 0.834–0.90), VIX9D/VIX 0.90+ in a steep or normal term structure, at VIX/VIX3M 0.90+ (backwardation: stand aside), thin RUT premium; calendars stand aside at VIX/VIX3M 0.90+ and step down below the 20-day average or into CPI / FOMC / payrolls / PCE / GDP. Market warnings: the five with history since 2010 (breadth has only a year of computed data, so it is shown on the Market tab but not used here). Data to the ${esc(R.date)} close.</p>`;
}
/* sidebar: the headline number of each view, without repeating it on the page */
function badges(R) {
  const nb = window.navBadge; if (!nb) return;
  const n = R.warnings.total6;
  nb("market", `${n} of 6`, n >= 5 ? "neg" : n >= 3 ? "wrn" : "");
  $("nb-market").title = `Market warnings: ${n} of 6`;
  [["a14", "A14"], ["cal", "Calendar"]].forEach(([tab, k]) => {
    const ss = R.strategies.filter((s) => s.name.startsWith(k)), best = ss.map((s) => s.size).sort((a, b) => ORDER.indexOf(b) - ORDER.indexOf(a))[0];
    if (best) nb(tab, SHORT[best], best === "Stand aside" ? "neg" : best === "Full size" ? "pos" : "sz");
  });
}
async function load() {
  try {
    const R = await api("/api/readiness");
    if (R.error) { $("readyBar").innerHTML = `<span class="small muted">${esc(R.error)}</span>`; return; }
    window.READY = R;
    $("readyBar").innerHTML = `<span class="lbl">Trade readiness</span><b class="rdsize" style="color:${COL[R.size]}">${esc(R.size)}</b>${sizeMeter(R.size)}
      <span class="small muted rdwhy" title="${esc(R.why)}">${esc(R.why)}</span>
      ${R.strategies.map((s) => `<button type="button" class="rdchip" title="${esc(s.notes.join(" · "))}">${esc(s.name)} <b style="color:${COL[s.size]}">${SHORT[s.size]}</b></button>`).join("")}
      <button type="button" class="ghost" id="rdOpen">Why</button>`;
    detail(R);
    const why = () => { $("rdPanel").hidden = false; if (window.renderMatrix) window.renderMatrix(R); };
    $("readyBar").querySelectorAll("#rdOpen,.rdchip").forEach((b) => b.addEventListener("click", why));
    badges(R);
    window.dispatchEvent(new Event("readiness"));
  } catch (e) { $("readyBar").innerHTML = ""; }
}
load(); setInterval(load, 600000);
window.loadReadiness = load;
})();
