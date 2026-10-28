"""Model backtest of your A14 and TimeEdge rules over every regime since late 2009.

Your closed trades in ONE all fall in June-October 2026, one calm and mostly rising market, so the rules drawn
from them are untested in a selloff. This replays the same structures and exits on SPX / RUT daily closes from
2009-10 (when VIX3M starts) to the latest close: 2010 flash crash, 2011 downgrade, 2015, 2018 (February and Q4),
2020, 2022, 2024 and 2025.

Pricing is the model that matched your ONE fills (median exit error about 1% of margin): Black-76 with the ATM vol
from the CBOE VIX9D/VIX/VIX3M/VIX6M/VIX1Y curve (total-variance interpolation; RUT scaled by RVX/VIX) and the put
skew fitted on your fills, sticky-moneyness. It knows each day's vol level and term structure, not that day's
skew, bid/ask or event bumps. a14_managed re-centres by rule; your own adjustments (which added about +3% of
margin a trade in 2026) are not modelled.

Structures (per lot): A14 = your median shape in units of the implied move to expiry (upper long ~ATM, short
~0.3 sd below, wings 0.29 / 0.38 sd SPX, 0.33 / 0.44 sd RUT), entered Fridays; TimeEdge = ATM put calendar,
short 15 DTE / long 22 DTE, entered every weekday. Costs: $1.36 a contract a side plus a quarter point a combo
a side (SPX; RUT 0.15), so every result is after costs. Returns are % of max loss (ONE margin for these).
"""
import datetime as dt
import json
import math
import threading

import numpy as np
import pandas as pd

from . import db
from .a14 import put_price
from .history import series
from .readiness import ivts_band

START = "2009-10-01"
VERSION = 6
SKEW = {"SPX": (0.798, -1.102, 1.584), "RUT": (0.875, -0.735, 1.174)}  # fitted on your ONE fills, Jun-Oct 2026
GEOM = {"SPX": (0.0, 0.29, 0.38), "RUT": (0.05, 0.33, 0.44)}  # upper offset, upper wing, lower wing (sd units)
COMM, SLIP = 1.36, {"SPX": 0.25, "RUT": 0.15}
TEN = np.array([9.0, 30.0, 93.0, 183.0, 365.0])
A14_DTE = [14, 21, 30, 45, 60, 90]
TPS, SLS = [3, 5, 7, 10, 15, None], [5, 8, 10, 15, 20, None]
status = {"running": False, "error": None}
_lock = threading.Lock()


# ------------------------------------------------------------------ data
def _bars(sym):
    rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=? AND date>=? ORDER BY date", (sym, START))
    return {r["date"]: r["c"] for r in rows if r["c"]}


def _bars_all(sym):
    rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=? ORDER BY date", (sym,))
    return {r["date"]: r["c"] for r in rows if r["c"]}


def _season_up(full, days, h=21, lookback=20):
    """Seasonality tab's 21-day window: share of the previous 20 years in which SPX was higher 21 sessions after
    the same calendar date (only years before the entry, so no look-ahead)."""
    idx = pd.to_datetime(full.index)
    vals = full.values
    by_year = {}
    for y in sorted(set(idx.year)):
        m = idx.year == y
        by_year[y] = (idx[m], np.flatnonzero(m))
    out = np.full(len(days), np.nan)
    for k, d in enumerate(days):
        t = dt.date.fromisoformat(d)
        ups = []
        for y in range(t.year - lookback, t.year):
            if y not in by_year:
                continue
            ds, ii = by_year[y]
            j = ds.searchsorted(pd.Timestamp(year=y, month=t.month, day=min(t.day, 28 if t.month == 2 else t.day)))
            if j >= len(ii) or ii[j] + h >= len(vals):
                continue
            ups.append(vals[ii[j] + h] > vals[ii[j]])
        if len(ups) >= 10:
            out[k] = 100 * np.mean(ups)
    return out


def load():
    spot = {"SPX": _bars("^GSPC"), "RUT": _bars("^RUT")}
    vol = {n: series(n, START).to_dict() for n in ("VIX9D", "VIX", "VIX3M", "VIX6M", "VIX1Y", "RVX")}
    days = sorted(d for d in spot["SPX"] if d in spot["RUT"] and all(d in vol[n] for n in ("VIX", "VIX3M", "VIX6M", "VIX1Y", "RVX")))
    D = {"days": days, "di": {d: i for i, d in enumerate(days)}, "date": np.array([dt.date.fromisoformat(d) for d in days])}
    for u in ("SPX", "RUT"):
        D[u] = np.array([spot[u][d] for d in days])
    v = {n: np.array([vol[n].get(d, np.nan) for d in days]) / 100 for n in ("VIX9D", "VIX", "VIX3M", "VIX6M", "VIX1Y", "RVX")}
    v["VIX9D"] = np.where(np.isnan(v["VIX9D"]), v["VIX"], v["VIX9D"])  # before 2011: flat from VIX
    D["W"] = np.stack([v[n] ** 2 * t for n, t in zip(("VIX9D", "VIX", "VIX3M", "VIX6M", "VIX1Y"), TEN)], axis=1)  # total variance
    D["vix"], D["vix3m"], D["rvx"] = v["VIX"], v["VIX3M"], v["RVX"]
    # signals from the other tabs, for the condition matrix (nan where a series has no value that day)
    for n in ("SKEW", "VVIX"):
        x = series(n).to_dict()
        D[n.lower()] = np.array([x.get(d, np.nan) for d in days], dtype=float)
    D["vix9d_raw"] = np.array([vol["VIX9D"].get(d, np.nan) for d in days], dtype=float) / 100
    vx = series("VIX")
    pct = vx.rolling(252).apply(lambda a: (a[:-1] < a[-1]).mean() * 100, raw=True).to_dict()  # 1-year percentile of VIX
    D["vix_pct"] = np.array([pct.get(d, np.nan) for d in days], dtype=float)
    full = pd.Series(_bars_all("^GSPC"))
    sma200 = full.rolling(200).mean().to_dict()
    D["SPX_sma200"] = np.array([sma200.get(d, np.nan) for d in days], dtype=float)
    D["season"] = _season_up(full, days)
    for u in ("SPX", "RUT"):
        lr = np.diff(np.log(D[u]), prepend=np.nan)
        D[u + "_rv20"] = np.array([np.nanstd(lr[max(i - 19, 1):i + 1], ddof=1) * math.sqrt(252) if i >= 20 else np.nan for i in range(len(days))])
        D[u + "_sma20"] = np.array([D[u][max(i - 19, 0):i + 1].mean() for i in range(len(days))])
    return D


def base_vol(D, u, i, days):
    """ATM-level vol for date rows i at `days` calendar days (arrays broadcast together)."""
    i, days = np.broadcast_arrays(np.asarray(i), np.clip(np.asarray(days, dtype=float), 1, 365))
    W = D["W"][i]
    k = np.clip(np.searchsorted(TEN, days) - 1, 0, len(TEN) - 2)
    t0, t1 = TEN[k], TEN[k + 1]
    w0, w1 = np.take_along_axis(W, k[..., None], -1)[..., 0], np.take_along_axis(W, (k + 1)[..., None], -1)[..., 0]
    var = np.where(days <= TEN[0], W[..., 0] / TEN[0], (w0 + (w1 - w0) * (days - t0) / (t1 - t0)) / days)
    v = np.sqrt(np.maximum(var, 1e-6))
    return v * (D["rvx"][i] / D["vix"][i]) if u == "RUT" else v


def leg_iv(D, u, i, days, K, S=None):
    """Skew multiplier on the ATM-level vol, sticky moneyness. m is held inside the range the curve was fitted
    on (flat beyond its low point on the in-the-money side, and below m = -1.5), so crash days don't invent vols."""
    a, b, c = SKEW[u]
    T = np.maximum(days, 1) / 365
    m = np.clip(np.log(K / (D[u][i] if S is None else S)) / np.sqrt(T), -1.5, -b / (2 * c))
    return base_vol(D, u, i, days) * np.maximum(a + b * m + c * m * m, 0.3)


def value(D, u, idx, expiry, K, w):
    """Structure value (points) on date rows idx for legs K (n_legs,) with weights w, all expiring `expiry`
    (date or array per leg)."""
    exp = np.broadcast_to(np.asarray(expiry, dtype=object), K.shape)
    days = np.array([[(e - D["date"][i]).days for e in exp] for i in idx], dtype=float)  # (n, legs)
    I = np.asarray(idx)[:, None]
    iv = leg_iv(D, u, I, days, K[None, :])
    px = put_price(D[u][I], K[None, :], np.maximum(days, 0) / 365, iv)
    return (px * w).sum(axis=1), days


# ------------------------------------------------------------------ trades
COST_SCALE = 1.0  # 0 = no costs (for checks)


def _cost(u, legs, S0, D):
    """$ per lot per side, scaled to today's index level: option prices and spreads grow with the index, and at
    lower index levels you would trade more lots for the same capital."""
    return COST_SCALE * (COMM * legs + SLIP[u] * 100) * S0 / D[u][-1]


BWB_W = np.array([1.0, -2.0, 1.0])


def _bwb(D, u, i, days):
    """Your A14 shape around row i's close for `days` to expiry: strikes (upper, short, lower)."""
    up0, Uw, Lw = GEOM[u]
    S = D[u][i]
    sd = float(base_vol(D, u, i, days)) * SKEW[u][0] * math.sqrt(max(days, 1) / 365)
    up = S * (1 + up0 * sd)
    return np.array([up, up * (1 - Uw * sd), up * (1 - Uw * sd) - S * Lw * sd])


def _bwb_value(D, u, idx, exp, K):
    v, days = value(D, u, idx, exp, K, BWB_W)
    Uw_pts, Lw_pts = K[0] - K[1], K[1] - K[2]
    return np.clip(v, min(Uw_pts - Lw_pts, 0), Uw_pts), days  # a BWB is worth between its worst and best payoff


def _span(D, i0, exp):
    """Last row on or before expiry, or None when the path runs past the data."""
    j = i0
    while j + 1 < len(D["date"]) and D["date"][j + 1] <= exp:
        j += 1
    return None if (exp - D["date"][j]).days > 3 or j == i0 else j


def a14_paths(D, u, dte):
    """Every Friday entry: daily P&L % of risk until expiry, plus entry conditions."""
    out = []
    for i0, d0 in enumerate(D["date"]):
        if d0.weekday() != 4 or i0 < 21:
            continue
        exp = d0 + dt.timedelta(days=dte)
        j = _span(D, i0, exp)
        if j is None:
            continue
        S0 = D[u][i0]
        K = _bwb(D, u, i0, dte)
        idx = np.arange(i0, j + 1)
        v, days = _bwb_value(D, u, idx, exp, K)
        Uw_pts, Lw_pts = K[0] - K[1], K[1] - K[2]
        credit = -v[0]
        risk = max(Lw_pts - Uw_pts - credit, -credit, 0.05) * 100
        c = _cost(u, 4, S0, D)
        pnl = (v - v[0]) * 100 - 2 * c
        pnl[0] += c  # day 0: only the entry cost is sunk
        out.append({"i0": i0, "ret": 100 * pnl / risk, "dleft": days[:, 0], "held": np.array([(x - d0).days for x in D["date"][idx]]),
                    "credit": credit, "risk": risk, "cond": _cond(D, u, i0), "S": D[u][idx], "K": K})
    return out


def a14_managed(D, u, dte, tp=None, sl=None, time_dte=2, decide=-6, recenter=1.5, max_adj=9, min_dte=11, pace=None):
    """A14 with mechanical re-centering, the way the trade plan gates it: when the trade is red (or past the
    decide line) and the index has moved `recenter` % from the tent's centre, or it is at the decide line, close
    the BWB and open the same shape around today's close, same expiry. Allowed while more than `min_dte` days
    remain and fewer than `max_adj` adjustments are done; at the decide line without an allowed adjustment, exit.
    Never adjusts a trade at +3% or more. Each re-centre costs a combo side on 8 contracts. Returns
    (return % of the entry risk, days held, reason, adjustments) per Friday entry."""
    out = []
    for i0, d0 in enumerate(D["date"]):
        if d0.weekday() != 4 or i0 < 21:
            continue
        exp = d0 + dt.timedelta(days=dte)
        j = _span(D, i0, exp)
        if j is None:
            continue
        S0 = D[u][i0]
        K = _bwb(D, u, i0, dte)
        c4, c8 = _cost(u, 4, S0, D), _cost(u, 8, S0, D)
        v, days = _bwb_value(D, u, np.arange(i0, j + 1), exp, K)
        risk = max(K[1] - K[2] - (K[0] - K[1]) + v[0], v[0], 0.05) * 100
        banked, base, centre, start, n_adj = -c4, v[0], S0, i0, 0
        res = None
        while res is None:
            r = 100 * (banked + (v - base) * 100 - c4) / risk  # if closed at that close
            if len(v) == 1:
                res = (r[0], (D["date"][start] - d0).days, "expiry")
            for k in range(1, len(v)):  # row `start` was already checked (entry, or the re-centre close)
                i = start + k
                held = (D["date"][i] - d0).days
                dl = days[k, 0]
                p = r[k]
                if sl is not None and p <= -sl:
                    res = (p, held, "stop")
                elif tp is not None and p >= tp:
                    res = (p, held, "target")
                elif dl <= time_dte:
                    res = (p, held, "time")
                elif pace and held >= pace[0] and 0 <= p < pace[1] * held:
                    res = (p, held, "slow")
                elif i == j:
                    res = (p, held, "expiry")
                else:
                    at_line = decide is not None and p <= decide
                    off = recenter is not None and abs(D[u][i] / centre - 1) * 100 >= recenter
                    if at_line or off:
                        if dl >= min_dte and n_adj < max_adj and p < 3:
                            # close the old tent at this close, open a new one at the same expiry
                            banked += (v[k] - base) * 100 - c8
                            K = _bwb(D, u, i, dl)
                            v, days = _bwb_value(D, u, np.arange(i, j + 1), exp, K)
                            base, centre, start, n_adj = v[0], D[u][i], i, n_adj + 1
                            break
                        if at_line:
                            res = (p, held, "decide")
                if res:
                    break
        out.append((float(res[0]), max(int(res[1]), 1), res[2], n_adj))
    return out


def cal_paths(D, u="SPX", front=15, back=22):
    """TimeEdge: ATM put calendar, every weekday entry, P&L % of the debit until the front expiry."""
    out = []
    for i0, d0 in enumerate(D["date"]):
        if i0 < 21 or d0.weekday() > 4:
            continue
        ef, eb = d0 + dt.timedelta(days=front), d0 + dt.timedelta(days=back)
        j = i0
        while j + 1 < len(D["date"]) and D["date"][j + 1] <= ef:
            j += 1
        if (ef - D["date"][j]).days > 3 or j == i0:
            continue
        K = np.array([D[u][i0], D[u][i0]])
        idx = np.arange(i0, j + 1)
        v, days = value(D, u, idx, np.array([ef, eb], dtype=object), K, np.array([-1.0, 1.0]))
        v = np.maximum(v, 0)  # same strike: the later expiry is worth at least the earlier
        debit = v[0] * 100
        if debit <= 0:
            continue
        c = _cost(u, 2, D[u][i0], D)
        pnl = (v - v[0]) * 100 - 2 * c
        pnl[0] += c
        out.append({"i0": i0, "ret": 100 * pnl / debit, "dleft": days[:, 0], "held": np.array([(x - d0).days for x in D["date"][idx]]),
                    "debit": debit, "cond": _cond(D, u, i0)})
    return out


def _cut(v, edges, labels):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return labels[int(np.searchsorted(edges, v, side="right"))]


# condition buckets: key -> (tab, label, value from the _cond dict, edges, bucket labels)
COND = {
    "vix_band": ("Market", "VIX level", "vix", [15, 20, 30], ["<15", "15–20", "20–30", "30+"]),
    "spx200": ("Market", "SPX vs its 200-day average", "spx200_pct", [0], ["below", "above"]),
    "trend": ("Market", "Index vs its 20-day average", None, None, ["above", "below"]),
    "ivts_band": ("Term structure", "VIX/VIX3M", "ivts", None, ["steep", "normal", "flat", "backwardation"]),
    "front": ("Term structure", "VIX9D/VIX (front of the curve)", "front_r", [0.90, 1.0], ["<0.90", "0.90–1.00", "1.00+"]),
    "ivpct": ("Skew & IV", "Implied vol: VIX 1-year percentile", "vix_pct", [25, 50, 75], ["<25", "25–50", "50–75", "75+"]),
    "skew_b": ("Skew & IV", "SKEW index (tail skew)", "skew", [126, 142], ["<126", "126–142", "142+"]),
    "vvix_b": ("Skew & IV", "VVIX (vol of vol)", "vvix", [85, 100, 115], ["<85", "85–100", "100–115", "115+"]),
    "rvxs": ("Skew & IV", "RVX − VIX (RUT premium)", "rvx_spread", [3, 8], ["<3", "3–8", "8+"]),
    "vrp_b": ("Expected moves", "Implied minus realised vol (index IV − 20-day realised)", "vrp", [0, 4, 8], ["<0", "0–4", "4–8", "8+"]),
    "season": ("Seasonality", "Next 21 sessions: years up of the last 20", "season_up", [60, 75], ["<60%", "60–75%", "75%+"]),
}


def _cond(D, u, i):
    ivts = D["vix"][i] / D["vix3m"][i]
    vix = D["vix"][i] * 100
    rv = D[u + "_rv20"][i]
    iv = (D["rvx"][i] if u == "RUT" else D["vix"][i]) * 100
    raw = {"vix": vix, "spx200_pct": 100 * (D["SPX"][i] / D["SPX_sma200"][i] - 1), "front_r": D["vix9d_raw"][i] / D["vix"][i],
           "vix_pct": D["vix_pct"][i], "skew": D["skew"][i], "vvix": D["vvix"][i], "rvx_spread": 100 * (D["rvx"][i] - D["vix"][i]),
           "vrp": iv - 100 * rv, "season_up": D["season"][i]}
    raw = {k: (None if v is None or np.isnan(v) else round(float(v), 3)) for k, v in raw.items()}
    b = {k: _cut(raw[f], e, lab) for k, (_, _, f, e, lab) in COND.items() if e is not None}
    return {**b, "raw": raw, "date": D["days"][i], "year": D["days"][i][:4], "ivts": round(float(ivts), 3),
            "ivts_band": ivts_band(float(ivts))["band"], "vix": round(float(vix), 1),
            "trend": "above" if D[u][i] > D[u + "_sma20"][i] else "below",
            "vrp": None if np.isnan(rv) else round(float(vix - 100 * rv), 1)}


# ------------------------------------------------------------------ exits
def exit_at(p, tp=None, sl=None, time_dte=2, pace=None):
    """First close where a rule fires: (return %, days held, reason). Checked like the trade plan: stop, target,
    time stop, then pace = (from day held, % per day): a trade under that pace is closed at a close at or above 0."""
    r, dl, held = p["ret"], p["dleft"], p["held"]
    stop = r <= -sl if sl is not None else np.zeros(len(r), bool)
    tgt = r >= tp if tp is not None else np.zeros(len(r), bool)
    tim = dl <= time_dte
    slow = (held >= pace[0]) & (r < pace[1] * held) & (r >= 0) if pace else np.zeros(len(r), bool)
    hit = stop | tgt | tim | slow
    hit[0] = False
    if not hit.any():
        return float(r[-1]), max(int(held[-1]), 1), "expiry"
    k = int(np.argmax(hit))
    why = "stop" if stop[k] else "target" if tgt[k] else "time" if tim[k] else "slow"
    return float(r[k]), max(int(held[k]), 1), why


def summary(res):
    if not res:
        return None
    r = np.array([x[0] for x in res])
    d = np.array([x[1] for x in res])
    why = [x[2] for x in res]
    return {"n": len(r), "avg": float(r.mean()), "median": float(np.median(r)), "win": float((r > 0).mean()), "p5": float(np.percentile(r, 5)),
            "worst": float(r.min()), "days": float(d.mean()), "per_day": float(r.sum() / d.sum()),
            "stop": why.count("stop") / len(r), "target": why.count("target") / len(r)}


def _tp(dte):
    return 5 if dte <= 21 else 7


# exit rules compared (levels are % of risk; pace = from day 21, close a trade under 0.2%/day at the next close >= 0)
RULES = {
    "card": ("Card: stop −10%", lambda d: {"tp": _tp(d), "sl": 10, "time_dte": 2, "pace": (21, 0.2)}),
    "plan": ("Revised: stop −20%", lambda d: {"tp": _tp(d), "sl": 20, "time_dte": 2, "pace": (21, 0.2)}),
    "nostop": ("No stop", lambda d: {"tp": _tp(d), "sl": None, "time_dte": 2, "pace": (21, 0.2)}),
    "hold": ("Hold to 2 DTE", lambda d: {"tp": None, "sl": None, "time_dte": 2}),
}
CAL_RULE = {"tp": 5, "sl": 15, "time_dte": 1}  # TimeEdge card exits
CAL_GATES = {
    "all": ("Every weekday", lambda c: True),
    "old": ("Old gate: VIX/VIX3M 0.834–1.00", lambda c: 0.834 < c["ivts"] < 1),
    "new": ("New gate: VIX/VIX3M < 0.90 and SPX above its 20-day average", lambda c: c["ivts"] < 0.90 and c["trend"] == "above"),
    "steep": ("Steep contango only (≤ 0.834), the old 'avoid' zone", lambda c: c["ivts"] <= 0.834),
}
BANDS = ["steep", "normal", "flat", "backwardation"]


def plan_rule(dte):
    return RULES["plan"][1](dte)


def _sum(res, paths=None):
    """summary() plus the share of calendar years with a positive average and the share of trades losing over half."""
    s = summary(res)
    if not s:
        return None
    r = np.array([x[0] for x in res])
    s["big_loss"] = float((r < -50).mean())
    if paths is not None:
        g = {}
        for p, x in zip(paths, res):
            g.setdefault(p["cond"]["year"], []).append(x[0])
        s["years_pos"] = float(np.mean([np.mean(v) > 0 for v in g.values()]))
        s["years"] = len(g)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}


def _grid(paths, time_dte):
    g = []
    for tp in TPS:
        for sl in SLS:
            s = summary([exit_at(p, tp, sl, time_dte) for p in paths])
            g.append({"tp": tp, "sl": sl, **s})
    return g


def _by(paths, rule, key):
    groups = {}
    for p in paths:
        groups.setdefault(p["cond"][key], []).append(p)
    return {k: _sum([exit_at(p, **rule) for p in v], v) for k, v in sorted(groups.items())}


def _matrix(paths, rule):
    """Results per term-structure band x short-term trend (the decision matrix cells)."""
    return {b: {t: _sum([exit_at(p, **rule) for p in q], q) for t in ("above", "below")
                for q in [[p for p in paths if p["cond"]["ivts_band"] == b and p["cond"]["trend"] == t]] if q}
            for b in BANDS}


def _conds(paths, rule):
    """Results per bucket of every condition in COND, plus SKEW buckets inside a normal term structure."""
    res = [exit_at(p, **rule) for p in paths]
    groups = {}
    for p, r in zip(paths, res):
        c = p["cond"]
        for k in COND:
            if c.get(k) is not None:
                g = groups.setdefault(k, {}).setdefault(c[k], ([], []))
                g[0].append(r); g[1].append(p)
        if c["ivts_band"] == "normal" and c.get("skew_b"):
            g = groups.setdefault("normal_skew", {}).setdefault(c["skew_b"], ([], []))
            g[0].append(r); g[1].append(p)
    return {"all": _sum(res, paths), **{k: {b: _sum(r, q) for b, (r, q) in v.items()} for k, v in groups.items()}}


def conditions_now():
    """Today's reading and bucket of every condition, per index (same code as the backtest entries)."""
    D = data()
    i = len(D["days"]) - 1
    return {"date": D["days"][i], "SPX": _cond(D, "SPX", i), "RUT": _cond(D, "RUT", i)}


def _years(paths, rule):
    return _by(paths, rule, "year")


def _ivts_fine(paths, rule):
    """Results in finer VIX/VIX3M steps (where the 0.834 and 0.90 lines sit)."""
    edges = [0, 0.78, 0.81, 0.834, 0.86, 0.88, 0.90, 0.95, 1.0, 9]
    g = {}
    for p in paths:
        v = p["cond"]["ivts"]
        k = next(i for i in range(len(edges) - 1) if edges[i] <= v < edges[i + 1])
        g.setdefault(k, []).append(p)
    return [{"lo": edges[k], "hi": edges[k + 1], **_sum([exit_at(p, **rule) for p in v], v)} for k, v in sorted(g.items())]


# ------------------------------------------------------------------ run + cache
def run():
    D = load()
    out = {"version": VERSION, "built": dt.datetime.now().isoformat(timespec="seconds"), "from": D["days"][0], "to": D["days"][-1],
           "rules": {k: v[0] for k, v in RULES.items()}, "a14": {}, "odds": {}, "managed": {}, "cal": {}, "matrix": {}, "conds": {},
           "cond_defs": {k: {"tab": t, "label": lab, "buckets": b} for k, (t, lab, _, _, b) in COND.items()}}
    for u in ("SPX", "RUT"):
        rows, odds = [], {}
        for dte in A14_DTE:
            paths = a14_paths(D, u, dte)
            row = {"dte": dte, "n": len(paths), "credit": round(float(np.median([p["credit"] for p in paths])), 2),
                   "risk": round(float(np.median([p["risk"] for p in paths]))), "tp": _tp(dte)}
            for k, (_, rule) in RULES.items():
                row[k] = _sum([exit_at(p, **rule(dte)) for p in paths], paths)
            row["gated"] = {k: _sum([exit_at(p, **RULES[k][1](dte)) for p in q], q)
                            for k in ("card", "plan", "nostop") for q in [[p for p in paths if p["cond"]["ivts"] < 0.90]]}
            odds[str(dte)] = {"all": row["plan"], **_by(paths, plan_rule(dte), "ivts_band")}
            if dte == 45:
                out["matrix"][f"A14 {u}"] = {"dte": dte, "rule": "plan", "cells": _matrix(paths, plan_rule(dte))}
                out["conds"][f"A14 {u}"] = _conds(paths, plan_rule(dte))
            if dte in (21, 45):
                row["bands"] = {k: _by(paths, RULES[k][1](dte), "ivts_band") for k in ("card", "plan", "nostop")}
                row["trend"] = _by(paths, plan_rule(dte), "trend")
                nr = RULES["nostop"][1](dte)
                row["worst"] = [{"date": p["cond"]["date"], "ret": round(exit_at(p, **nr)[0], 1), "vix": p["cond"]["vix"], "ivts": p["cond"]["ivts"],
                                 "band": p["cond"]["ivts_band"], "trend": p["cond"]["trend"]}
                                for p in sorted(paths, key=lambda p: exit_at(p, **nr)[0])[:10]]
            rows.append(row)
        out["a14"][u] = rows
        out["odds"][u] = odds
    for u, dte in (("SPX", 45), ("RUT", 60)):
        tp = _tp(dte)
        var = {"static": ("No adjustments, stop −10%", dict(tp=tp, sl=10, decide=None, recenter=None, max_adj=0)),
               "decide": ("Re-centre at the −6% decide line, stop −10%", dict(tp=tp, sl=10, decide=-6, recenter=None)),
               "move": ("Re-centre on every 1.5% move, stop −20%", dict(tp=tp, sl=20, decide=-10, recenter=1.5)),
               "move_nostop": ("Re-centre on every 1.5% move, no stop", dict(tp=tp, sl=None, decide=None, recenter=1.5))}
        m = {}
        for k, (label, kw) in var.items():
            res = a14_managed(D, u, dte, pace=(21, 0.2), **kw)
            m[k] = {"label": label, **_sum([r[:3] for r in res]), "adj": round(float(np.mean([r[3] for r in res])), 1)}
        out["managed"][f"{u} {dte}"] = m
    for u in ("SPX", "RUT"):
        cpu = cal_paths(D, u)
        out["matrix"][f"Calendar {u}"] = {"rule": CAL_RULE, "cells": _matrix(cpu, CAL_RULE)}
        out["conds"][f"Calendar {u}"] = _conds(cpu, CAL_RULE)
    cp = cal_paths(D, "SPX")
    out["cal"] = {"rule": CAL_RULE, "n": len(cp), "debit": round(float(np.median([p["debit"] for p in cp]))),
                  "fine": _ivts_fine(cp, CAL_RULE), "trend": _by(cp, CAL_RULE, "trend"), "vix": _by(cp, CAL_RULE, "vix_band"),
                  "gates": {k: {"label": lab, **_sum([exit_at(p, **CAL_RULE) for p in q], q)}
                            for k, (lab, f) in CAL_GATES.items() for q in [[p for p in cp if f(p["cond"])]]},
                  "june": [{"date": p["cond"]["date"], "ivts": p["cond"]["ivts"], "ret": round(exit_at(p, **CAL_RULE)[0], 1), "why": exit_at(p, **CAL_RULE)[2]}
                           for p in cp if "2026-05-28" <= p["cond"]["date"] <= "2026-06-12"]}
    return out


# ------------------------------------------------------------------ any BWB shape, for the A14 scanner
_DATA = {"key": None, "D": None}
_SCORE = {}
_data_lock = threading.Lock()


def data():
    """load(), kept until the next SPX close."""
    with _data_lock:
        k = _last_close()
        if _DATA["key"] != k or _DATA["D"] is None:
            D = load()
            D["ord"] = np.array([d.toordinal() for d in D["date"]])
            _DATA.update(key=k, D=D)
            _SCORE.clear()
        return _DATA["D"]


def sd_now(D, u, dte):
    """Today's model 1-sd move to expiry (fraction), the unit the shapes are scaled in."""
    return float(base_vol(D, u, len(D["days"]) - 1, dte)) * SKEW[u][0] * math.sqrt(dte / 365)


def shape_score(D, u, dte, x, rule=None):
    """Replay a put BWB with strikes at ln(K/S) = x * sd (x = upper, short, lower in model sd units) on every
    Friday since 2009 at the same DTE, with the trade-plan exits. Vectorised over all entries. Returns a summary
    for all entries and for each VIX/VIX3M band at entry."""
    key = (u, int(dte), tuple(round(float(v), 2) for v in x))
    if key in _SCORE:
        return _SCORE[key]
    rule = rule or plan_rule(dte)
    o, n = D["ord"], len(D["ord"])
    i0 = np.array([i for i, d in enumerate(D["date"]) if d.weekday() == 4 and i >= 21])
    exp = o[i0] + dte
    j = np.searchsorted(o, exp, side="right") - 1
    keep = (j > i0) & (exp - o[np.minimum(j, n - 1)] <= 3) & (exp <= o[-1] + 3) & (j < n)
    keep &= exp <= o[-1]
    i0, exp, j = i0[keep], exp[keep], j[keep]
    ln = j - i0 + 1
    E = np.repeat(np.arange(len(i0)), ln)
    first = np.concatenate([[0], np.cumsum(ln)[:-1]])
    I = i0[E] + (np.arange(len(E)) - first[E])
    days = (exp[E] - o[I]).astype(float)
    S0 = D[u][i0]
    sd = base_vol(D, u, i0, dte) * SKEW[u][0] * math.sqrt(dte / 365)
    K = S0[:, None] * np.exp(np.asarray(x, dtype=float)[None, :] * sd[:, None])  # (entries, 3)
    Ke = K[E]
    iv = leg_iv(D, u, I[:, None], days[:, None], Ke)
    v = (put_price(D[u][I][:, None], Ke, np.maximum(days, 0)[:, None] / 365, iv) * BWB_W).sum(axis=1)
    Uw, Lw = K[:, 0] - K[:, 1], K[:, 1] - K[:, 2]
    v = np.clip(v, np.minimum(Uw - Lw, 0)[E], Uw[E])
    v0 = v[first]
    risk = np.maximum.reduce([Lw - Uw + v0, v0, np.full(len(v0), 0.05)]) * 100
    c = COST_SCALE * (COMM * 4 + SLIP[u] * 100) * S0 / D[u][-1]
    pnl = (v - v0[E]) * 100 - 2 * c[E]
    pnl[first] += c
    r = 100 * pnl / risk[E]
    held = (o[I] - o[i0][E]).astype(float)
    tp, sl, tdte, pace = rule.get("tp"), rule.get("sl"), rule.get("time_dte", 2), rule.get("pace")
    hit = days <= tdte
    if tp is not None:
        hit |= r >= tp
    if sl is not None:
        hit |= r <= -sl
    if pace:
        hit |= (held >= pace[0]) & (r < pace[1] * held) & (r >= 0)
    hit[first] = False
    last = first + ln - 1
    hit[last] = True
    hi = np.flatnonzero(hit)
    ue, ix = np.unique(E[hi], return_index=True)
    k = hi[ix]
    ret, dh = r[k], np.maximum(held[k], 1)
    why = np.where((sl is not None) & (ret <= -(sl or 0)), "stop", np.where((tp is not None) & (ret >= (tp or 1e9)), "target", "other"))
    ivts = D["vix"][i0] / D["vix3m"][i0]
    bands = np.array([ivts_band(float(q))["band"] for q in ivts])

    def summ(m):
        if m.sum() < 20:
            return None
        rr, dd = ret[m], dh[m]
        return {"n": int(m.sum()), "avg": round(float(rr.mean()), 2), "win": round(float((rr > 0).mean()), 3),
                "p_target": round(float((why[m] == "target").mean()), 3), "p_stop": round(float((why[m] == "stop").mean()), 3),
                "days": round(float(dd.mean()), 1), "per_day": round(float(rr.sum() / dd.sum()), 3), "p5": round(float(np.percentile(rr, 5)), 1),
                "worst": round(float(rr.min()), 1), "big_loss": round(float((rr < -50).mean()), 3)}
    out = {"all": summ(np.ones(len(ret), bool)), **{b: summ(bands == b) for b in BANDS}, "rule": {k2: v2 for k2, v2 in rule.items()}}
    _SCORE[key] = out
    return out


def _last_close():
    return (db.query("SELECT MAX(date) d FROM bars_daily WHERE symbol='^GSPC'") or [{}])[0].get("d")


def cached():
    """The last stored results, without starting a computation (for notes that must not wait)."""
    raw = db.get_meta("backtest")
    cur = json.loads(raw) if raw else None
    return cur if cur and cur.get("version") == VERSION else None


def results(force=False):
    """Cached until a new SPX close arrives; recomputed in the background (about 10 seconds)."""
    raw = db.get_meta("backtest")
    cur = json.loads(raw) if raw else None
    fresh = cur and cur.get("version") == VERSION
    if fresh and cur.get("src") == _last_close() and not force:
        return cur
    if not status["running"] and not (status["error"] and not force):
        threading.Thread(target=_compute, daemon=True).start()
    return cur if fresh else {"running": status["running"] or not status["error"], "error": status["error"]}


def _compute():
    if not _lock.acquire(blocking=False):
        return
    status.update(running=True, error=None)
    try:
        src = _last_close()
        db.set_meta("backtest", json.dumps({**run(), "src": src}, default=float))
    except Exception as e:
        status["error"] = str(e)
    finally:
        status["running"] = False
        _lock.release()
