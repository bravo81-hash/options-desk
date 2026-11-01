/* Journal statistics. Pure functions, no page access, tested in tests/test_journal_js.py.
   Everything is counted on decisions: the same trade placed in two accounts is one decision, one win or one loss. */
"use strict";
window.JStats = (() => {
const num = (v) => v != null && isFinite(v);
const sum = (a) => a.reduce((s, v) => s + v, 0);
const mean = (a) => a.length ? sum(a) / a.length : null;
const median = (a) => { if (!a.length) return null; const b = [...a].sort((x, y) => x - y), m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; };
const sd = (a) => { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(sum(a.map((v) => (v - m) ** 2)) / (a.length - 1)); };
const spread = (a) => { const s = sd(a); return s > 1e-12 ? s : null; };  // identical values leave rounding dust, not a spread
const skew = (a) => { const s = spread(a), m = mean(a); return s ? mean(a.map((v) => ((v - m) / s) ** 3)) : null; };
const cv = (a) => { const s = sd(a), m = mean(a); return s != null && m ? s / m : null; };
const sqn = (a) => { const s = spread(a); return s ? mean(a) / s * Math.sqrt(a.length) : null; };
/* Wilson interval on a win rate; z 1.2816 is 80% two-sided. Stays inside 0–1 and is honest at 0 or n wins. */
function wilson(w, n, z = 1.2816) {
  if (!n) return [null, null];
  const p = w / n, c = z * z, dn = 1 + c / n, ce = p + c / (2 * n), m = z * Math.sqrt(p * (1 - p) / n + c / (4 * n * n));
  return [Math.max(0, (ce - m) / dn), Math.min(1, (ce + m) / dn)];
}
const rng = (seed) => () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
/* Bootstrap interval on the mean: resample the decisions with replacement. Seeded, so a page reload shows the same numbers. */
function bootMean(a, {B = 2000, lo = 0.1, hi = 0.9, seed = 7} = {}) {
  if (a.length < 2) return [null, null];
  const r = rng(seed), out = new Float64Array(B), n = a.length;
  for (let b = 0; b < B; b++) { let s = 0; for (let i = 0; i < n; i++) s += a[Math.floor(r() * n)]; out[b] = s / n; }
  out.sort();
  return [out[Math.floor(lo * (B - 1))], out[Math.floor(hi * (B - 1))]];
}

/* Book rows to decisions. Twins average for R and add up for dollars; a decision counts once every side has closed. */
function fold(rows) {
  const g = new Map();
  rows.forEach((r) => { if (!g.has(r.decision)) g.set(r.decision, []); g.get(r.decision).push(r); });
  return [...g.values()].map((v) => {
    const a = v[0], done = v.every((x) => !x.open), rs = v.map((x) => x.r).filter(num), by = (f) => v.map(f).filter(num), first = (f) => by(f)[0] ?? null;
    const checks = v.flatMap((x) => x.checks || []), live = v.map((x) => x.followed).filter((x) => x != null), ever = v.map((x) => x.followed_ever).filter((x) => x != null);
    return {decision: a.decision, keys: v.flatMap((x) => x.keys), rows: v, strategy: a.strategy, ticker: a.ticker, entry: v.map((x) => x.entry).sort()[0], close: done ? v.map((x) => x.close).sort().pop() : null,
      exit_us: done ? v.map((x) => x.exit_us).sort().pop() : null, entry_us: a.entry_us, open: !done, r: done && rs.length === v.length ? mean(rs) : null, pnl: done ? sum(v.map((x) => x.pnl || 0)) : null, risk0: sum(by((x) => x.risk0)),
      risk_days: sum(by((x) => x.risk_days)), peak: sum(by((x) => x.peak)), creep: Math.max(...by((x) => x.creep)), adj: Math.max(...by((x) => x.adj)), dte0: a.dte0, dit: Math.max(0, ...by((x) => x.dit)),
      vix: first((x) => x.vix), ivts: first((x) => x.ivts), plan: by((x) => x.plan).length ? sum(by((x) => x.plan)) : null, plan_pct: by((x) => x.plan_pct).length ? Math.max(...by((x) => x.plan_pct)) : null,
      checks, followed: live.length ? live.every(Boolean) : null, followed_ever: ever.length ? ever.every(Boolean) : null, extreme: a.extreme || [], streak: a.streak, hot: a.hot, size_x: a.size_x, revenge: a.revenge,
      after_loss: a.after_loss, ticket: a.ticket, rolls: Math.max(0, ...by((x) => x.rolls)), accts: [...new Set(v.map((x) => x.acct))]};
  }).sort((x, y) => x.entry.localeCompare(y.entry));
}
const closed = (D) => D.filter((d) => num(d.r));

function kpi(D) {
  const C = closed(D), R = C.map((d) => d.r), W = C.filter((d) => d.pnl > 0), L = C.filter((d) => d.pnl <= 0), wr = W.map((d) => d.r), lr = L.map((d) => -d.r);
  const avgW = mean(wr), avgL = mean(lr), bestR = R.length ? Math.max(...R) : null, worstR = R.length ? Math.min(...R) : null, days = sum(C.map((d) => d.risk_days));
  return {n: C.length, wins: W.length, losses: L.length, win: C.length ? W.length / C.length : null, ci: wilson(W.length, C.length), avgWin: avgW, avgLoss: avgL, avgWinUsd: mean(W.map((d) => d.pnl)), avgLossUsd: mean(L.map((d) => d.pnl)),
    payoff: avgW != null && avgL ? avgW / avgL : null, expR: mean(R), expUsd: mean(C.map((d) => d.pnl)), totalR: sum(R), totalUsd: sum(C.map((d) => d.pnl)), mean: mean(R), median: median(R), sd: sd(R), cv: cv(R), skew: skew(R), sqn: sqn(R),
    pf: L.length ? sum(wr) / sum(lr) : null, bestR, worstR, bestUsd: C.length ? Math.max(...C.map((d) => d.pnl)) : null, worstUsd: C.length ? Math.min(...C.map((d) => d.pnl)) : null,
    worstOverAvg: avgL && worstR != null ? -worstR / avgL : null, bestOverWorst: bestR != null && worstR ? bestR / -worstR : null, rod: days > 0 ? 100 * sum(C.map((d) => d.pnl)) / days : null,
    tail: C.length ? R.filter((v) => v < -0.5).length / C.length : null, meanCi: bootMean(R)};
}

/* Cumulative R by close, with its running peak. base: capital at the start in dollars, for the drawdown in %. */
function curve(D, base) {
  const C = closed(D).slice().sort((a, b) => a.close.localeCompare(b.close));
  let run = 0, peak = 0, usd = 0, top = base || 0, mddR = 0, mddP = 0;
  const pts = C.map((d) => { run += d.r; usd += d.pnl; peak = Math.max(peak, run); mddR = Math.min(mddR, run - peak);
    if (base) { const eq = base + usd; top = Math.max(top, eq); mddP = Math.min(mddP, eq / top - 1); }
    return {d: d.exit_us, v: run, peak, usd, title: d}; });
  const lastDd = pts.length ? run - peak : 0, nowP = base && pts.length ? (base + usd) / top - 1 : 0;
  return {pts, mddR, mddP: base ? 100 * mddP : null, ddNow: lastDd, ddNowP: base ? 100 * nowP : null, recover: base ? 100 * recovery(-mddP) : null, recoverNow: base ? 100 * recovery(-nowP) : null};
}
/* A loss of share x needs this gain to get back: 0.5 -> 1.0. */
const recovery = (x) => x >= 1 ? Infinity : x / (1 - x);

function hist(vals, width = 0.1) {
  if (!vals.length) return [];
  const lo = Math.floor(Math.min(...vals) / width + 1e-9), hi = Math.ceil(Math.max(...vals) / width + 1e-9), bins = [];
  for (let k = lo; k < Math.max(hi, lo + 1); k++) bins.push({x0: k * width, x1: (k + 1) * width, n: 0});
  vals.forEach((v) => { const i = Math.min(Math.floor(v / width + 1e-9) - lo, bins.length - 1); bins[i].n++; });
  return bins;
}

/* One strategy against the rules of thumb. A losing strategy never passes: CV only measures spread around the mean. */
function confidence(D, prior, cfg) {
  const k = kpi(D), before = prior || {n: 0, losses: 0}, lossesAll = k.losses + before.losses, rate = k.n ? k.losses / k.n : null;
  return {...k, prior: before, lossesAll, barOk: lossesAll >= cfg.loss_bar, more: rate ? Math.max(Math.ceil((cfg.loss_bar - lossesAll) / rate), 0) : null,
    cvOk: k.mean > 0 && k.cv != null && k.cv < cfg.cv_max, skewOk: k.skew != null && k.skew > cfg.skew_min, ciOk: num(k.meanCi[0]) && k.meanCi[0] > 0};
}

const VIX = [["under 15", 0, 15], ["15–20", 15, 20], ["20–30", 20, 30], ["30+", 30, 1e9]];
const DTE = [["up to 21", 0, 21], ["22–45", 22, 45], ["46–70", 46, 70], ["71+", 71, 1e9]];
const ADJ = [["none", 0, 0], ["1–2", 1, 2], ["3–5", 3, 5], ["6+", 6, 1e9]];
const bucket = (v, table) => { if (!num(v)) return null; const b = table.find(([, lo, hi]) => table === VIX ? v >= lo && v < hi : v >= lo && v <= hi); return b ? b[0] : null; };
/* Group decisions by a label: n, wins, mean R and dollars. */
function groupBy(D, fn, order) {
  const g = new Map();
  closed(D).forEach((d) => { const k = fn(d); if (k == null) return; if (!g.has(k)) g.set(k, []); g.get(k).push(d); });
  const keys = order ? order.filter((k) => g.has(k)) : [...g.keys()];
  return keys.map((k) => { const v = g.get(k), R = v.map((d) => d.r); return {label: k, n: v.length, losses: v.filter((d) => d.pnl <= 0).length, win: v.filter((d) => d.pnl > 0).length / v.length, mean: mean(R), median: median(R), pnl: sum(v.map((d) => d.pnl))}; });
}

const RULES = {stop: "Closed inside the card's stop", time: "Out before the time stop", adjust: "Stayed inside the adjustment limit", gate: "Calendar entered with the gate open", aside: "A14 stood aside in backwardation", cap: "Planned loss inside the cap"};
/* Rule accuracy against win rate. live: only rules that existed at that moment. all: as if every rule had always existed. */
function accuracy(D, all) {
  const C = closed(D), key = all ? "followed_ever" : "followed", S = C.filter((d) => d[key] != null), F = S.filter((d) => d[key]), B = S.filter((d) => !d[key]);
  const side = (a) => ({n: a.length, win: a.length ? a.filter((d) => d.pnl > 0).length / a.length : null, mean: mean(a.map((d) => d.r)), pnl: sum(a.map((d) => d.pnl))});
  const rules = Object.keys(RULES).map((id) => {
    const seen = S.filter((d) => d.checks.some((c) => c[0] === id && (all || c[2])));
    const pass = (d) => d.checks.filter((c) => c[0] === id && (all || c[2])).every((c) => c[1]);
    return {id, label: RULES[id], kept: side(seen.filter(pass)), broke: side(seen.filter((d) => !pass(d)))};
  });
  return {scored: S.length, unscored: C.length - S.length, accuracy: S.length ? F.length / S.length : null, win: kpi(C).win, kept: side(F), broke: side(B), rules};
}

return {num, sum, mean, median, sd, skew, cv, sqn, wilson, bootMean, fold, closed, kpi, curve, recovery, hist, confidence, bucket, groupBy, accuracy, VIX, DTE, ADJ, RULES};
})();
