/* Now: the one screen for the trading hour. Three questions (can I open anything, what do I do with what I hold, am I within my
   limits), the daily read of the week ahead, and the automatic log. Everything else sits behind the Detail switch.
   Also draws the Process scoreboard on P&L: drawdown, rules followed and the reads, with no profit target. */
"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const pctS = (v, d = 1) => ok(v) ? `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%` : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const go = (tab, text, sub) => `<a href="#" class="small" data-go="${tab}"${sub ? ` data-sub="${esc(sub)}"` : ""}>${esc(text)} →</a>`;
const SIZE_CLS = {"Full size": "pos", "Three-quarter size": "sz", "Half size": "sz", "Quarter size": "sz", "Stand aside": "neg"};
const ACT = {exit: ["neg", "⚠ Exit"], decide: ["wrn", "⚠ Decide"], close: ["pos", "✓ Close"], marks: ["wrn", "◌ Marks incomplete"], slow: ["wrn", "◔ Exit at next green"]};
const CALL = {quiet: ["Quiet", "pos"], normal: ["Normal", "sz"], rough: ["Rough", "neg"]};
const day = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-AU", {weekday: "short", day: "numeric", month: "short", timeZone: "UTC"});
const big = (word, k, sub) => `<div class="nwbig"><b class="${k}">${esc(word)}</b><span>${sub}</span></div>`;
let D = {};

/* the entry rule for one ticker today (desk/a14rules.py entry_ok): the week's Friday entry, or a midweek one that replaces it */
const etDate = (iso) => iso ? new Date(iso).toLocaleDateString("en-CA", {timeZone: "America/New_York"}) : null;
window.a14Entry = function (u, LAD, Rk, Rd) {
  if (!Rk || !Array.isArray(Rk.trades) || !Array.isArray(Rk.limits)) return {ok: false, why: "the book limits are unread"};
  const P = LAD.rule, s = ((Rd && Rd.strategies) || []).find((x) => x.name === `A14 ${u}`), size = s ? s.size : null;
  const over = ((Rk && Rk.limits) || []).filter((a) => a.over).map((a) => a.label);
  const wk = ((Rk && Rk.trades) || []).filter((t) => t.strategy === "A14" && t.underlying === u && (etDate(t.opened_iso) || "") >= LAD.week_start);
  if (over.length) return {ok: false, why: `${over.join(" and ")} over your limits`};
  if (!LAD.session) return {ok: false, why: "the market is shut"};
  const entered = ((LAD.week_opened || {})[u] || []);
  if (entered.length) return {ok: false, why: `this week's id is already on (opened ${day(entered[0])})`};
  if (wk.length) return {ok: false, why: `this week's id is already on (opened ${day(etDate(wk[0].opened_iso))})`};
  if (!size) return {ok: false, why: "the readiness size is unread"};
  if (size === "Stand aside") return {ok: false, why: "the readiness bar says stand aside"};
  if (LAD.entry_day) return {ok: true, kind: "friday", why: "the week's entry day"};
  if (LAD.today >= P.mid_from && (P.mid_sizes || []).includes(size)) return {ok: true, kind: "midweek", why: `${size.toLowerCase()} on the readiness bar and every account inside its limits`};
  return {ok: false, why: `midweek needs full or three-quarter size; the bar reads ${size.toLowerCase()}`};
};

/* ---------- 1. can I open anything? ---------- */
function canOpen() {
  const el = $("nwOpen"), Rd = D.Rd, Rk = D.Rk, LAD = D.LAD;
  if (!Rd || Rd.error) { el.innerHTML = `<div class="state">${esc((Rd && Rd.error) || "Reading the market…")}</div>`; return; }
  const over = ((Rk && Rk.limits) || []).filter((a) => a.over);
  const a14 = (Rd.strategies || []).filter((s) => s.name.startsWith("A14"));
  const etToday = new Date().toLocaleDateString("en-CA", {timeZone: "America/New_York"});
  const sizes = a14.map((s) => `<span class="chip ${SIZE_CLS[s.size] || ""}" title="${esc(s.notes.join(" · "))}">${esc(s.name)}: ${esc(s.size.toLowerCase())}</span>`).join(" ");
  let head, lines = [];
  if (over.length) {
    head = big("No", "neg", "the book is over your limits");
    lines = over.flatMap((a) => a.alerts.filter((x) => /your/.test(x)).map((x) => `<b>${esc(a.label)}</b>: ${esc(x)}`));
    lines.push("Nothing new fits until the open ids run off or are closed by their own rules.");
  } else if (a14.length && a14.every((s) => s.size === "Stand aside")) {
    head = big("No", "neg", "the market read says stand aside");
    lines = [esc(Rd.why), ...a14.flatMap((s) => s.notes.slice(0, 1).map((n) => `${esc(s.name)}: ${esc(n)}`))];
  } else if (!LAD) {
    head = big("…", "muted", "pricing the next id");
  } else if (LAD.error) {
    head = big("?", "muted", esc(LAD.error));
  } else {
    const P = LAD.rule, known = Rk && Rk.trades, rows = [], kinds = [];
    ["SPX", "RUT"].forEach((u) => { const n = LAD.next[u], s = a14.find((x) => x.name === `A14 ${u}`), lots = n && s ? n.lots[s.size] : null, e = window.a14Entry(u, LAD, Rk, Rd);
      const most = known ? Math.max(0, ...Object.keys(LAD.navs).map((a) => Rk.trades.filter((t) => t.strategy === "A14" && t.underlying === u && t.acctLabel === a).length)) : null;
      if (!e.ok) rows.push(`<b>${u}</b>: no, ${esc(e.why)}`);
      else if (ok(most) && most >= P.cap) rows.push(`<b>${u}</b>: no, ${most} ids open (cap ${P.cap})`);
      else if (!n) rows.push(`<b>${u}</b>: no Friday expiry in ${P.dte_lo}–${P.dte_hi} DTE on the chain`);
      else if (!lots) rows.push(`<b>${u}</b>: no, ${esc(s ? s.size.toLowerCase() : "no size")} rounds to 0 lots`);
      else { kinds.push(e.kind); rows.push(`<b>${u}</b>: yes, <b>${lots} lot${lots > 1 ? "s" : ""}</b> at ${esc(s.size.toLowerCase())} · ${n.dte}d <span class="mono">${Math.round(n.upper)}/${Math.round(n.short)}/${Math.round(n.lower)}</span>${e.kind === "midweek" ? ` <span class="chip sz" title="${esc(e.why)}">midweek: replaces Friday's</span>` : ""}`); } });
    const yes = kinds.length > 0;
    head = yes ? big("Yes", "pos", "one id per ticker this week, same lots in every account") : !LAD.session ? big("Not today", "muted", "the market is shut") : LAD.entry_day ? big("No", "neg", "nothing fits today") : big("Not today", "muted", `no ticker meets the midweek conditions: next Friday entry ${day(LAD.entry_next)}`);
    lines = rows;
    if (!yes && !LAD.entry_day) lines.push(`Sizes now: ${sizes}`);
  }
  el.innerHTML = `${head}<ul class="nwlist">${lines.map((x) => `<li>${x}</li>`).join("")}</ul>
    <p class="small muted">${esc(Rd.size)}: ${esc(Rd.why)}. ${go("actions", "A14 ladder")}</p>`;
}

/* ---------- 2. what do I do with what I hold? ---------- */
function hold() {
  const el = $("nwHold"), Rk = D.Rk;
  if (!Rk) { el.innerHTML = `<div class="state">${D.loaded ? "Open trades unavailable: is a ONE report in Documents?" : "Reading your trades…"}</div>`; return; }
  const P = Rk.trades.filter((t) => t.plan && t.plan.act !== "hold").sort((a, b) => a.plan.pri - b.plan.pri || (a.totalPct ?? 0) - (b.totalPct ?? 0));
  const held = Rk.trades.length - P.length;
  if (!P.length) { el.innerHTML = `${big("Nothing", "pos", `all ${Rk.trades.length} open trades are between their stop and target`)}`; return; }
  const order = (o) => window.orderTxt ? window.orderTxt(o, true) : "";
  const what = (t) => { const q = t.plan;
    return q.act === "exit" ? "close now"
      : q.act === "marks" ? "refresh marks with TWS running; the target order still stands"
      : q.act === "close" ? `close now${q.order ? ` · ${order(q.order)}` : ""}`
      : q.act === "slow" ? "close at the next close at 0% or better"
      : `adjust only if the gates pass: <span class="chip">${esc(q.adj.ok)}</span>, otherwise hold to the stop`; };
  el.innerHTML = `${big(String(P.length), "wrn", `need something · ${held} just hold`)}
    <div class="tbl"><table><tbody>${P.map((t) => { const [k, word] = ACT[t.plan.act] || ["", t.plan.label];
      return `<tr><td><span class="chip ${k}">${esc(word)}</span></td><td>${esc(t.name)} <span class="small muted">${esc(t.acctLabel || "")}</span></td>
        <td class="n ${cls(t.totalPct)}"><b>${pctS(t.totalPct)}</b>${window.basisTag ? window.basisTag(t) : ""}</td><td class="small">${what(t)}</td>
        <td><a href="#" class="small" data-trade="${esc(t.id)}">detail →</a></td></tr>`; }).join("")}</tbody></table></div>
    <p class="small muted">Returns are % of margin against each trade's own stop and target. ${go("risk", "Trade plan", "Trade plan")}</p>`;
}

/* ---------- 3. am I within my limits? ---------- */
function limits() {
  const el = $("nwLimits"), Lm = D.Rk && D.Rk.limits;
  if (!Lm || !Lm.length) { el.innerHTML = `<div class="state">${D.loaded ? "No marked trades to measure." : "Measuring the book…"}</div>`; return; }
  const bar = (v, cap, label) => !ok(v) ? "–" : bulletSvg(v, {w: 220, lo: 0, hi: Math.max((cap || 10) * 2, v * 1.1), color: ok(cap) && v > cap ? "var(--down)" : "var(--up)", label,
    zones: ok(cap) ? [{from: 0, to: cap, color: "var(--up)"}, {from: cap, to: Math.max(cap * 2, v * 1.1), color: "var(--down)"}] : [], marks: ok(cap) ? [{v: cap, color: "var(--ink)", label: `your limit ${cap}%`}] : []});
  const anyOver = Lm.some((a) => a.over), move = fmt((Lm[0].stress || {}).move, 0);
  const NAME = {A14: "All A14 worst cases", F49: "All F49 worst cases", total: "Every strategy together"};
  const keys = ["A14", "F49", "total"].filter((k) => Lm.some((a) => (a.caps || []).some((c) => c.key === k && (ok(c.cap) || (k !== "total" && c.n)))));
  const capCell = (a, k) => { const c = (a.caps || []).find((x) => x.key === k);
    if (!c) return `<td class="small muted">none open</td>`;
    return `<td><b class="${c.over ? "neg" : ""}">${c.open_ended ? "no ceiling" : ok(c.pct) ? fmt(c.pct, 1) + "%" : "–"}</b> <span class="small muted">of ${ok(c.cap) ? c.cap + "%" : "no cap set"}</span><br>${bar(c.pct, c.cap, `${a.label} ${NAME[k]} ${c.pct}% of NAV`)}</td>`; };
  el.innerHTML = `${big(anyOver ? "Over" : "Within", anyOver ? "neg" : "pos", anyOver ? "no new ids until back under" : "room for the next id")}
    <div class="tbl"><table><thead><tr><th>Limit</th>${Lm.map((a) => `<th>${esc(a.label)}</th>`).join("")}</tr></thead><tbody>
    ${keys.map((k) => `<tr><td title="each open trade at its worst case, added up, as % of NAV">${NAME[k]}</td>${Lm.map((a) => capCell(a, k)).join("")}</tr>`).join("")}
    <tr><td title="the whole book on a ${move}% day either way with IVs moving, as % of NAV">A ${move}% day, whole book</td>${Lm.map((a) => { const s = a.stress || {};
      return `<td><b class="${ok(s.limit) && s.pct > s.limit ? "neg" : ""}">${ok(s.pct) ? fmt(s.pct, 1) + "%" : "–"}</b> <span class="small muted">of ${ok(s.limit) ? s.limit + "%" : "no limit set"}</span><br>${bar(s.pct, s.limit, `${a.label} stress ${s.pct}% of NAV`)}</td>`; }).join("")}</tr></tbody></table></div>
    <p class="small muted">${go("risk", "Book what-if", "What-if")} ${go("rules", "Change a limit")}</p>`;
}

/* ---------- the daily read: one tap, scored a week later ---------- */
function read() {
  const el = $("nwRead"), C = D.P && D.P.calls;
  if (!C) { el.innerHTML = `<div class="state">${D.loaded ? "The read is unavailable." : "…"}</div>`; return; }
  const f = C.defs, S = C.score;
  const tip = {quiet: `SPX never closes more than ${Math.abs(f.quiet)}% below today's close in the next ${f.ahead} sessions`,
    normal: `SPX closes between ${Math.abs(f.quiet)}% and ${Math.abs(f.rough)}% below at its worst`, rough: `SPX closes ${Math.abs(f.rough)}% or more below at some point`};
  const btn = (k) => `<button type="button" class="nwcall ${C.mine === k ? "on " + CALL[k][1] : ""}" data-call="${k}"${window.DESK_CLOUD ? " disabled" : ""} title="${esc(tip[k])}">${CALL[k][0]}<span>${C.base ? C.base[k] + "% of weeks" : ""}</span></button>`;
  const rate = (h, n) => n ? `${h} of ${n}` : "–";
  el.innerHTML = `<div class="nwcalls">${Object.keys(CALL).map(btn).join("")}</div>
    <p class="small">${C.mine ? `Your read for the week after ${day(C.today)}: <b>${CALL[C.mine][0]}</b>. The desk's read: <b>${C.app ? CALL[C.app][0] : "–"}</b>. You can change yours until that session ends.`
      : window.DESK_CLOUD ? "No read made for this session yet. It is made on the laptop desk: this copy can't save." : `How will the next ${f.ahead} sessions go? One tap. The desk's own read stays hidden until you've made yours.`}</p>
    <p class="small muted">Scored so far: you <b>${rate(S.mine, S.mine_n)}</b> · the desk <b>${rate(S.app, S.app_n)}</b> · always saying quiet <b>${rate(S.quiet, S.n)}</b>${S.n < 20 ? ` · ${S.n} weeks scored: it takes about 20 before this says anything` : ""}. Quiet = SPX stays within ${Math.abs(f.quiet)}% of today's close on the downside; rough = it closes ${Math.abs(f.rough)}%+ lower at some point.</p>`;
  el.querySelectorAll("[data-call]").forEach((b) => b.addEventListener("click", async () => {
    const r = await api("/api/process/call", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mine: b.dataset.call})}).catch(() => null);
    if (r && !r.error) { D.P.calls = r; read(); } }));
}

/* ---------- the automatic log: each decision against the rules, nothing typed ---------- */
function logRows(rows, withNote) {
  return rows.map((d) => `<tr><td class="small">${day(d.exit && !d.open ? d.exit : d.entry)}<br><span class="muted">${d.open ? "opened" : "closed"}</span></td>
    <td>${esc(d.name)} <span class="small muted">${esc(d.accts.join(" + "))}</span></td>
    <td>${d.planned ? `<span class="chip pos">✓ as planned</span>` : `<span class="chip wrn">differed</span>`}</td>
    <td class="small">${d.planned ? `<span class="muted">${d.checks} rules checked</span>` : d.why.map(esc).join("<br>")}</td>
    ${withNote ? `<td>${d.planned ? "" : `<input class="nwnote" data-key="${esc(d.key)}" value="${esc(d.note || "")}" placeholder="${window.DESK_CLOUD ? "notes are typed on the laptop" : "one line, when you have time"}" maxlength="200"${window.DESK_CLOUD ? " disabled" : ""}>`}</td>` : ""}</tr>`).join("");
}
function bindNotes(el) {
  el.querySelectorAll(".nwnote").forEach((i) => i.addEventListener("change", async () => {
    const r = await api("/api/journal/note", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key: i.dataset.key, note: i.value})}).catch(() => null);
    i.classList.toggle("saved", !!r && !r.error); }));
}
function log() {
  const el = $("nwLog"), Lg = D.P && D.P.log;
  if (!Lg) { el.innerHTML = `<div class="state">${D.loaded ? "The log is unavailable." : "Reading your fills…"}</div>`; return; }
  if (Lg.error) { el.innerHTML = `<div class="state">${esc(Lg.error)}</div>`; return; }
  const dd = D.P.drawdown || {}, names = Object.keys(dd).filter((k) => k !== "error");
  const tiles = `<div class="kv mini"><div><span class="lbl">Rules followed</span><b>${Lg.planned} of ${Lg.n}</b><span class="small muted">decisions since ${day(Lg.since)}</span></div>
    ${names.map((a) => `<div><span class="lbl">${esc(a)} from its peak</span><b class="${dd[a].now < -0.05 ? "neg" : ""}">${pctS(dd[a].now)}</b><span class="small muted">deepest ${pctS(dd[a].worst)}</span></div>`).join("")}</div>`;
  const rows = Lg.rows.slice(0, 5);
  el.innerHTML = `${tiles}${rows.length ? `<div class="tbl"><table><tbody>${logRows(rows, true)}</tbody></table></div>` : `<div class="state">No decisions scored yet.</div>`}
    <p class="small muted">Read from your fills in ONE against the rules in force that day. Nothing to fill in; the one-line note is optional and for the weekend. ${go("pnl", "Scoreboard", "Scoreboard")}</p>`;
  bindNotes(el);
}

function render() { canOpen(); hold(); limits(); read(); log(); }

async function load() {
  if (!$("nwOpen")) return;
  D = {}; render();
  $("nwWhen").textContent = new Date().toLocaleString([], {weekday: "long", day: "numeric", month: "short", hour: "numeric", minute: "2-digit"});
  const [Rk, Rd] = await Promise.all([window.riskActions ? window.riskActions().catch(() => null) : null, api("/api/readiness").catch(() => null)]);
  D.Rk = Rk; D.Rd = Rd; D.loaded = true; render();
  if (window.renderHeads && window.loadHeads) window.loadHeads().then(() => window.renderHeads(Rk)).catch(() => {});
  api("/api/process").catch(() => null).then((P) => { D.P = P; read(); log(); });  // after readiness, so the desk's read has its odds
  api("/api/a14/rules").catch(() => ({error: "A14 rules unavailable"})).then((d) => { D.LAD = d; canOpen(); });
}
window.loadNow = load;
document.addEventListener("click", (e) => { if (e.target.closest("#nwReload")) { if (window.riskStale) window.riskStale(); load(); } });

/* ---------- Rules: every rule in one list, with what it is, why it is there and who set it (desk/rulebook.py) ---------- */
let RB = null;
function rules() {
  const el = $("rbBody"); if (!el || !RB) return;
  if (RB.error) { el.innerHTML = `<div class="state">${esc(RB.error)}</div>`; return; }
  const q = ($("rbFind").value || "").trim().toLowerCase(), hit = (r) => !q || [r.name, r.rule, r.what, r.why, r.who].join(" ").toLowerCase().includes(q);
  let n = 0;
  el.innerHTML = RB.sections.map((s) => { const R = s.rules.filter(hit); n += R.length; if (!R.length) return "";
    return `<div class="rbsec"><h2>${esc(s.title)}</h2><p class="small">${esc(s.note || "")}</p><div class="rbgrid">${R.map((r) => `<div class="rbcard"><h3>${esc(r.name)}</h3>
      <p class="rbrule">${esc(r.rule)}</p><p><span>What it means:</span> ${esc(r.what)}</p><p><span>Why it's there:</span> ${esc(r.why)}</p>
      <div class="rbwho"><span>Set by: ${esc(r.who)}</span><span>${esc(r.where || "")}</span></div></div>`).join("")}</div></div>`; }).join("") || `<div class="state">No rule matches "${esc(q)}".</div>`;
  $("rbMeta").textContent = `${n} rule${n === 1 ? "" : "s"} · numbers read from the live settings · reference only`;
}
let LC = null;
function limitsEdit() {
  const el = $("rbLimBody"); if (!el) return;
  if (!LC || LC.error || !LC.values) { $("rbLimits").hidden = true; return; }
  $("rbLimits").hidden = false;
  const RO = !!window.DESK_CLOUD, one = (v) => v && typeof v === "object" ? Math.max(...Object.values(v)) : v;
  const HELP = {"cap:A14": "every open A14 id at its worst case, added up", "cap:F49": "every open F49 id at its worst case, added up", "cap:total": "every open trade of every strategy at its worst case, added up",
    "ids:A14": "open ids per ticker and account, separate from the NAV cap",
    stress: `the whole book on a ${fmt(LC.move, 0)}% day either way, with volatility moving with it`};
  const wait = Object.fromEntries((LC.pending || []).map((p) => [p.key, p]));
  const cell = (k) => { const v = one(LC.values[k]), p = wait[k];
    return `<div><span class="lbl">${esc(LC.names[k])}</span><span class="row" style="gap:4px"><input type="number" class="rbnum" data-key="${k}" value="${ok(v) ? v : ""}" placeholder="not set" min="1" max="100" step="${k === "ids:A14" ? 1 : 0.5}" style="width:84px"${RO ? " disabled" : ""}> <b>${k === "ids:A14" ? "ids" : "%"}</b></span>
      <span class="small muted">${esc(HELP[k])}</span>${p ? `<span class="small wrn">${ok(p.new) ? `${p.new}${k === "ids:A14" ? " ids" : "%"}` : "no limit"} from ${day(p.effective)}</span>` : ""}</div>`; };
  const txt = (v, k) => ok(v) ? `${v}${k === "ids:A14" ? " ids" : "%"}` : "not set";
  el.innerHTML = `<div class="kv mini">${Object.keys(LC.names).map(cell).join("")}</div><div id="rbLimMsg" class="small"></div>
    <p class="small muted">${RO ? "Limits are changed on the laptop desk: this copy can't save. " : "Type a number and press Enter; clear the box to remove a limit. "}A tighter limit applies at once. A looser one, or removing one, applies from the next US session, so a cap can't be raised in the minute you want to open a trade. The stress limit covers the whole book because a 5% day hits every strategy at once.</p>
    ${(LC.log || []).length ? `<details><summary class="small">Changes made (${LC.log.length})</summary><div class="tbl"><table><tbody>${LC.log.map((r) => `<tr><td class="small">${new Date(r.made).toLocaleString([], {day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})}</td><td>${esc(LC.names[r.key] || r.key)}</td><td class="mono">${txt(r.old, r.key)} → ${txt(r.new, r.key)}</td><td class="small muted">in force from ${day(r.effective)}</td></tr>`).join("")}</tbody></table></div></details>` : ""}`;
  el.querySelectorAll(".rbnum").forEach((i) => i.addEventListener("change", async () => {
    const r = await api("/api/limits", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key: i.dataset.key, value: i.value === "" ? null : +i.value})}).catch(() => ({error: "Could not save."}));
    if (r.error) { $("rbLimMsg").innerHTML = `<span class="neg">${esc(r.error)}</span>`; return; }
    LC = r; limitsEdit(); if (window.riskStale) window.riskStale();
    RB = await api("/api/rulebook").catch(() => RB); rules(); }));
}
window.loadRules = async () => { [RB, LC] = await Promise.all([api("/api/rulebook").catch(() => ({error: "Rules unavailable"})), api("/api/limits").catch(() => null)]); limitsEdit(); rules(); };
document.addEventListener("input", (e) => { if (e.target.id === "rbFind") rules(); });

/* ---------- Detail switch: the other tabs stay, out of the way until wanted ---------- */
const DK = "od.detail";
function setDetail(on) {
  document.body.classList.toggle("simple", !on);
  const b = $("detailBtn"); if (b) { b.textContent = on ? "Hide detail" : "Show detail"; b.setAttribute("aria-pressed", String(on)); }
  try { localStorage.setItem(DK, on ? "1" : "0"); } catch (e) {}
}
let detail = false; try { detail = localStorage.getItem(DK) === "1"; } catch (e) {}
const CLOUD = !!window.DESK_CLOUD;
if (CLOUD) {  // the cloud copy answers Now and Rules from your encrypted snapshot: hidden until it is unlocked, and nothing can be saved there
  const tabs = ["now", "rules"].map((t) => document.querySelector(`.tabs button[data-tab="${t}"]`)).filter(Boolean), d = $("detailBtn");
  detail = true; tabs.forEach((b) => { b.style.display = "none"; }); if (d) d.style.display = "none";
  window.addEventListener("load", () => api("/api/rulebook").then((r) => { if (r && r.sections) { tabs.forEach((b) => { b.style.display = ""; }); if (d) d.style.display = ""; } }).catch(() => {}));
}
setDetail(detail);
document.addEventListener("click", (e) => { if (e.target.closest("#detailBtn")) setDetail(document.body.classList.contains("simple")); });

/* ---------- Process scoreboard (P&L): drawdown, rules followed, the reads. No profit target. ---------- */
window.renderProcess = async function (el) {
  if (!el) return;
  el.innerHTML = `<div class="state loading">Reading your fills…</div>`;
  const P = await api("/api/process").catch(() => null);
  if (!P || P.error) { el.innerHTML = `<div class="state">${esc((P && P.error) || "Scoreboard unavailable.")}</div>`; return; }
  const dd = P.drawdown || {}, names = Object.keys(dd).filter((k) => k !== "error"), Lg = P.log, C = P.calls, S = C.score;
  const rate = (h, n) => n ? `${h} of ${n}` : "–";
  el.innerHTML = `<div class="kv mini"><div><span class="lbl">Rules followed</span><b>${Lg.planned} of ${Lg.n}</b><span class="small muted">decisions since ${day(Lg.since || P.from)}</span></div>
      ${names.map((a) => `<div><span class="lbl">${esc(a)} from its peak</span><b class="${dd[a].now < -0.05 ? "neg" : ""}">${pctS(dd[a].now)}</b><span class="small muted">deepest ${pctS(dd[a].worst)} in ${dd[a].weeks} weeks</span></div>`).join("")}
      <div><span class="lbl">Your reads</span><b>${rate(S.mine, S.mine_n)}</b><span class="small muted">desk ${rate(S.app, S.app_n)} · always quiet ${rate(S.quiet, S.n)}</span></div></div>
    <div class="acctgrid">${names.map((a, k) => `<div><h3>${esc(a)}</h3><div class="chart" id="psDd${k}"></div></div>`).join("")}</div>
    <h3 style="margin:12px 0 6px">Every decision against the rules</h3>
    ${Lg.rows.length ? `<div class="tbl"><table><thead><tr><th>When</th><th>Trade</th><th>Verdict</th><th>How it differed</th><th>Your note</th></tr></thead><tbody>${logRows(Lg.rows, true)}</tbody></table></div>` : `<div class="state">${esc(Lg.error || "No decisions scored yet.")}</div>`}
    <h3 style="margin:12px 0 6px">Your reads of the week ahead</h3>
    ${C.rows.length ? `<div class="tbl"><table><thead><tr><th>Session</th><th>You</th><th>Desk</th><th class="n">SPX worst close after</th><th>The week was</th></tr></thead><tbody>${C.rows.map((r) => `<tr><td>${day(r.date)}</td>
      <td>${r.mine ? CALL[r.mine][0] : "–"}</td><td>${r.app ? CALL[r.app][0] : "–"}</td><td class="n ${cls(r.worst)}">${pctS(r.worst, 2)}${r.outcome ? "" : ` <span class="small muted">${r.seen} of ${C.defs.ahead} sessions</span>`}</td>
      <td>${r.outcome ? `<span class="chip ${CALL[r.outcome][1]}">${CALL[r.outcome][0]}</span>${r.mine ? (r.mine === r.outcome ? " ✓" : " ✗") : ""}` : `<span class="small muted">pending</span>`}</td></tr>`).join("")}</tbody></table></div>` : `<div class="state">No reads yet: the Now screen asks once a day.</div>`}
    <p class="note">This replaces the 1%-a-week target. It scores what you control: staying inside your limits and rules, and how well you read the week ahead, against the desk and against always saying "quiet" (${C.base ? C.base.quiet : "about half"}% of weeks since 1990). Drawdown is each account's fall from its own peak on weekly NAV change, deposits and withdrawals taken out. Your limits: all A14 worst cases under ${ok(P.limits.cap_pct) ? P.limits.cap_pct + "%" : "–"} of NAV, a 5% day under ${ok(P.limits.limit_pct) ? P.limits.limit_pct + "%" : "–"}.</p>`;
  names.forEach((a, k) => lineChart($(`psDd${k}`), {h: 150, label: `${a} fall from peak, %`, refs: [{y: 0}], fy: (v) => `${v}%`, endLabels: false,
    series: [{name: "From peak", color: "var(--down)", width: 2, data: dd[a].series}]}));
  bindNotes(el);
};
})();
