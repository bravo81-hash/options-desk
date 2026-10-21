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
  const cols = [["name", "Trade"], ["acct", "Account"], ["pnlNow", "Total return", 1], ["totalPct", "Total %", 1], ["perDay", "% / day", 1], ["dollarDay", "$ / day", 1], ["dayChg", "Today's return", 1], ["dayPct", "Today %", 1],
    ["openedMs", "Opened", 1], ["ditNow", "Days in trade", 1], ["firstExp", "Days to expiry", 1], ["margin", "Margin", 1]];
  T.forEach((t) => { t.acct = label(t); });
  const s = tSort, rows = [...T].sort((a, b) => { const x = a[s.k], y = b[s.k]; if (!ok(x) && typeof x !== "string") return 1; if (!ok(y) && typeof y !== "string") return -1;
    return typeof x === "string" ? (s.dir < 0 ? y.localeCompare(x) : x.localeCompare(y)) : (s.dir < 0 ? y - x : x - y); });
  const tot = (k) => T.reduce((a, t) => a + (ok(t[k]) ? t[k] : 0), 0), mg = tot("margin");
  return `<div class="tbl"><table><thead><tr>${cols.map(([k, l, n]) => `<th class="sort ${n ? "n" : ""}" tabindex="0" data-k="${k}" ${s.k === k ? `aria-sort="${s.dir < 0 ? "descending" : "ascending"}"` : ""}>${l}${s.k === k ? (s.dir < 0 ? " ▾" : " ▴") : ""}</th>`).join("")}</tr></thead><tbody>${
    rows.map((t) => `<tr class="click" tabindex="0" data-id="${esc(t.id)}"><td>${esc(t.name)}</td><td>${esc(t.acct)}</td>
      <td class="n ${cls(t.pnlNow)}">${money(t.pnlNow)}</td><td class="n ${cls(t.totalPct)}">${pctS(t.totalPct)}</td>
      <td class="n ${cls(t.perDay)}" title="total return ÷ ${Math.max(t.ditNow || 0, 1)} days in trade">${ok(t.perDay) ? fmt(t.perDay, 2) + "%" : "–"}</td><td class="n ${cls(t.dollarDay)}">${money(t.dollarDay)}</td>
      <td class="n ${cls(t.dayChg)}">${money(t.dayChg)}</td><td class="n ${cls(t.dayPct)}">${pctS(t.dayPct)}</td>
      <td class="n">${dshort(t.openedMs)}</td><td class="n">${t.ditNow ?? "–"}</td><td class="n" title="${esc(dexp(t.firstExp) + (t.lastExp > t.firstExp + DAY ? " / " + dexp(t.lastExp) : ""))}">${dteTxt(t)}</td><td class="n">${money(t.margin)}</td></tr>`).join("")}
    <tr><td><b>Total</b></td><td></td><td class="n ${cls(tot("pnlNow"))}"><b>${money(tot("pnlNow"))}</b></td><td class="n">${mg ? pctS(100 * tot("pnlNow") / mg) : "–"}</td>
      <td class="n" title="book: total $ per day ÷ total margin">${mg ? fmt(100 * tot("dollarDay") / mg, 2) + "%" : "–"}</td><td class="n"><b>${money(tot("dollarDay"))}</b></td>
      <td class="n ${cls(tot("dayChg"))}"><b>${money(tot("dayChg"))}</b></td><td class="n">${mg ? pctS(100 * tot("dayChg") / mg) : "–"}</td><td></td><td></td><td></td><td class="n">${money(mg)}</td></tr></tbody></table></div>`;
}
function label(t) { return R.labels[t.ib_account] || t.group; }

/* ---------- capital use: margin and days tied up, by DTE at entry ---------- */
const BUCKETS = [[0, 21, "≤21"], [22, 45, "22–45"], [46, 70, "46–70"], [71, 9999, "71+"]];
function capitalView(T) {
  const mgAll = T.reduce((a, t) => a + (t.margin || 0), 0) || 1, bench = (STATS && STATS.by_dte) || {};
  const rows = BUCKETS.map(([lo, hi, lab]) => {
    const tt = T.filter((t) => ok(t.entryDte) && t.entryDte >= lo && t.entryDte <= hi);
    if (!tt.length) return "";
    const mg = tt.reduce((a, t) => a + (t.margin || 0), 0), pnl = tt.reduce((a, t) => a + (t.pnlNow || 0), 0);
    const dd = tt.reduce((a, t) => a + (t.dollarDay || 0), 0), days = tt.reduce((a, t) => a + Math.max(t.ditNow || 0, 1), 0) / tt.length;
    const pd = mg ? 100 * dd / mg : null, b = bench[lab];
    return `<tr><td>${lab} DTE</td><td class="n">${tt.length}</td><td class="n">${money(mg)}</td>
      <td><span class="minibar" style="width:120px"><span style="width:${(100 * mg / mgAll).toFixed(0)}%"></span></span><span class="small muted">${Math.round(100 * mg / mgAll)}%</span></td>
      <td class="n ${cls(pnl)}">${money(pnl)}</td><td class="n">${mg ? pctS(100 * pnl / mg) : "–"}</td><td class="n">${Math.round(days)}</td>
      <td class="n ${cls(pd)}"><b>${ok(pd) ? fmt(pd, 2) + "%" : "–"}</b></td><td class="n">${money(dd)}</td>
      <td class="n muted">${b ? `${fmt(b.per_day, 2)}% <span class="small">(n ${b.n}, ${Math.round(b.dit)}d)</span>` : "–"}</td></tr>`;
  }).join("");
  // trades earning less per day than your slowest finished A14 bucket, biggest margin first
  const floor = Math.min(...Object.values(bench).map((b) => b.per_day), 0.25);
  const slow = T.filter((t) => ok(t.perDay) && t.margin && t.perDay < floor).sort((a, b) => b.margin - a.margin).slice(0, 8);
  return `<div class="tbl"><table><thead><tr><th>Entry DTE</th><th class="n">Trades</th><th class="n">Margin</th><th>Share of margin</th><th class="n">P&amp;L now</th><th class="n">Return</th><th class="n">Avg days held</th>
    <th class="n" title="all trades in the bucket: $ per day held ÷ margin">Return / day</th><th class="n">$ / day</th><th class="n" title="your closed A14 trades in ONE with the same entry DTE">Closed A14s / day</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h3 style="margin:14px 0 6px">Most margin for the least return per day <span class="small muted">(below ${fmt(floor, 2)}% a day, largest margin first)</span></h3>
    <div class="tbl"><table><thead><tr><th>Trade</th><th class="n">Entry DTE</th><th class="n">Margin</th><th class="n">Days held</th><th class="n">Total</th><th class="n">% / day</th><th class="n">$ / day</th></tr></thead><tbody>${
    slow.map((t) => `<tr class="click" data-id="${esc(t.id)}"><td>${esc(t.name)}</td><td class="n">${t.entryDte ?? "–"}</td><td class="n">${money(t.margin)}</td><td class="n">${t.ditNow ?? "–"}</td><td class="n ${cls(t.totalPct)}">${pctS(t.totalPct)}</td><td class="n ${cls(t.perDay)}">${fmt(t.perDay, 2)}%</td><td class="n ${cls(t.dollarDay)}">${money(t.dollarDay)}</td></tr>`).join("")}</tbody></table></div>
    <p class="note">Return per day = total return on ONE margin ÷ days in trade. Open trades are mid-way, so their per-day figure can still rise (theta accelerates near expiry) or fall; the closed-A14 column is what your finished trades with the same entry DTE earned per day held. Data, not a recommendation: longer-dated trades also carry less gamma risk.</p>`;
}

function render() {
  if (!R) return;
  const c = ctl();
  $("rkDaysTxt").textContent = c.days === 0 ? "today" : `+${c.days}d (${new Date(now() + c.days * DAY).toLocaleDateString([], {month: "short", day: "numeric"})})`;
  $("rkVolTxt").textContent = `${c.dv >= 0 ? "+" : ""}${Math.round(c.dv * 100)} pts`;
  const T = R.trades.filter((t) => !c.acct || label(t) === c.acct);
  T.forEach((t) => { t.beta = t.underlying === "RUT" ? c.beta : 1; });
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
  $("rkCapital").innerHTML = capitalView(T);
  $("rkTable").querySelectorAll("th.sort").forEach((th) => { const go = () => { tSort = {k: th.dataset.k, dir: tSort.k === th.dataset.k ? -tSort.dir : (["pnlNow", "dayChg", "totalPct", "dayPct", "margin", "ditNow", "perDay", "dollarDay"].includes(th.dataset.k) ? -1 : 1)}; render(); };
    th.addEventListener("click", go); th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }); });
  document.querySelectorAll("#rkTable tr.click, #rkCapital tr.click").forEach((tr) => { const go = () => openDetail(tr.dataset.id); tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); });
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
  $("rkDetailLegs").innerHTML = `<div class="small muted">ONE P&amp;L (realised + commissions) ${money(t.one_pnl)} · open legs at TWS mid ${money(t.unreal)} · margin ${money(t.margin)} · days in trade ${t.dit ?? "–"}${be.length ? ` · first-expiry breakevens ${be.map((b) => b.toFixed(0)).join(" / ")}` : ""}</div>
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
window.riskChart = riskChart;
})();
