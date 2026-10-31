/* Heads-up: the event-risk chip in the ribbon and the Event risk, Overnight, Stress and Pre-close sub-tabs on Actions.
   Information only (desk/heads.py): nothing here feeds the size call, gates, rankings or Today's pick. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const LEVEL = {red: ["var(--down)", "Red", "neg"], amber: ["var(--warn)", "Amber", "wrn"], green: ["var(--up)", "Green", "pos"], unknown: ["var(--muted)", "Unknown", "muted"]};
const ET = {timeZone: "America/New_York"};
const etTime = (iso) => iso ? new Date(iso).toLocaleString([], {...ET, weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"}) + " ET" : "–";
const etDay = (d) => new Date(d + "T12:00:00Z").toLocaleDateString([], {weekday: "short", day: "numeric", timeZone: "UTC"});
const tile = (l, b, sub, k = "") => `<div><span class="lbl">${l}</span><b class="${k}">${b}</b><span class="small muted">${sub}</span></div>`;
const capped = (head, rows, n, tag = 8) => `<div class="capped"><div class="tbl"><table><thead><tr>${head}</tr></thead><tbody>${rows.map((r, i) => r(i >= tag)).join("")}</tbody></table></div>${rows.length > tag ? `<button type="button" class="ghost" data-cap="Show all ${n}">Show all ${n}</button>` : ""}</div>`;
const spark = (v, label) => { if (!v || v.length < 2) return "";
  const w = 120, h = 26, lo = Math.min(0, ...v), hi = Math.max(0, ...v), Y = (x) => h - 2 - (x - lo) * (h - 4) / ((hi - lo) || 1), X = (i) => i * w / (v.length - 1);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}"><line x1="0" x2="${w}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="var(--line)"/><polyline fill="none" stroke="${v[v.length - 1] >= 0 ? "var(--up)" : "var(--down)"}" stroke-width="1.5" points="${v.map((x, i) => `${X(i).toFixed(1)},${Y(x).toFixed(1)}`).join(" ")}"/></svg>`; };
const preWindow = () => { const p = new Intl.DateTimeFormat("en-US", {...ET, weekday: "short", hour: "numeric", minute: "numeric", hour12: false}).formatToParts(new Date()), g = (t) => (p.find((x) => x.type === t) || {}).value;
  const m = +g("hour") * 60 + +g("minute"); return !["Sat", "Sun"].includes(g("weekday")) && m >= 870 && m < 960; };

let H = null, RK = null, opened = false;

async function load() {
  H = await api("/api/heads").catch(() => null);
  if (H && H.error) H = null;
  window.HEADS = H;
  ribbon(); render();
  window.dispatchEvent(new Event("heads"));
  return H;
}

function openSub(name) {
  showTab("actions");
  setTimeout(() => { const h = $("acMore"); showSub(h, name); h.scrollIntoView({behavior: "smooth", block: "start"}); }, 80);
}

function ribbon() {
  const el = $("rdHeads"); if (!el) return;
  if (!H) { el.innerHTML = `<button type="button" class="rdchip" id="rdHeadsBtn" title="The heads-up feeds could not be read">Event risk <b class="muted">unavailable</b></button>`; return; }
  const [col, word] = LEVEL[H.score.level], st = H.stress, n = H.alerts.length;
  const tip = [...H.score.why, ...H.alerts, ok(st.n) ? `stress: ${st.n} of ${st.of} signals firing` : ""].filter(Boolean).join(" · ");
  el.innerHTML = `<button type="button" class="rdchip" id="rdHeadsBtn" title="${esc(tip)}">Event risk <b style="color:${col}">${word}</b>${ok(st.n) ? ` · Stress <b>${st.n}</b> of ${st.of}` : ""}${n ? ` · <b style="color:var(--warn)">⚠ ${n} alert${n > 1 ? "s" : ""}</b>` : ""}</button>`;
}

function render() {
  if (!$("acEvent")) return;
  const miss = `<div class="state">Heads-up feeds unavailable: nothing here can be read as calm. Check the Data check tab.</div>`;
  if (!H) { ["acEvent", "acNight", "acStress"].forEach((id) => { $(id).innerHTML = miss; }); pre(); return; }
  eventView(); nightView(); stressView(); pre();
}

/* ---------- event risk ---------- */
function eventView() {
  const S = H.score, [col, word, k] = LEVEL[S.level];
  $("acEvMeta").textContent = `as of ${etTime(H.ts)} · S&P 500 weights ${H.weights_asof || "from market cap"}`;
  const bullet = (v, end) => `${bulletSvg(v, {w: 160, lo: 0, hi: 25, color: col, label: `${fmt(v, 1)}% of the S&P 500 reports by ${etTime(end)}`,
    zones: [{from: 0, to: 5, color: "var(--up)"}, {from: 5, to: 15, color: "var(--warn)"}, {from: 15, to: 25, color: "var(--down)"}], marks: [{v: 5, color: "var(--warn)", label: "amber at 5%"}, {v: 15, color: "var(--down)", label: "red over 15%"}]})}`;
  const next = H.macro.find((m) => ["Payrolls", "CPI", "FOMC", "Election"].includes(m.kind));
  const big = H.earnings.filter((e) => e.weight >= 0.25 || e.groups.length);
  const eRows = big.map((e) => (x) => `<tr${x ? ` class="xrow"` : ""}><td class="small">${esc(etTime(e.when).replace(/,? \d+:\d+.*$/, ""))}</td><td title="${esc(e.name || "")}"><b>${esc(e.sym)}</b></td><td class="small">${e.firm ? esc(e.session) : `<span class="chip muted" title="date not confirmed by the company">est.</span>`}</td><td class="n">${e.weight ? fmt(e.weight, 2) + "%" : "–"}</td><td class="small muted" style="white-space:normal">${esc(e.groups.join(" · "))}</td></tr>`);
  const hi = H.macro.filter((m) => m.importance >= 1);
  const mRows = hi.map((m) => (x) => `<tr${x ? ` class="xrow"` : ""}><td class="small">${esc(etTime(m.date))}</td><td>${["Payrolls", "CPI", "FOMC", "Election"].includes(m.kind) ? "<b>" + esc(m.title) + "</b>" : esc(m.title)}${m.source === "schedule" ? ` <span class="small muted" title="from the official schedule built into the desk">schedule</span>` : ""}</td></tr>`);
  $("acEvent").innerHTML = `${H.feed_note ? `<div class="state err" style="margin-bottom:8px">${esc(H.feed_note)}</div>` : ""}
    <div class="kv mini" style="margin-bottom:8px">
      ${tile("Event risk", `<span class="chip ${k}">${word}</span>`, esc(S.why.join(" · ")))}
      ${tile("Reports, next 24 trading hours", fmt(S.pct24, 1) + "% of SPX", bullet(S.pct24, S.w24) + `<br>to ${esc(etTime(S.w24))}`)}
      ${tile("Reports, next 48 trading hours", fmt(S.pct48, 1) + "% of SPX", bullet(S.pct48, S.w48) + `<br>to ${esc(etTime(S.w48))}`)}
      ${tile("Next top-tier release", next ? esc(next.title.replace(" (schedule)", "")) : "none in 2 weeks", next ? esc(etTime(next.date)) : "")}
    </div>
    <div class="hgrid" style="grid-template-columns:minmax(220px,.8fr) minmax(360px,1.3fr) minmax(320px,1.1fr)">
      <div><h3>Earnings by day <span class="small muted">% of the S&amp;P 500 reporting</span></h3><div class="chart" id="acEvChart"></div></div>
      <div><h3>Earnings to watch <span class="small muted">top names and anyone over 0.25% of SPX</span></h3>${big.length ? capped("<th>When</th><th>Name</th><th>Session</th><th class=\"n\">% SPX</th><th>Watched as</th>", eRows, big.length, 6) : `<div class="state">No large name reports in the next week.</div>`}</div>
      <div><h3>High-impact releases <span class="small muted">next 14 days</span></h3>${hi.length ? capped("<th>When</th><th>Release</th>", mRows, hi.length, 6) : `<div class="state">${esc(H.feed_note || "No high-impact releases in the next 14 days.")}</div>`}</div>
    </div>
    <p class="note">Information only: event risk does not change the size call, gates, rankings or Today's pick. Red = over 15% of the S&amp;P 500 reports within 24 trading hours, or payrolls, CPI, FOMC or an election falls inside them. Amber = 5% or more reports, a top-10 name reports, or another high-impact release falls inside 24 trading hours; or a top-tier release or over 15% inside 48. Trading hours skip weekends and market holidays, so Friday's 24 hours reach Monday evening. Green needs both feeds up; with one down and nothing else to flag it reads Unknown, never calm. Green here doesn't mean no gap: a surprise from a mid-size name (Intel, 0.7% of SPX) can move the whole market.</p>`;
  barChart($("acEvChart"), {h: 150, label: "percent of the S&P 500 reporting by day", items: H.sessions.map((d) => { const v = d.pre + d.post; return {label: etDay(d.day), v, color: v > 15 ? "var(--down)" : v >= 5 ? "var(--warn)" : "var(--accent)", title: `${esc(etDay(d.day))}: <b>${v.toFixed(1)}%</b><br>before the open ${d.pre.toFixed(1)}% · after the close ${d.post.toFixed(1)}%`}; })});
}

/* ---------- overnight and leaders ---------- */
function nightView() {
  const O = H.overnight, V = O.vx, L = H.leaders;
  $("acNightMeta").textContent = `${O.session} · futures from ${O.close ? etTime(O.close) : "–"} · refreshed ${etTime(H.ts)}`;
  const down = [H.feeds.futures, H.feeds.scan, H.feeds.vx].filter((f) => !f.ok);
  const fut = O.futures.map((f) => tile(`${esc(f.sym)} vs cash close`, ok(f.chg) ? `<span class="${cls(f.chg)}">${pctS(f.chg, 2)}</span>${f.alert ? ` <span class="chip wrn">⚠ over 0.75%</span>` : ""}` : "–",
    `${spark(f.spark, `${f.sym} since the cash close`)}<br>${ok(f.implied) ? `${esc(f.index)} ≈ ${Math.round(f.implied).toLocaleString()} vs close ${Math.round(f.cash).toLocaleString()}` : "no quote"}${f.at ? ` · ${esc(etTime(f.at))}` : ""}`)).join("");
  const vx = V ? tile("VIX futures, front vs second", `<span class="${V.spread < 0 ? "wrn" : ""}">${fmt(V.front.px, 2)} / ${fmt(V.second.px, 2)}</span>`,
    `${V.spread < 0 ? "inverted" : "contango"} ${sgn(V.spread, 2)} pts${ok(V.prev_spread) ? ` (was ${sgn(V.prev_spread, 2)})` : ""} · settled ${esc(V.date)}, end of day only`) : tile("VIX futures", "–", "settlements unavailable");
  const lRows = L.rows.map((r) => (x) => { const [a, b] = r.moves;
    const day = (m) => m ? `<span class="${cls(m.ret)}">${pctS(m.ret)}</span> <span class="small muted">${ok(m.z) ? sgn(m.z, 1) + "σ" : ""}</span>` : "–";
    return `<tr${x && !r.alert ? ` class="xrow"` : ""}><td><b>${esc(r.sym)}</b>${r.alert ? ` <span class="chip wrn">⚠ spillover</span>` : r.broke ? ` <span class="chip muted" title="broke the line, but only a top-10 name or SMH raises the alert">shown only</span>` : ""}</td><td class="small muted">${esc(r.groups.join(" · "))}</td><td class="n">${ok(r.weight) ? fmt(r.weight, 2) + "%" : "–"}</td><td class="n">${day(a)}</td><td class="n">${day(b)}</td><td>${ok(a.z) ? hBarSvg(a.z, 6, {w: 80, label: "last session in σ of its 60-day moves (full bar = 6σ)"}) : ""}</td></tr>`; });
  $("acNight").innerHTML = `${down.length ? `<div class="state err" style="margin-bottom:8px">Feed unavailable, last good copy shown: ${esc(down.map((f) => f.name).join(", "))}.</div>` : ""}
    ${H.alerts.length ? `<div class="state" style="margin-bottom:8px"><b style="color:var(--warn)">⚠ ${esc(H.alerts.join(" · "))}</b></div>` : ""}
    <div class="kv mini" style="margin-bottom:8px">${fut}${vx}</div>
    <div class="hgrid">
      <div><h3>Top 10 names, ${esc(O.session)} <span class="small muted">alert over ±5% out of hours</span></h3><div class="chart" id="acNightMovers"></div></div>
      <div style="grid-column:span 2"><h3>Leader spillover <span class="small muted">sessions to ${esc(L.date || "–")}: a top-10 name or SMH down 3σ or 7% flags next-day risk</span></h3>${L.rows.length ? capped("<th>Name</th><th>Watched as</th><th class=\"n\">% SPX</th><th class=\"n\">Last session</th><th class=\"n\">Session before</th><th>Size</th>", lRows, L.rows.length, 6) : `<div class="state">No leader bars yet.</div>`}</div>
    </div>
    <p class="note">Each future is compared with its own price at the 16:00 ET cash close, because futures trade at a basis to cash; the cash level is that move applied to the close. Quotes are yfinance's, about 10 minutes late, and stop at Friday's 17:00 ET futures close until Sunday evening. VIX futures are CBOE's daily settlements: no free overnight quote exists, so this shows the curve as it stood at the last close. After-hours moves come from TradingView's scanner and are thin before 16:30 ET. σ is each name's daily moves over the 60 sessions before that day.</p>`;
  barChart($("acNightMovers"), {h: 150, label: "top 10 names out of hours", items: O.movers.map((m) => ({label: m.sym, v: m.move, hi: m.alert, title: `${esc(m.sym)} <b>${pctS(m.move, 2)}</b> · ${fmt(m.weight, 2)}% of SPX`}))});
}

/* ---------- stress ---------- */
function stressView() {
  const S = H.stress;
  if (!ok(S.n)) { $("acStress").innerHTML = `<div class="state">Not enough history yet.</div>`; return; }
  const k = {red: "neg", amber: "wrn", calm: ""}[S.level] || "";
  $("acStressMeta").textContent = `close of ${S.date} · separate from the Market warnings (of 6)`;
  const rows = S.signals.map((s) => `<tr><td class="small muted">${esc(s.group)}</td><td>${esc(s.name)}</td><td>${s.on === null ? `<span class="chip muted">no data</span>` : s.on ? `<span class="chip wrn">⚠ firing</span>` : `<span class="small muted">quiet</span>`}</td><td class="n mono small">${esc(s.reading)}</td><td class="small muted" style="white-space:normal;min-width:170px">${esc(s.rule)}</td><td class="n small muted">${ok(s.rate) ? Math.round(s.rate) + "%" : "–"}</td></tr>`).join("");
  $("acStress").innerHTML = `<div class="hgrid" style="grid-template-columns:minmax(260px,1fr) minmax(420px,2fr)">
      <div><div class="kv mini" style="margin-bottom:8px">${tile("Firing now", `<span class="${k}">${S.n} of ${S.of}</span>`, `higher than ${S.pct}% of the last year · amber at 3, red at 5`)}</div>
        <h3>Last 30 sessions</h3><div class="chart" id="acStressChart"></div></div>
      <div><div class="tbl"><table><thead><tr><th>Group</th><th>Signal</th><th>Now</th><th class="n">Reading</th><th>Fires when</th><th class="n" title="share of the last 252 sessions it fired">Fires</th></tr></thead><tbody>${rows}</tbody></table></div></div>
    </div>
    <p class="note">A count, not a verdict: the signals overlap and nothing here changes the size call. NYSE and Nasdaq advance/decline and new lows aren't in a free feed, so breadth uses S&amp;P 500 members, computed here; RSP vs SPY stands for equal weight against cap weight. Cross-assets are read at each S&amp;P close, so Bitcoin's weekend moves land on Monday. The "Fires" column shows how often each signal is on: VVIX 100+ is common at this vol level, so read it with the others.${S.no_data.length ? ` No data yet for ${esc(S.no_data.join(", "))}.` : ""}</p>`;
  barChart($("acStressChart"), {h: 130, unit: "", label: "stress signals firing, last 30 sessions", items: S.hist.map((d) => ({label: shortDate(d.d), v: d.n, color: d.n >= 5 ? "var(--down)" : d.n >= 3 ? "var(--warn)" : "var(--accent)", title: `${esc(d.d)}: <b>${d.n} of ${S.of}</b>`}))});
}

/* ---------- pre-close ---------- */
function pre() {
  const el = $("acPre"); if (!el) return;
  const Rk = RK, O = Rk && Rk.overnight, S = H && H.score, hg = Rk && Rk.hedge;
  const inWin = preWindow();
  $("acPreMeta").textContent = inWin ? "window open: 14:30–16:00 ET" : "for the 14:30–16:00 ET window · shown any time";
  const row = (name, flag, body) => `<tr><td><b>${name}</b></td><td>${flag}</td><td style="white-space:normal">${body}</td></tr>`;
  const lock = window.DESK_CLOUD ? "unlock your snapshot to see this" : "needs TWS marks";
  const rows = [
    row("Event risk, next 24 trading hours", S ? `<span class="chip ${LEVEL[S.level][2]}">${LEVEL[S.level][1]}</span>` : `<span class="chip muted">feed unavailable</span>`, S ? esc(S.why.join(" · ")) : "The heads-up feeds could not be read."),
    row("Net gamma", O ? `<b class="${cls(O.gamma_1pct)}">${money(O.gamma_1pct)}</b>` : "–", O ? `On a 1% move, ${O.gamma_1pct < 0 ? "short gamma costs about that much" : "long gamma makes about that much"} on top of delta, either way. Estimated at today's IVs across all accounts.` : lock),
    row("±2σ overnight", O ? `<b class="${cls(O.down2)}">${money(O.down2)}</b> / <b class="${cls(O.up2)}">${money(O.up2)}</b>` : "–", O ? `SPX ±${fmt(2 * O.sd_pct, 1)}% (VIX ${fmt(O.vix, 1)}, one day), RUT at beta 1.2, IVs unchanged, repriced at the next open (${esc(etTime(O.at))}). Real gaps come with IV moves: the Risk grid's Gap what-if has both.` : lock),
    row("Hedge reference", S && S.level === "red" ? `<span class="chip wrn">event risk red</span>` : `<span class="small muted">only when red</span>`, S && S.level === "red"
      ? (hg ? `SPX ${Math.round(hg.long)}/${Math.round(hg.short)} put spread, ${hg.dte} DTE (${esc(hg.expiry)}): about <b>${money(hg.cost * 100)}</b> a spread at ask/bid, ${money(hg.mid * 100)} at mid, from the surface recorded ${esc(etTime(hg.ts))}. A reference price with no size: it isn't a recommendation to hedge.` : lock === "needs TWS marks" ? "No recorded SPX surface to price it from." : lock)
      : "A put-spread cost appears here when event risk is red."),
  ].join("");
  el.innerHTML = `<div class="tbl"><table><thead><tr><th>Check</th><th>Reading</th><th>What it means</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">Informational only: nothing here changes a rule or a size.</p>`;
  const line = $("acPreLine"); if (!line) return;
  line.innerHTML = inWin ? `<div class="state" style="margin-bottom:8px"><b>Pre-close window open.</b> Event risk ${S ? LEVEL[S.level][1].toLowerCase() : "unavailable"}${O ? ` · net gamma ${money(O.gamma_1pct)} · ±2σ overnight ${money(O.down2)} / ${money(O.up2)}` : ""}. <a href="#" id="acPreOpen" class="small">checklist →</a></div>` : "";
  if (inWin && !opened) { opened = true; showSub($("acMore"), "Pre-close"); }
}

document.addEventListener("click", (e) => {
  if (e.target.closest("#rdHeadsBtn")) { openSub(H && H.alerts.length ? "Overnight" : "Event risk"); return; }
  if (e.target.closest("#acPreOpen")) { e.preventDefault(); e.stopPropagation(); openSub("Pre-close"); return; }
  const r = e.target.closest("#acHdRefresh"); if (!r) return;
  r.disabled = true; r.textContent = "Refreshing…";
  fetch("/api/heads/refresh", {method: "POST"}).then(load).finally(() => { r.disabled = false; r.textContent = "Refresh"; });
});
window.addEventListener("readiness", ribbon);
window.loadHeads = load;
window.renderHeads = (Rk) => { RK = Rk; render(); };
load(); setInterval(load, 300000);
})();
