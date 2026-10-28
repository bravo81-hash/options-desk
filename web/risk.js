/* Risk-graph grid: every open ONE trade repriced with Black-Scholes at its legs' own IVs. */
"use strict";
(() => {
const oneStale = (R) => { const f = R.one_fresh; if (!f || !f.stale) return "";
  return `<div class="state err" style="margin-bottom:6px"><b>ONE export is ${f.age_h != null ? Math.round(f.age_h) + "h old" : "missing"}${f.fills_since ? ` and IBKR has ${f.fills_since} fill${f.fills_since > 1 ? "s" : ""} since` : ""}</b> — differences below may just be trades not yet in the report. Export a fresh ONE Summary Report, then reload.</div>`; };
const $ = (id) => document.getElementById(id);
const MULT = 100, DAY = 86400000;
let R = null, sel = null;

/* ---------- pricing ---------- */
function ncdf(x) { // Abramowitz-Stegun 7.1.26 via erf
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x / 2);
  return 0.5 * (1 + (x >= 0 ? y : -y));
}
function bs(S, K, T, v, right) {
  if (T <= 0 || v <= 0) return Math.max(0, right === "C" ? S - K : K - S);
  const sd = v * Math.sqrt(T), d1 = (Math.log(S / K) + 0.5 * sd * sd) / sd, d2 = d1 - sd;
  return right === "C" ? S * ncdf(d1) - K * ncdf(d2) : K * ncdf(-d2) - S * ncdf(-d1);
}
const now = () => Date.now();
function prep(t) { // per-leg IV fallback: same-expiry average, then 20%
  const byExp = {};
  t.legs.forEach((l) => { const iv = l.mark && l.mark.iv; if (ok(iv) && iv > 0.01 && iv < 3) (byExp[l.expiry_iso] = byExp[l.expiry_iso] || []).push(iv); });
  t.legs.forEach((l) => {
    const iv = l.mark && l.mark.iv;
    const alt = byExp[l.expiry_iso] ? byExp[l.expiry_iso].reduce((a, b) => a + b, 0) / byExp[l.expiry_iso].length : 0.2;
    l.vol = ok(iv) && iv > 0.01 && iv < 3 ? iv : alt;
    l.expMs = Date.parse(l.expiry_iso);
    l.mid = l.mark && ok(l.mark.mid) ? l.mark.mid : null;
  });
  t.firstExp = Math.min(...t.legs.map((l) => l.expMs));
  t.model0 = t.legs.reduce((s, l) => s + l.qty * MULT * bs(t.spot, l.strike, Math.max(0, (l.expMs - now()) / (365 * DAY)), l.vol, l.right), 0);
  t.unreal = t.legs.reduce((s, l) => s + (l.mid == null ? 0 : l.qty * MULT * (l.mid - l.open_price)), 0);
  t.pnlNow = (t.one_pnl || 0) + t.unreal;
  t.marked = t.legs.every((l) => l.mid != null);
  const closes = t.legs.every((l) => l.mid != null && l.mark && ok(l.mark.close));
  t.dayChg = closes ? t.legs.reduce((s, l) => s + l.qty * MULT * (l.mid - l.mark.close), 0) : null;
  t.totalPct = t.margin ? 100 * t.pnlNow / t.margin : null;
  t.dayPct = t.margin && ok(t.dayChg) ? 100 * t.dayChg / t.margin : null;
  t.openedMs = t.opened_iso ? Date.parse(t.opened_iso) : null;
  t.ditNow = t.openedMs ? Math.floor((now() - t.openedMs) / DAY) : t.dit;
  t.lastExp = Math.max(...t.legs.map((l) => l.expMs));
  const held = Math.max(t.ditNow || 0, 1);
  t.perDay = ok(t.totalPct) ? t.totalPct / held : null;       // % of margin per day held
  t.dollarDay = ok(t.pnlNow) ? t.pnlNow / held : null;
  t.entryDte = t.openedMs ? Math.round((etDay(t.firstExp) - etDay(t.openedMs)) / DAY) : null;
}
function value(t, S, atMs, dv) {
  return t.legs.reduce((s, l) => s + l.qty * MULT * bs(S, l.strike, Math.max(0, (l.expMs - atMs) / (365 * DAY)), Math.max(0.01, l.vol + dv), l.right), 0);
}
const pnlAt = (t, S, atMs, dv) => t.pnlNow + value(t, S, atMs, dv) - t.model0;
function greeks(t) {
  const S = t.spot, n = now(), h = S * 0.001;
  const v0 = value(t, S, n, 0), up = value(t, S + h, n, 0), dn = value(t, S - h, n, 0);
  return {delta: (up - dn) / (2 * h), gamma: (up - 2 * v0 + dn) / (h * h), theta: value(t, S, n + DAY, 0) - v0,
          vega: (value(t, S, n, 0.01) - v0), dollarDelta1pct: (up - dn) / (2 * h) * S * 0.01};
}

/* ---------- chart ---------- */
function riskChart(el, cfg) {
  mount(el, (W) => {
    const H = cfg.h || 160, mL = 50, mR = 10, mT = 8, mB = 20, pw = W - mL - mR, ph = H - mT - mB;
    const xs = cfg.xs, ys = cfg.series.filter((s) => s.scale !== false).flatMap((s) => s.ys).filter(ok).concat(ok(cfg.nowPnl) ? [cfg.nowPnl] : []);
    let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys); const pad = (hi - lo) * 0.08 || 100; lo -= pad; hi += pad;
    const X = (x) => mL + (x - xs[0]) * pw / (xs[xs.length - 1] - xs[0]), Y = (v) => mT + ph - (v - lo) * ph / (hi - lo);
    const fk = (v) => Math.abs(v) >= 1000 ? (v / 1000).toFixed(Math.abs(v) >= 10000 ? 0 : 1) + "k" : Math.round(v);
    const cid = "clip" + Math.random().toString(36).slice(2, 8);
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(cfg.label || "risk graph")}"><defs><clipPath id="${cid}"><rect x="${mL}" y="${mT}" width="${pw}" height="${ph}"/></clipPath></defs>`;
    // profit / loss tint under the dated curve
    niceTicks(lo, hi, cfg.ticks || 4).forEach((v) => { if (v >= lo && v <= hi) s += `<line x1="${mL}" x2="${mL + pw}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="${v === 0 ? "var(--faint)" : "var(--grid)"}"/><text x="${mL - 5}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${fk(v)}</text>`; });
    niceTicks(xs[0], xs[xs.length - 1], Math.max(2, Math.floor(pw / 70))).forEach((v) => { if (v >= xs[0] && v <= xs[xs.length - 1]) s += `<text x="${X(v).toFixed(1)}" y="${H - 5}" text-anchor="middle">${cfg.fx ? cfg.fx(v) : v}</text>`; });
    (cfg.bands || []).forEach(([a, b]) => { const xa = X(Math.max(a, xs[0])), xb = X(Math.min(b, xs[xs.length - 1])); if (xb > xa) s += `<rect x="${xa.toFixed(1)}" y="${mT}" width="${(xb - xa).toFixed(1)}" height="${ph}" fill="var(--s1)" opacity=".07"/>`; });
    if (ok(cfg.spot)) s += `<line x1="${X(cfg.spot).toFixed(1)}" x2="${X(cfg.spot).toFixed(1)}" y1="${mT}" y2="${mT + ph}" stroke="var(--accent)" stroke-dasharray="3 3"/>`;
    cfg.series.forEach((se) => {
      let d = ""; se.ys.forEach((y, i) => { if (ok(y)) d += (d ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(y).toFixed(1); });
      if (se.fill) { s += `<path d="${d}L${X(xs[xs.length - 1]).toFixed(1)} ${Y(0).toFixed(1)}L${X(xs[0]).toFixed(1)} ${Y(0).toFixed(1)}Z" fill="${se.color}" opacity=".08"/>`; }
      s += `<path d="${d}" clip-path="url(#${cid})" fill="none" stroke="${se.color}" stroke-width="${se.width || 1.8}" ${se.dash ? `stroke-dasharray="${se.dash}"` : ""} stroke-linejoin="round"/>`;
    });
    if (ok(cfg.nowPnl) && ok(cfg.spot)) s += `<circle cx="${X(cfg.spot).toFixed(1)}" cy="${Y(cfg.nowPnl).toFixed(1)}" r="4" fill="var(--accent)" stroke="var(--panel)" stroke-width="2"/>`;
    s += `<line class="xh" x1="0" x2="0" y1="${mT}" y2="${mT + ph}" stroke="var(--muted)" visibility="hidden"/><rect class="hit" x="${mL}" y="${mT}" width="${pw}" height="${ph}" fill="transparent"/></svg>`;
    el.innerHTML = s;
    const svg = el.firstChild, xh = svg.querySelector(".xh"), hit = svg.querySelector(".hit");
    const mv = (ev) => { const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(xs.length - 1, Math.round((ev.clientX - r.left - mL) / pw * (xs.length - 1))));
      xh.setAttribute("x1", X(xs[i])); xh.setAttribute("x2", X(xs[i])); xh.setAttribute("visibility", "visible");
      showTip(`<div>${esc(cfg.fx ? cfg.fx(xs[i], true) : xs[i])}</div>` + cfg.series.map((se) => `<div><span class="sw" style="background:${se.color}"></span>${esc(se.name)} <b>${ok(se.ys[i]) ? Math.round(se.ys[i]).toLocaleString() : "–"}</b></div>`).join(""), ev.clientX, ev.clientY); };
    hit.addEventListener("pointermove", mv); hit.addEventListener("pointerdown", mv); hit.addEventListener("pointerleave", () => { xh.setAttribute("visibility", "hidden"); hideTip(); });
  });
}

/* ---------- controls ---------- */
const ctl = () => ({days: +$("rkDays").value, dv: +$("rkVol").value / 100, range: +$("rkRange").value / 100, beta: +$("rkBeta").value || 1, acct: $("rkAcct").value});
const money = (v) => ok(v) ? (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString() : "–";
const cls = (v) => !ok(v) ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
function curves(t, c, xsPct) {
  const at = now() + c.days * DAY, exp = t.firstExp;
  return {
    today: xsPct.map((x) => pnlAt(t, t.spot * (1 + x * t.beta), now(), c.dv)),
    dated: xsPct.map((x) => pnlAt(t, t.spot * (1 + x * t.beta), Math.min(at, exp), c.dv)),
    expiry: xsPct.map((x) => pnlAt(t, t.spot * (1 + x * t.beta), exp, c.dv)),
  };
}
const COL = {today: "var(--s1)", dated: "var(--accent)", expiry: "var(--faint)"};
const pctS = (v) => ok(v) ? `${v > 0 ? "+" : ""}${v.toFixed(1)}%` : "–";
const dshort = (ms) => ok(ms) ? new Date(ms).toLocaleDateString([], {day: "numeric", month: "short"}) : "–";
const dexp = (ms) => ok(ms) ? new Date(ms).toLocaleDateString([], {day: "numeric", month: "short", timeZone: "America/New_York"}) : "–"; // expiries are US dates
const etDay = (ms) => { const p = new Intl.DateTimeFormat("en-CA", {timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date(ms)); return Date.parse(p + "T00:00:00Z"); };
const dteOf = (ms) => Math.max(0, Math.round((etDay(ms) - etDay(now())) / DAY)); // calendar days, US date, like OptionStrat
const dteTxt = (t) => t.lastExp > t.firstExp + DAY ? `${dteOf(t.firstExp)}d / ${dteOf(t.lastExp)}d` : `${dteOf(t.firstExp)}d`;
let tSort = {k: "firstExp", dir: 1};
const mktOpen = () => { const p = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "numeric", hour12: false}).formatToParts(new Date());
  const g = (t) => (p.find((x) => x.type === t) || {}).value, h = +g("hour"), m = +g("minute"), wd = g("weekday");
  return !["Sat", "Sun"].includes(wd) && (h * 60 + m) >= 570 && (h * 60 + m) < 960; };
function tradesTable(T) {
  const cols = [["name", "Trade"], ["acct", "Account"], ["pnlNow", "Total return", 1], ["totalPct", "Total %", 1], ["perDay", "% / day", 1], ["paceNow", "Pace now", 1], ["planPri", "Plan", 1], ["dollarDay", "$ / day", 1], ["dayChg", "Today's return", 1], ["dayPct", "Today %", 1],
    ["openedMs", "Opened", 1], ["ditNow", "Days in trade", 1], ["firstExp", "Days to expiry", 1], ["margin", "Margin", 1]];
  T.forEach((t) => { t.acct = label(t); });
  const s = tSort, rows = [...T].sort((a, b) => { const x = a[s.k], y = b[s.k]; if (!ok(x) && typeof x !== "string") return 1; if (!ok(y) && typeof y !== "string") return -1;
    return typeof x === "string" ? (s.dir < 0 ? y.localeCompare(x) : x.localeCompare(y)) : (s.dir < 0 ? y - x : x - y); });
  const tot = (k) => T.reduce((a, t) => a + (ok(t[k]) ? t[k] : 0), 0), mg = tot("margin");
  return `<div class="tbl"><table><thead><tr>${cols.map(([k, l, n]) => `<th class="sort ${n ? "n" : ""}" tabindex="0" data-k="${k}" ${s.k === k ? `aria-sort="${s.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${s.k === k ? (s.dir < 0 ? " ▾" : " ▴") : ""}</th>`).join("")}</tr></thead><tbody>${
    rows.map((t) => `<tr class="click" tabindex="0" data-id="${esc(t.id)}"><td>${esc(t.name)}</td><td>${esc(t.acct)}</td>
      <td class="n ${cls(t.pnlNow)}">${money(t.pnlNow)}</td><td class="n ${cls(t.totalPct)}">${hBarSvg(t.totalPct, 10, {w: 60, label: "total % of margin (full bar = 10%)"})} ${pctS(t.totalPct)}</td>
      <td class="n ${cls(t.perDay)}" title="total return ÷ ${Math.max(t.ditNow || 0, 1)} days in trade">${ok(t.perDay) ? fmt(t.perDay, 2) + "%" : "–"}</td><td class="n" title="theta/day at today's IVs ÷ margin: what it earns from here">${ok(t.paceNow) ? fmt(t.paceNow, 2) + "% " + speedChip(t) : "–"}</td><td>${planChip(t)}</td><td class="n ${cls(t.dollarDay)}">${money(t.dollarDay)}</td>
      <td class="n ${cls(t.dayChg)}">${money(t.dayChg)}</td><td class="n ${cls(t.dayPct)}">${pctS(t.dayPct)}</td>
      <td class="n">${dshort(t.openedMs)}</td><td class="n">${t.ditNow ?? "–"}</td><td class="n" title="${esc(dexp(t.firstExp) + (t.lastExp > t.firstExp + DAY ? " / " + dexp(t.lastExp) : ""))}">${dteTxt(t)}</td><td class="n">${money(t.margin)}</td></tr>`).join("")}
    <tr><td><b>Total</b></td><td></td><td class="n ${cls(tot("pnlNow"))}"><b>${money(tot("pnlNow"))}</b></td><td class="n">${mg ? pctS(100 * tot("pnlNow") / mg) : "–"}</td>
      <td class="n" title="book: total $ per day ÷ total margin">${mg ? fmt(100 * tot("dollarDay") / mg, 2) + "%" : "–"}</td><td class="n" title="book: theta/day ÷ margin">${mg ? fmt(T.reduce((a, t) => a + (ok(t.paceNow) ? t.paceNow * (t.margin || 0) : 0), 0) / mg, 2) + "%" : "–"}</td><td></td><td class="n"><b>${money(tot("dollarDay"))}</b></td>
      <td class="n ${cls(tot("dayChg"))}"><b>${money(tot("dayChg"))}</b></td><td class="n">${mg ? pctS(100 * tot("dayChg") / mg) : "–"}</td><td></td><td></td><td></td><td class="n">${money(mg)}</td></tr></tbody></table></div>`;
}
function label(t) { return R.labels[t.ib_account] || t.group; }

/* ---------- capital use: margin and days tied up, by DTE at entry ---------- */
const BUCKETS = [[0, 21, "≤21"], [22, 45, "22–45"], [46, 70, "46–70"], [71, 9999, "71+"]];
const bucketOf = (d) => ok(d) ? (BUCKETS.find(([lo, hi]) => d >= lo && d <= hi) || [])[2] : null;
const SPEED = () => (STATS && STATS.speed) || {target: 0.4, slow: 0.2, source: "default"};
// pace now = what the trade earns from here: theta $/day at today's IVs ÷ margin; usual hold = your closed A14s with that entry DTE
function paceOf(t) {
  t.paceNow = t.margin ? 100 * greeks(t).theta / t.margin : null;
  const b = STATS && STATS.by_dte && STATS.by_dte[bucketOf(t.entryDte)];
  t.usualHold = b ? b.dit : null;
  t.overstay = ok(t.usualHold) && ok(t.ditNow) && t.ditNow > 1.25 * t.usualHold;
  const sp = SPEED();
  // slow from here (theta) or slow so far (3+ weeks in, realised return per day under half the target: theta has not been turning into P&L)
  t.slowHere = ok(t.paceNow) && t.paceNow < sp.slow;
  t.slowSoFar = ok(t.perDay) && (t.ditNow || 0) >= 21 && t.perDay < sp.slow;
  t.speed = !ok(t.paceNow) ? null : t.slowHere || t.slowSoFar ? "slow" : t.paceNow >= sp.target && !(ok(t.perDay) && (t.ditNow || 0) >= 21 && t.perDay < sp.target) ? "fast" : "ok";
  const best = Math.max(t.paceNow ?? -1e9, (t.ditNow || 0) >= 21 ? t.perDay ?? -1e9 : -1e9);
  t.gapDay = t.margin && ok(t.paceNow) ? t.margin * Math.max(sp.target - best, 0) / 100 : null;
}
const speedChip = (t) => t.speed === "fast" ? `<span class="chip pos">fast</span>` : t.speed === "slow" ? `<span class="chip neg" title="${t.slowHere ? "theta from here is under half your target" : "3+ weeks in and the realised return per day is under half your target"}">slow${t.slowHere ? "" : " so far"}</span>` : "";
function capitalView(T) {
  const mgAll = T.reduce((a, t) => a + (t.margin || 0), 0) || 1, bench = (STATS && STATS.by_dte) || {}, sp = SPEED();
  const thetaAll = T.reduce((a, t) => a + (ok(t.paceNow) ? t.paceNow * (t.margin || 0) / 100 : 0), 0);
  const bookPace = 100 * thetaAll / mgAll;
  const slowT = T.filter((t) => t.speed === "slow"), slowMg = slowT.reduce((a, t) => a + (t.margin || 0), 0);
  const gap = T.reduce((a, t) => a + Math.max(t.gapDay || 0, 0), 0);
  const tile = (l, b, sub, k = "") => `<div><span class="lbl">${l}</span><b class="${k}">${b}</b><span class="small muted">${sub}</span></div>`;
  const head = `<div class="kv mini" style="margin-bottom:10px">${tile("Book pace now", fmt(bookPace, 2) + "% / day", `theta ${money(thetaAll)}/day on ${money(mgAll)} margin`, bookPace >= sp.target ? "pos" : bookPace < sp.slow ? "neg" : "wrn")}
    ${tile("Your pace target", fmt(sp.target, 2) + "% / day", esc(sp.source) + ` · slow = under ${fmt(sp.slow, 2)}%`)}
    ${tile("Margin in slow trades", money(slowMg), `${Math.round(100 * slowMg / mgAll)}% of margin · ${slowT.length} trades`, slowMg / mgAll > 0.5 ? "neg" : "")}
    ${tile("Gap to target", money(gap) + " / day", "what the slower trades' margin would add per day at your target pace", gap > 0 ? "wrn" : "pos")}</div>`;
  const rows = BUCKETS.map(([lo, hi, lab]) => {
    const tt = T.filter((t) => ok(t.entryDte) && t.entryDte >= lo && t.entryDte <= hi);
    if (!tt.length) return "";
    const mg = tt.reduce((a, t) => a + (t.margin || 0), 0), pnl = tt.reduce((a, t) => a + (t.pnlNow || 0), 0);
    const dd = tt.reduce((a, t) => a + (t.dollarDay || 0), 0), days = tt.reduce((a, t) => a + Math.max(t.ditNow || 0, 1), 0) / tt.length;
    const th = tt.reduce((a, t) => a + (ok(t.paceNow) ? t.paceNow * (t.margin || 0) / 100 : 0), 0);
    const pd = mg ? 100 * dd / mg : null, pn = mg ? 100 * th / mg : null, b = bench[lab];
    return `<tr><td>${lab} DTE</td><td class="n">${tt.length}</td><td class="n">${money(mg)}</td>
      <td><span class="minibar" style="width:120px"><span style="width:${(100 * mg / mgAll).toFixed(0)}%"></span></span><span class="small muted">${Math.round(100 * mg / mgAll)}%</span></td>
      <td class="n ${cls(pnl)}">${money(pnl)}</td><td class="n">${mg ? pctS(100 * pnl / mg) : "–"}</td><td class="n">${Math.round(days)}</td>
      <td class="n ${cls(pd)}"><b>${ok(pd) ? fmt(pd, 2) + "%" : "–"}</b></td><td class="n ${pn >= sp.target ? "pos" : pn < sp.slow ? "neg" : ""}">${ok(pn) ? fmt(pn, 2) + "%" : "–"}</td>
      <td class="n muted">${b ? `${fmt(b.per_day, 2)}% <span class="small">(n ${b.n}, ${Math.round(b.dit)}d)</span>` : "–"}</td></tr>`;
  }).join("");
  // slow trades: earning under half the target from here, largest gap to target first
  const slow = T.filter((t) => t.speed === "slow" && t.margin).sort((a, b) => (b.gapDay || 0) - (a.gapDay || 0)).slice(0, 10);
  return head + `<div class="tbl"><table><thead><tr><th>Entry DTE</th><th class="n">Trades</th><th class="n">Margin</th><th>Share of margin</th><th class="n">P&amp;L now</th><th class="n">Return</th><th class="n">Avg days held</th>
    <th class="n" title="so far: $ per day held ÷ margin">Return / day so far</th><th class="n" title="from here: theta $/day at today's IVs ÷ margin">Pace now</th><th class="n" title="your closed A14 trades in ONE with the same entry DTE">Closed A14s / day</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h3 style="margin:14px 0 6px">Slow capital: under ${fmt(sp.slow, 2)}% a day from here, or so far after 3+ weeks <span class="small muted">(largest gap to your ${fmt(sp.target, 2)}%/day target first)</span></h3>
    ${slow.length ? `<div class="tbl"><table><thead><tr><th>Trade</th><th class="n">Entry DTE</th><th class="n">Margin</th><th class="n">Days held</th><th class="n">Total</th><th class="n">% / day so far</th><th class="n">Pace now</th><th class="n">Theta / day</th><th class="n" title="margin × target − theta">Gap to target / day</th><th class="n">Days to expiry</th></tr></thead><tbody>${
    slow.map((t) => `<tr class="click" data-id="${esc(t.id)}"><td>${esc(t.name)}${t.overstay ? ` <span class="chip wrn" title="held ${t.ditNow}d vs ${Math.round(t.usualHold)}d for your closed A14s with this entry DTE">past usual hold</span>` : ""}</td><td class="n">${t.entryDte ?? "–"}</td><td class="n">${money(t.margin)}</td>
      <td class="n">${t.ditNow ?? "–"}${ok(t.usualHold) ? ` <span class="small muted">/ ${Math.round(t.usualHold)}</span>` : ""}</td><td class="n ${cls(t.totalPct)}">${pctS(t.totalPct)}</td><td class="n ${t.slowSoFar ? "neg" : cls(t.perDay)}">${fmt(t.perDay, 2)}%</td>
      <td class="n ${t.slowHere ? "neg" : ""}">${fmt(t.paceNow, 2)}%</td><td class="n">${money(t.paceNow * t.margin / 100)}</td><td class="n wrn">${money(t.gapDay)}</td><td class="n">${dteTxt(t)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="state">No open trade is earning under ${fmt(sp.slow, 2)}% a day from here.</div>`}
    <p class="note">Pace now = theta per day at today's IVs ÷ ONE margin: what the trade earns from here if nothing moves. % / day so far = realised and open P&amp;L ÷ margin ÷ days held; a trade 3+ weeks in with that under half the target is flagged <i>slow so far</i> even if theta looks fine, because moves and adjustments have been eating the decay. Gap to target uses the better of the two paces. It changes with the market (theta grows near expiry; adjustments reset it). A slow trade is a question, not an instruction: would that margin earn more in a fresh 14–45 DTE A14 (check the A14 scanner's <i>fast</i> rows and the readiness bar for size)? Longer-dated trades also carry less gamma risk. "Past usual hold" = held 25% longer than your closed A14s with the same entry DTE.</p>`;
}


/* ---------- trade plan: TP / SL / time / adjust gates from your ONE history (A14: 56 closed trades, 365 adjustments) ---------- */
// all levels are % of ONE margin; adjust: "gated" = the gates in planOf, "one" = the card's one adjustment then exit, "never"
// A14 stop: −20 (was the card's −10). In the 2009–2026 model backtest (Evidence → Since 2009) −10 was hit in 28–46% of
// A14s (14–60 DTE), mostly on VIX pops that later reverted, and cost more than it saved at every SPX entry DTE from 14 to 60.
const CARDS = {
  A14: {tp: (t) => (t.entryDte <= 21 ? 5 : 7), decide: -6, stop: -20, timeDte: 2, adjust: "gated", pace: true, holdPastDecide: true},
  Allantis: {tp: () => 7, decide: -6, stop: -10, timeDte: 2, adjust: "gated", pace: true},
  HV7: {tp: () => 5, stop: -10, timeDte: 2, adjust: "never"},
  TimeEdge: {tp: () => 5, stop: -15, timeDte: 1, adjust: "one"},
  "Triple Cal": {tp: () => 5, stop: -15, timeDte: 1, adjust: "one"},
  TimeZone: {tp: () => 5, stop: -5, timeDte: 7, adjust: "one"},
  Flyagonal: {tp: () => 10, timeFrac: 2 / 3, adjust: "one"},
};
const PRI = {exit: 0, close: 1, decide: 2, slow: 3, hold: 4};
/* ---------- execution aids: the combo price that closes a trade at a given total, and the index level where it gets there ---------- */
const COMM_SIDE = 1.36, TICK = 0.05;
const gcdAll = (a) => a.reduce((g, x) => { let p = Math.abs(g), q = Math.abs(x); while (q) [p, q] = [q, p % q]; return p; }, 0) || 1;
function closeAt(t, pct) {
  // closing nets one_pnl + (V − Σ qty·100·open) − commissions; solve for the position value V at a total of pct % of margin.
  // Depends only on ONE P&L and the open legs, so it stays valid until the trade is adjusted.
  if (!ok(t.margin) || !ok(pct) || t.legs.some((l) => !ok(l.open_price))) return null;
  const g = gcdAll(t.legs.map((l) => l.qty));
  const basis = t.legs.reduce((a, l) => a + l.qty * MULT * l.open_price, 0);
  const comm = t.legs.reduce((a, l) => a + Math.abs(l.qty), 0) * COMM_SIDE;
  const V = t.margin * pct / 100 - (t.one_pnl || 0) + basis + comm;
  const raw = V / (g * MULT), sell = raw >= 0;
  // round so the fill is at least as good as the level: sell limits up, buy limits down
  const px = sell ? Math.ceil(raw / TICK - 1e-9) * TICK : Math.floor(-raw / TICK + 1e-9) * TICK;
  const now = t.marked ? t.legs.reduce((a, l) => a + l.qty * MULT * l.mid, 0) / (g * MULT) : null;
  const multiExp = new Set(t.legs.map((l) => l.expMs)).size > 1;
  const legs = t.legs.slice().sort((a, b) => a.expMs - b.expMs || b.strike - a.strike)
    .map((l) => `${l.qty / g > 0 ? "+" : ""}${l.qty / g} ${fmt(l.strike, 0)}${l.right}${multiExp ? " " + dexp(l.expMs) : ""}`).join(", ");
  return {side: sell ? "Sell" : "Buy", px, units: g, ratio: legs, nLegs: t.legs.length, total: V, now: ok(now) ? (sell ? now : -now) : null};
}
function levelAt(t, pct, dv = 0) {
  // index close where the trade would be at pct % of margin if the move happened today (IVs + dv, sticky strike); [below, above]
  if (!ok(t.margin) || !ok(t.spot) || !ok(pct) || !ok(t.pnlNow)) return null;
  const goal = t.margin * pct / 100, T0 = now();
  if (t.pnlNow <= goal) return {past: true};
  const f = (S) => pnlAt(t, S, T0, dv) - goal;
  const find = (dir, steps) => { let a = t.spot, fa = f(a);
    for (let k = 1; k <= steps; k++) { const b = t.spot * (1 + dir * 0.0025 * k), fb = f(b); if (fb < 0) return a + (b - a) * fa / (fa - fb); a = b; fa = fb; }
    return null; };
  return {dn: find(-1, 100), up: find(1, 60)};
}
function planOf(t) {
  const c = CARDS[t.strategy];
  t.plan = null; t.planPri = null;
  if (!c || !ok(t.totalPct)) return;
  const p = t.totalPct, dte = dteOf(t.firstExp), tp = c.tp(t), usd = (pct) => money(t.margin * pct / 100);
  const move = ok(t.entry_spot) && ok(t.spot) ? 100 * (t.spot / t.entry_spot - 1) : null;
  const timeHit = ok(c.timeDte) ? dte <= c.timeDte : ok(t.entryDte) && (t.ditNow || 0) >= c.timeFrac * t.entryDte;
  const slow = c.pace && (t.slowSoFar || t.overstay);
  const slowWhy = t.slowSoFar ? `${fmt(t.perDay, 2)}%/day after ${t.ditNow} days, under the ${fmt(SPEED().slow, 2)}% slow line` : `held ${t.ditNow}d vs ${Math.round(t.usualHold)}d usual for this entry DTE`;
  let act, label, why;
  if (ok(c.stop) && p <= c.stop) [act, label, why] = ["exit", "Exit: hard stop", `${pctS(p)} is at or past the ${c.stop}% stop. Exit; no adjustment.`];
  else if (p >= tp) [act, label, why] = ["close", "Close: target", `${pctS(p)} reached the +${tp}% target. Holding 10 more sessions helped only half your exits; +7% targets earned 22% more per margin-day.`];
  else if (timeHit) [act, label, why] = ["close", "Close: time stop", ok(c.timeDte) ? `${dte} DTE: inside the ${c.timeDte} DTE time stop.` : `held ${t.ditNow}d of ${t.entryDte}: past 2/3 of the duration.`];
  else if (slow && p >= 0) [act, label, why] = ["close", "Close: slow, green", `${slowWhy}. Free the margin while it's green.`];
  else if (ok(c.decide) && p <= c.decide) [act, label, why] = ["decide", "Decide today", c.holdPastDecide
    ? `${pctS(p)} is past the ${c.decide}% line: adjust today if the gates pass; if you don't adjust, hold to the ${c.stop}% stop rather than exiting here (since 2009, A14 exits this early cost more than they saved; model).`
    : `${pctS(p)} is past the ${c.decide}% line: adjust today if the gates pass, otherwise exit.`];
  else if (slow) [act, label, why] = ["slow", "Slow: exit at green", `${slowWhy}. Close at the next close at or above 0%; no new adjustments.`];
  else [act, label, why] = ["hold", "Hold", `between ${ok(c.decide) ? c.decide : c.stop ?? "–"}% and +${tp}%: let it work.`];
  // adjustment gate
  let adj, how = "";
  if (c.adjust === "never") adj = {ok: "no", why: "this strategy is never adjusted"};
  else if (c.adjust === "one") adj = !ok(t.adjustments) ? {ok: "?", why: "adjustment count unknown: export a ONE Detail Report"}
    : t.adjustments >= 1 ? {ok: "no", why: `${t.adjustments} adjustment${t.adjustments > 1 ? "s" : ""} made already: the card allows one, so a further breach means exit (backtest: 2+ adjustments cut the average from +8.1% to +0.9%)`}
    : {ok: "one", why: "one adjustment allowed by the card, then exit"};
  else {
    const no = [];
    if (p >= 3) no.push(`up ${pctS(p)}: never adjust a winner (yours at +3 to +6% helped only 36%)`);
    if (p >= 0 && p < 3 && ok(move) && Math.abs(move) < 1.5) no.push(`green and ${t.underlying} only ${pctS(move)} from entry (small-move adjustments helped 44–47%)`);
    if (p >= 0 && p < 3 && !ok(move)) no.push("green, and the entry price is unknown");
    if (ok(c.stop) && p <= c.stop) no.push("past the hard stop");
    if (dte <= c.timeDte) no.push("inside the time stop");
    if (no.length) adj = {ok: "no", why: no.join(" · ")};
    else if (dte <= 10) adj = {ok: "reduce", why: `${dte} DTE: only adjustments that reduce risk; otherwise let the target, stop or time stop decide`};
    else if (dte <= 21) adj = {ok: "roll out", why: `${dte} DTE: inside 10–21, roll out to a new expiry or close; no reshaping (yours there helped 38%)`};
    else adj = {ok: "yes", why: `${p < 0 ? "red" : "moved"}${ok(move) ? `, ${t.underlying} ${pctS(move)} from entry` : ""}, ${dte} DTE`};
    if (adj.ok !== "no") how = ok(move) && move >= 1.5 ? "roll the shorts up or add a call side (+2 to +3% median)"
      : ok(move) && move <= -1.5 && dte > 21 ? "roll out in time (+6% median, 75% helped); don't roll the shorts down (−6%)"
      : "roll out in time or reduce; reshaping in the same expiry is a coin flip";
  }
  t.plan = {act, label, why, pri: PRI[act], tp, decide: c.decide, stop: c.stop, dte, timeDte: c.timeDte, move, adj, how,
    lv: {tp: usd(tp), decide: ok(c.decide) ? usd(c.decide) : null, stop: ok(c.stop) ? usd(c.stop) : null},
    band: ok(t.entry_spot) ? [t.entry_spot * 0.985, t.entry_spot * 1.015] : null,
    order: closeAt(t, tp), at: {decide: ok(c.decide) ? levelAt(t, c.decide) : null, stop: ok(c.stop) ? levelAt(t, c.stop) : null,
      stopIv: ok(c.stop) ? levelAt(t, c.stop, 0.03) : null}, stopPx: ok(c.stop) ? closeAt(t, c.stop) : null};
  t.planPri = t.plan.pri;
}
const PLAN_CLS = {exit: "neg", close: "pos", decide: "neg", slow: "wrn", hold: "muted"};
const planChip = (t) => t.plan ? `<span class="chip ${PLAN_CLS[t.plan.act]}" title="${esc(t.plan.why)}">${esc(t.plan.label)}</span>` : `<span class="small muted" title="no card rules for ${esc(t.strategy || "this trade")}">–</span>`;
const orderTxt = (o, short) => !o ? "–" : `${o.side} ${o.units}× at <b class="mono">${o.px.toFixed(2)}</b>${short ? "" : ` <span class="small muted">combo ${esc(o.ratio)}${ok(o.now) ? ` · now ${o.now.toFixed(2)}` : ""}</span>`}`;
const lvTxt = (L, u) => !L ? "–" : L.past ? "already past" : [L.dn ? `${u} ↓ ${fmt(L.dn, 0)}` : null, L.up ? `↑ ${fmt(L.up, 0)}` : null].filter(Boolean).join(" · ") || "beyond −25% / +15%";
const ADJ_CLS = {yes: "pos", one: "pos", "roll out": "wrn", reduce: "wrn", no: "muted", "?": "muted"};
/* where a trade's total sits between its hard stop and target (decide line dashed) */
function planBullet(t, w = 140) {
  const q = t.plan; if (!q) return "";
  const lo = ok(q.stop) ? q.stop : -10, hi = q.tp || 7;
  return bulletSvg(t.totalPct, {w, lo: lo - 1, hi: hi + 1, label: `${pctS(t.totalPct)} · stop ${q.stop}% · decide ${q.decide ?? "–"}% · target +${q.tp}%`,
    zones: [{from: lo, to: q.decide ?? lo, color: "var(--down)"}, {from: q.decide ?? lo, to: 0, color: "var(--warn)"}, {from: 0, to: hi, color: "var(--up)"}],
    marks: [{v: q.stop, color: "var(--down)", label: `hard stop ${q.stop}%`}, {v: q.decide, color: "var(--warn)", dash: 1, label: `decide ${q.decide}%`},
      {v: 0, color: "var(--muted)", width: 1}, {v: q.tp, color: "var(--up)", label: `target +${q.tp}%`}]});
}
window.planBullet = planBullet;

function planView(T) {
  const P = T.filter((t) => t.plan).sort((a, b) => a.plan.pri - b.plan.pri || (a.totalPct ?? 0) - (b.totalPct ?? 0));
  if (!P.length) return `<div class="state">No open trade has card rules (A14, Allantis, HV7, TimeEdge, TimeZone, Triple Cal, Flyagonal).</div>`;
  const n = (k) => P.filter((t) => t.plan.act === k).length, mg = (k) => money(P.filter((t) => t.plan.act === k).reduce((a, t) => a + (t.margin || 0), 0));
  const lvl = (pct, d) => ok(pct) ? `${pct > 0 ? "+" : ""}${pct}% <span class="small muted">${d}</span>` : "–";
  const exp = R.detail_exported ? esc(R.detail_exported.replace("T", " ")) : null;
  return `<div class="kv mini" style="margin-bottom:10px">${[["Exit or decide today", n("exit") + n("decide"), "neg", ""], ["Close now", n("close"), "pos", mg("close") + " margin"], ["Slow: exit at next green", n("slow"), "wrn", mg("slow") + " margin"], ["Hold", n("hold"), "", ""]]
    .map(([l, v, k, sub]) => `<div><span class="lbl">${l}</span><b class="${v ? k : ""}">${v}</b><span class="small muted">${sub}</span></div>`).join("")}</div>
    <div class="tbl"><table><thead><tr><th>Trade</th><th>Card</th><th class="n">Total</th><th class="n">Target</th><th class="n" title="adjust today (if the gates pass) or exit">Decide line</th><th class="n">Hard stop</th>
      <th class="n" title="days to first expiry / time stop">DTE / time stop</th><th class="n" title="underlying vs the entry session's close; the adjust gate needs ±1.5% unless the trade is red">Move since entry</th><th class="n" title="ONE Detail Report${exp ? " exported " + exp : ""}">Adjustments</th><th>Adjust?</th>
      <th class="n" title="GTC limit on the whole combo that closes the trade at the target, after commissions; valid until the trade is adjusted">Target close order</th>
      <th class="n" title="index close where the trade reaches the decide line / the hard stop if the move happened today, IVs unchanged: set price alerts there">Alerts: decide / stop</th><th>Action</th></tr></thead><tbody>${
    P.map((t) => { const q = t.plan;
      return `<tr class="click" tabindex="0" data-id="${esc(t.id)}"><td>${esc(t.name)} <span class="small muted">${esc(label(t))}</span></td><td>${esc(t.strategy)}</td>
        <td class="n ${cls(t.totalPct)}"><b>${pctS(t.totalPct)}</b><br>${planBullet(t, 120)}</td><td class="n">${lvl(q.tp, q.lv.tp)}</td><td class="n">${lvl(q.decide, q.lv.decide)}</td><td class="n">${lvl(q.stop, q.lv.stop)}</td>
        <td class="n ${ok(q.timeDte) && q.dte <= q.timeDte ? "wrn" : ""}">${q.dte}d${ok(q.timeDte) ? ` <span class="small muted">/ ${q.timeDte}</span>` : ""}</td>
        <td class="n" title="${q.band ? esc(`entry close ${fmt(t.entry_spot, 0)} · ±1.5% = ${fmt(q.band[0], 0)} / ${fmt(q.band[1], 0)}`) : ""}">${ok(q.move) ? `<span class="${Math.abs(q.move) >= 1.5 ? "wrn" : ""}">${pctS(q.move)}</span>` : "–"}</td>
        <td class="n">${t.adjustments ?? "–"}</td>
        <td><span class="chip ${ADJ_CLS[q.adj.ok]}" title="${esc(q.adj.why + (q.how ? " → " + q.how : ""))}">${esc(q.adj.ok)}</span></td>
        <td class="n small" title="${esc(q.order ? `combo ${q.order.ratio} × ${q.order.units}${ok(q.order.now) ? `, now ${q.order.now.toFixed(2)} at mid` : ""}` : "")}">${orderTxt(q.order, true)}</td>
        <td class="n small">${lvTxt(q.at.decide, t.underlying)}<br>${lvTxt(q.at.stop, t.underlying)}</td>
        <td>${planChip(t)} <span class="small muted">${esc(q.why)}</span></td></tr>`; }).join("")}</tbody></table></div>
    <p class="note">Checked in this order every day: hard stop → target → time stop → slow (under ${fmt(SPEED().slow, 2)}%/day after 3+ weeks, or 25% past your usual hold) → decide line → otherwise hold.
    <b>Adjust?</b> for A14 and Allantis needs all of: under +3%; red, <i>or</i> the underlying ±1.5% from entry; more than 21 DTE to reshape (10–21: roll out or close only; under 10: reduce risk only); not past the stop or time stop.
    How: market up → roll the shorts up or add a call side; market down with 21+ DTE → roll out in time; never roll the shorts down. Targets and stops don't move after an adjustment.
    Calendars: one adjustment, then a further breach is an exit. A14 target is +5% when entered at 21 DTE or less, +7% beyond.
    A14 hard stop is −20% (the card says −10%): replayed on every Friday since 2009, the −10% stop was hit in 28–46% of A14s (14–60 DTE) and cost more than it saved at every SPX entry DTE from 14 to 60; −20% keeps a cap on runaway losses (a stop-free A14 lost over half its margin in 2–5% of trades). Allantis keeps the card's −10% (not backtested). See Evidence → Since 2009.
    <b>Target close order</b>: a GTC limit on the whole combo (legs in the ratio shown, × units) that closes the trade at the target after about $${COMM_SIDE} a contract in commissions. It uses ONE's P&amp;L and the legs' open prices, not today's marks, so it stays right until you adjust; re-enter it after every adjustment. Sell limits are rounded up and buy limits down to ${TICK.toFixed(2)}.
    <b>Alerts</b>: the index level where the trade would reach the decide line and the hard stop if the move happened today with IVs unchanged; set TWS price alerts there. Falls usually come with higher IVs, which reach the stop sooner (the detail panel shows the stop level with IV +3 pts). Stops are best worked by hand at the alert, not left as stop orders on a combo.
    Rules come from your ONE history (56 closed A14s; 365 adjustments, each compared with holding the pre-adjustment legs to the same exit), model error about ±2% of margin. Flags, not orders.
    ${exp ? `Adjustment counts: ONE Detail Report exported ${exp}; trades adjusted since then show the older count.` : "Export a ONE Detail Report to Documents for adjustment counts."}</p>`;
}

function render() {
  if (!R) return;
  const c = ctl();
  $("rkDaysTxt").textContent = c.days === 0 ? "today" : `+${c.days}d (${new Date(now() + c.days * DAY).toLocaleDateString([], {month: "short", day: "numeric"})})`;
  $("rkVolTxt").textContent = `${c.dv >= 0 ? "+" : ""}${Math.round(c.dv * 100)} pts`;
  const T = R.trades.filter((t) => !c.acct || label(t) === c.acct);
  T.forEach((t) => { t.beta = t.underlying === "RUT" ? c.beta : 1; paceOf(t); planOf(t); });
  const N = 81, xsPct = Array.from({length: N}, (_, i) => -c.range + 2 * c.range * i / (N - 1));
  // book
  const accts = [...new Set(T.map(label))];
  const book = accts.map((a) => {
    const tt = T.filter((t) => label(t) === a), cs = tt.map((t) => curves(t, c, xsPct));
    const sum = (k) => xsPct.map((_, i) => cs.reduce((s, cc) => s + cc[k][i], 0));
    return {a, today: sum("today"), dated: sum("dated")};
  });
  const total = (k) => xsPct.map((_, i) => book.reduce((s, b) => s + b[k][i], 0));
  const pal = ["var(--s2)", "var(--s3)", "var(--s4)"];
  const fxp = (x, long) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(long ? 1 : 0)}%`;
  const series = [{name: "Book today", ys: total("today"), color: COL.today, width: 2.2}, {name: `Book at ${$("rkDaysTxt").textContent}`, ys: total("dated"), color: COL.dated, dash: "6 3", width: 2.2, fill: true}];
  if (accts.length > 1) book.forEach((b, k) => series.push({name: `${b.a} at date`, ys: b.dated, color: pal[k % 3], width: 1.3}));
  const pnlNow = T.reduce((s, t) => s + t.pnlNow, 0);
  riskChart($("rkBook"), {label: "book risk graph", h: 260, xs: xsPct, series, spot: 0, nowPnl: pnlNow, fx: fxp, ticks: 5});
  $("rkBookLegend").innerHTML = legend(series.map((s) => [s.name, s.color]));
  $("rkBookNote").textContent = `SPX moves x%, RUT moves ${c.beta} × x%, stocks move x% · IV ${c.dv >= 0 ? "+" : ""}${Math.round(c.dv * 100)} pts`;
  // strip
  const G = T.map((t) => greeks(t)), sumG = (k) => G.reduce((s, g) => s + g[k] * 1, 0);
  const d1 = T.reduce((s, t, i) => s + G[i].dollarDelta1pct * t.beta, 0);
  const worstIdx = total("dated").reduce((m, v, i, a) => (v < a[m] ? i : m), 0);
  const tile = (l, b, sub, k = "") => `<div><span class="lbl">${l}</span><span class="big ${k}">${b}</span><span class="small muted">${sub}</span></div>`;
  $("rkStrip").innerHTML = tile("P&L now", money(pnlNow), `${T.length} trades · ${T.filter((t) => !t.marked).length ? T.filter((t) => !t.marked).length + " not fully marked" : "all legs marked"}`, cls(pnlNow)) +
    tile(mktOpen() ? "Today's return" : "Last session's return", money(T.reduce((s, t) => s + (t.dayChg || 0), 0)), mktOpen() ? "change since the prior close, all trades" : "market shut: the last session's change, all trades", cls(T.reduce((s, t) => s + (t.dayChg || 0), 0))) +
    tile("Delta per 1% move", money(d1), "SPX-equivalent, beta-adjusted", cls(d1)) +
    tile("Theta / day", money(sumG("theta")), "today, at current IVs", cls(sumG("theta"))) +
    tile("Vega / vol pt", money(sumG("vega")), "all legs +1 IV point", cls(sumG("vega"))) +
    tile("Worst in range", money(total("dated")[worstIdx]), `at ${fxp(xsPct[worstIdx], true)} on the chosen date · margin ${money(T.reduce((s, t) => s + (t.margin || 0), 0))}`, "neg");
  $("rkTable").innerHTML = tradesTable(T);
  $("rkPlan").innerHTML = planView(T);
  $("rkCapital").innerHTML = capitalView(T);
  $("rkTable").querySelectorAll("th.sort").forEach((th) => { const go = () => { tSort = {k: th.dataset.k, dir: tSort.k === th.dataset.k ? -tSort.dir : (["pnlNow", "dayChg", "totalPct", "dayPct", "margin", "ditNow", "perDay", "paceNow", "dollarDay"].includes(th.dataset.k) ? -1 : 1)}; render(); };
    th.addEventListener("click", go); th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }); });
  document.querySelectorAll("#rkTable tr.click, #rkCapital tr.click, #rkPlan tr.click").forEach((tr) => { const go = () => openDetail(tr.dataset.id); tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); });
  // groups
  const recon = new Map(R.recon.map((r) => [r.label, r]));
  $("rkGroups").innerHTML = accts.map((a) => {
    const tt = T.filter((t) => label(t) === a), rc = recon.get(a);
    const ap = tt.reduce((s, t) => s + t.pnlNow, 0);
    return `<section class="acct"><header><h2>${esc(a)} · ${tt.length} trades · <span class="${cls(ap)}">${money(ap)}</span></h2>
      ${rc ? (rc.diffs.length ? `<span class="chip neg" title="${esc(rc.diffs.slice(0, 12).map((d) => `${d.symbol}: ONE ${d.one} / IBKR ${d.ibkr}`).join("\n"))}">${rc.diffs.length} legs differ from IBKR</span>` : `<span class="chip pos">Matches IBKR positions</span>`) : `<span class="chip muted">not reconciled</span>`}</header>
      <div class="rgrid">${tt.sort((x, y) => x.firstExp - y.firstExp || x.underlying.localeCompare(y.underlying)).map((t) => { const g = greeks(t), dte = Math.max(0, Math.round((t.firstExp - now()) / DAY));
        return `<div class="rcard" tabindex="0" data-id="${esc(t.id)}"><div class="hd"><span class="nm" title="${esc(t.name)}">${esc(t.name)}</span><span class="mono ${cls(t.pnlNow)}">${money(t.pnlNow)}</span></div>
          <div class="greeks"><span>Total <b class="${cls(t.pnlNow)}">${pctS(t.totalPct)}</b></span><span>Today <b class="${cls(t.dayChg)}">${money(t.dayChg)} (${pctS(t.dayPct)})</b></span></div>
          <div class="greeks"><span>Opened ${dshort(t.openedMs)}</span><span>${t.ditNow ?? "–"}d in trade</span><span>${dteTxt(t)} to expiry (${dexp(t.firstExp)})</span></div>
          <div class="chart" id="rc-${cssId(t.id)}"></div>
          <div class="greeks"><span>${esc(t.underlying)} ${fmt(t.spot, 0)}</span><span>Δ ${fmt(g.delta, 1)}</span><span>θ ${money(g.theta)}</span><span>ν ${money(g.vega)}</span>${t.marked ? "" : `<span class="wrn">unmarked legs</span>`}</div></div>`; }).join("")}</div></section>`;
  }).join("");
  T.forEach((t) => {
    const cv = curves(t, c, xsPct), xsS = xsPct.map((x) => t.spot * (1 + x * t.beta));
    riskChart($("rc-" + cssId(t.id)), {label: t.name, h: 140, xs: xsS, spot: t.spot, nowPnl: t.pnlNow, fx: (v) => Math.round(v),
      series: [{name: "Today", ys: cv.today, color: COL.today}, {name: "Chosen date", ys: cv.dated, color: COL.dated, dash: "5 3", fill: true}, {name: "First expiry", ys: cv.expiry, color: COL.expiry, width: 1, scale: false}]});
  });
  document.querySelectorAll(".rcard").forEach((el) => { const go = () => openDetail(el.dataset.id); el.addEventListener("click", go); el.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); });
  if (sel && !$("rkDetailPanel").hidden) openDetail(sel, true);
}
const cssId = (s) => s.replace(/[^A-Za-z0-9]/g, "_");

function openDetail(id, quiet) {
  const t = R.trades.find((x) => x.id === id); if (!t) return;
  sel = id; const c = ctl(), N = 121, xsPct = Array.from({length: N}, (_, i) => -c.range + 2 * c.range * i / (N - 1));
  t.beta = t.underlying === "RUT" ? c.beta : 1;
  const cv = curves(t, c, xsPct), xs = xsPct.map((x) => t.spot * (1 + x * t.beta));
  $("rkDetailPanel").hidden = false;
  $("rkDetailTitle").textContent = `${t.name} · ${label(t)}`;
  const series = [{name: "Today", ys: cv.today, color: COL.today, width: 2.2}, {name: "Chosen date", ys: cv.dated, color: COL.dated, dash: "6 3", width: 2.2, fill: true}, {name: "First expiry", ys: cv.expiry, color: COL.expiry, width: 1.2}];
  riskChart($("rkDetailChart"), {label: t.name, h: 300, xs, spot: t.spot, nowPnl: t.pnlNow, fx: (v, long) => long ? `${t.underlying} ${v.toFixed(0)} (${((v / t.spot - 1) * 100).toFixed(1)}%)` : Math.round(v), series, ticks: 6});
  $("rkDetailLegend").innerHTML = legend(series.map((s) => [s.name, s.color]));
  const be = []; for (let i = 1; i < N; i++) { const a = cv.expiry[i - 1], b = cv.expiry[i]; if ((a < 0) !== (b < 0)) be.push(xs[i - 1] + (xs[i] - xs[i - 1]) * (0 - a) / (b - a)); }
  paceOf(t); planOf(t);
  const q = t.plan;
  $("rkDetailLegs").innerHTML = (q ? `<div class="kv mini" style="margin:8px 0">${[["Action", planChip(t), q.why], ["Target", `+${q.tp}%`, q.lv.tp], ["Decide line", ok(q.decide) ? q.decide + "%" : "–", q.lv.decide || ""], ["Hard stop", ok(q.stop) ? q.stop + "%" : "–", q.lv.stop || ""],
    ["Adjust?", `<span class="chip ${ADJ_CLS[q.adj.ok]}">${esc(q.adj.ok)}</span>`, q.adj.why + (q.how ? " → " + q.how : "")], ["Adjust band (±1.5%)", q.band ? `${fmt(q.band[0], 0)} / ${fmt(q.band[1], 0)}` : "–", ok(q.move) ? `${t.underlying} ${pctS(q.move)} since entry` : ""],
    ["Target close order (GTC)", orderTxt(q.order, true), q.order ? `combo ${q.order.ratio} × ${q.order.units}${ok(q.order.now) ? ` · now ${q.order.now.toFixed(2)} at mid` : ""} · whole position worth ${money(Math.abs(q.order.total))}${q.order.nLegs > 4 ? ` · ${q.order.nLegs} legs: if TWS won't take one combo, close in pieces once the position is worth that` : ""} · re-enter after any adjustment` : ""],
    ["Stop: close price", orderTxt(q.stopPx, true), q.stopPx ? "where the combo is worth the hard stop" : ""],
    ["Alert: decide line", lvTxt(q.at.decide, t.underlying), "if the move happened today, IVs unchanged"],
    ["Alert: hard stop", lvTxt(q.at.stop, t.underlying), q.at.stopIv && !q.at.stopIv.past ? `with IV +3 pts: ${lvTxt(q.at.stopIv, t.underlying)}` : ""]]
    .map(([l, b, sub]) => `<div><span class="lbl">${l}</span><b>${b}</b><span class="small muted">${esc(sub)}</span></div>`).join("")}</div>` : "") + `<div class="small muted">ONE P&amp;L (realised + commissions) ${money(t.one_pnl)} · open legs at TWS mid ${money(t.unreal)} · margin ${money(t.margin)} · days in trade ${t.dit ?? "–"}${be.length ? ` · first-expiry breakevens ${be.map((b) => b.toFixed(0)).join(" / ")}` : ""}</div>
    <div class="tbl"><table><thead><tr><th>Leg</th><th class="n">Qty</th><th class="n">Open</th><th class="n">Bid</th><th class="n">Ask</th><th class="n">Mid</th><th class="n">IV</th><th class="n">Leg P&amp;L</th><th>Expires</th></tr></thead><tbody>${
      t.legs.map((l) => `<tr><td class="mono">${esc(l.symbol)}</td><td class="n ${l.qty < 0 ? "neg" : ""}">${l.qty > 0 ? "+" : ""}${l.qty}</td><td class="n">${fmt(l.open_price)}</td><td class="n">${fmt(l.mark && l.mark.bid)}</td><td class="n">${fmt(l.mark && l.mark.ask)}</td><td class="n">${fmt(l.mid)}</td><td class="n" title="${esc((l.mark && l.mark.iv_src) || "same-expiry average")}">${fmt(l.vol * 100, 1)}%${l.mark && l.mark.iv_src === "surface" ? "ˢ" : l.mark && ok(l.mark.iv) ? "" : "*"}</td><td class="n ${cls(l.mid == null ? null : l.qty * (l.mid - l.open_price))}">${l.mid == null ? "–" : money(l.qty * MULT * (l.mid - l.open_price))}</td><td class="small mono">${l.expiry_iso.slice(0, 16).replace("T", " ")} ET</td></tr>`).join("")
    }</tbody></table></div><p class="note">ˢ in-the-money leg: IV taken from your recorded surface at that strike (TWS model IVs are unreliable deep in the money). * no IV available: average of the trade's other legs in the same expiry.</p>`;

}

let STATS = null;
async function load() {
  try {
    [R, STATS] = await Promise.all([fetch("/api/risk").then((r) => r.json()), fetch("/api/a14/stats").then((r) => r.json()).catch(() => null)]);
    R.trades.forEach(prep);
    const accts = [...new Set(R.trades.map(label))];
    const cur = $("rkAcct").value;
    $("rkAcct").innerHTML = `<option value="">All</option>` + accts.map((a) => `<option ${a === cur ? "selected" : ""}>${esc(a)}</option>`).join("");
    const maxD = Math.max(1, Math.ceil((Math.max(...R.trades.map((t) => t.firstExp)) - now()) / DAY));
    $("rkDays").max = String(Math.min(maxD, 120));
    $("rkStale").innerHTML = oneStale(R);
    $("rkMeta").textContent = R.marks_ts ? `marks ${new Date(R.marks_ts).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})} · ONE ${String(R.one_file || "").split(/[\\/]/).pop()}` : "no marks yet: press Refresh";
    if (!R.marks_ts) $("rkGroups").innerHTML = `<div class="state">No TWS marks yet. Press “Refresh marks from TWS” (TWS must be running).</div>`;
    render();
  } catch (e) { $("rkGroups").innerHTML = `<div class="state err">${esc(e.message || e)}</div>`; }
}
async function refresh() {
  $("rkRefresh").disabled = true; $("rkMeta").textContent = "Fetching marks from TWS…";
  await fetch("/api/risk/refresh", {method: "POST"});
  for (let i = 0; i < 90; i++) { await new Promise((r) => setTimeout(r, 2000)); const s = await (await fetch("/api/risk/status")).json(); if (!s.running) { if (s.log.length) $("rkMeta").textContent = s.log[s.log.length - 1]; break; } }
  $("rkRefresh").disabled = false; await load();
}
["rkDays", "rkVol"].forEach((id) => $(id).addEventListener("input", () => { clearTimeout(render._t); render._t = setTimeout(render, 60); }));
["rkRange", "rkBeta", "rkAcct"].forEach((id) => $(id).addEventListener("change", render));
$("rkRefresh").addEventListener("click", refresh);
$("rkClose").addEventListener("click", () => { sel = null; $("rkDetailPanel").hidden = true; });
window.loadRisk = load;
// for the Actions tab: every open trade with its plan (pace, trade plan, close order, alert levels)
window.riskActions = async () => {
  if (!R) await load();
  if (!R || !R.trades) return null;
  R.trades.forEach((t) => { t.beta = 1; paceOf(t); planOf(t); t.acctLabel = label(t); });
  return {trades: R.trades, marks_ts: R.marks_ts, one_fresh: R.one_fresh, detail_exported: R.detail_exported, missing: R.missing || []};
};
window.riskOpen = (id) => openDetail(id);
window.riskChart = riskChart;
})();
