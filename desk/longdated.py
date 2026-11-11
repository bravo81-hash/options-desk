"""The 130-day structure (the user's idea of 12 Nov 2026): an SPX put butterfly about 130 days out (long the 40-delta put, short two
30-delta puts, long one the same distance below), a short 30-delta call in the same expiry, and one long call in the next monthly at
the strike that brings the whole position to zero delta. In practice: a put butterfly plus a call calendar.

Priced each day from the recorded surface (one smile per expiry, Black-76 off each expiry's own forward), so strikes between the
recorded ones are interpolated: these are model prices, not quotes. What moves it most is not theta but (1) the gap between the two
expiries' implied vols, (2) put skew. Both are tracked here against their own short history and against long CBOE stand-ins
(VIX6M less VIX3M since 2009, the SKEW index). A reference for timing: nothing here is a rule, a size or an order."""
import datetime as dt
import math

import numpy as np

from . import db
from .a14 import _ncdf, put_price

FRONT, FRONT_LO, FRONT_HI = 130, 105, 155  # days to the butterfly's expiry: the monthly nearest FRONT inside the window
BACK_MIN, BACK_MAX = 20, 45  # the long call's expiry, days after the front one
D_UP, D_SHORT, D_CALL = 0.40, 0.30, 0.30
STEP = 25.0
AHEAD = 21  # sessions: how far the stand-ins are followed after each day
_cache = {}


def monthly(d):
    """A standard monthly: the third Friday, or the Thursday before it (how IB dates the AM-settled SPX monthlies)."""
    return (d.weekday() == 4 and 15 <= d.day <= 21) or (d.weekday() == 3 and 14 <= d.day <= 20)


def smile(rows):
    """{F, T, dte, ks, ivs} from one expiry's recorded quotes: the out-of-the-money IVs the recorder fitted."""
    pts = {}
    for r in rows:
        if r.get("iv"):
            pts.setdefault(r["strike"], []).append(r["iv"])
    if len(pts) < 5:
        return None
    ks = np.array(sorted(pts))
    d = rows[0]["dte"]
    return {"F": next((r["fwd"] for r in rows if r.get("fwd")), None), "dte": d, "T": max(d, 0.5) / 365.0, "ks": ks, "ivs": np.array([float(np.mean(pts[k])) for k in ks])}


def iv_at(sm, k):
    return float(np.interp(k, sm["ks"], sm["ivs"]))  # flat beyond the recorded wings


def price(F, K, T, iv, right):
    p = float(put_price(F, K, max(T, 1e-6), max(iv, 1e-4)))
    return p if right == "P" else p + F - K


def delta(F, K, T, iv, right):
    d1 = (math.log(F / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    c = float(_ncdf(d1))
    return c if right == "C" else c - 1.0


def strike_at(sm, target, right):
    """The 25-point strike whose delta is nearest the target, inside the recorded range."""
    grid = np.arange(math.ceil(sm["ks"][0] / STEP) * STEP, sm["ks"][-1] + 1, STEP)
    return float(min(grid, key=lambda k: abs(abs(delta(sm["F"], k, sm["T"], iv_at(sm, k), right)) - target)))


def build(front, back=None):
    """The structure on one day's smiles. back None: the long call is priced on the front smile's IV at its strike (an estimate)."""
    F1, T1 = front["F"], front["T"]
    up, sh, cs = strike_at(front, D_UP, "P"), strike_at(front, D_SHORT, "P"), strike_at(front, D_CALL, "C")
    if not up > sh:
        return None
    lo = sh - (up - sh)
    est = back is None
    if est:
        T2 = T1 + 28 / 365.0
        back = {"F": F1, "T": T2, "dte": front["dte"] + 28, "ks": front["ks"], "ivs": front["ivs"]}
    F2, T2 = back["F"], back["T"]
    base = [(1, up, "P", 0), (-2, sh, "P", 0), (1, lo, "P", 0), (-1, cs, "C", 0)]

    def val(legs, x=1.0, days=0.0, dv1=0.0, dv2=0.0, only=None):
        """US$ a lot with the index at x times today's level, `days` later, front IVs + dv1 and back IVs + dv2 (each strike keeps its IV)."""
        tot = 0.0
        for q, k, r, m in legs:
            sm, F, T, dv = (back, F2, T2, dv2) if m else (front, F1, T1, dv1)
            bump = dv if only is None or only == k else 0.0
            tot += q * price(F * x, k, T - days / 365.0, iv_at(sm, k) + bump, r)
        return tot * 100

    dl = lambda legs: (val(legs, 1.0005) - val(legs, 0.9995)) / (0.001 * F1)  # noqa: E731
    grid = np.arange(math.ceil(max(back["ks"][0], cs - 300) / STEP) * STEP, min(back["ks"][-1], cs + 500) + 1, STEP)
    if not len(grid):
        return None
    lc = float(min(grid, key=lambda k: abs(dl(base + [(1, k, "C", 1)]))))
    legs = base + [(1, lc, "C", 1)]
    v0 = val(legs)
    fly, cal = base[:3], [base[3], legs[4]]
    xs = [round(x, 4) for x in np.linspace(0.86, 1.12, 53)]
    left = max(front["dte"] - 0.01, 0)
    return {"front_dte": front["dte"], "back_dte": back["dte"], "back_est": est, "spot_ref": round(F1, 1),
            "legs": [{"q": q, "strike": k, "right": r, "back": bool(m), "iv": round(100 * iv_at(back if m else front, k), 2),
                      "delta": round(delta(F2 if m else F1, k, T2 if m else T1, iv_at(back if m else front, k), r), 3)} for q, k, r, m in legs],
            "cost": round(v0), "cost_fly": round(val(fly)), "cost_cal": round(val(cal)), "delta": round(dl(legs), 2),
            "theta": round(val(legs, days=1) - v0, 1), "theta_pct": round(100 * (val(legs, days=1) - v0) / v0, 3) if v0 > 0 else None,
            "vega": round(val(legs, dv1=0.01, dv2=0.01) - v0), "front_up1": round(val(legs, dv1=0.01) - v0), "back_up1": round(val(legs, dv2=0.01) - v0),
            "skew_up1": round(val(legs, dv1=0.01, only=lo) - v0),
            "gap": None if est else round(100 * (iv_at(back, lc) - iv_at(front, cs)), 2),  # back less front IV at the call strikes, vol points
            "skew": round(100 * (iv_at(front, lo) - iv_at(front, up)), 2),  # IV at the lower long less the upper long, vol points
            "max_fly": round((up - sh) * 100 - val(fly)),
            "scen": {"down5": round(val(legs, 0.95, dv1=0.05, dv2=0.05) - v0), "up5_30": round(val(legs, 1.05, 30, -0.03, -0.03) - v0), "flat30": round(val(legs, days=30) - v0)},
            "curve": {"xs": [round(F1 * x) for x in xs], "now": [round(val(legs, x) - v0) for x in xs], "d30": [round(val(legs, x, 30) - v0) for x in xs],
                      "d60": [round(val(legs, x, 60) - v0) for x in xs], "exp": [round(val(legs, x, left) - v0) for x in xs]}}


def _day(snap_id):
    """(front smile, back smile or None) from one recorded snapshot."""
    by = {}
    for r in db.query("SELECT expiry, dte, strike, right, iv, fwd FROM quotes WHERE snap_id=? AND dte>=? AND dte<=?", (snap_id, FRONT_LO, FRONT_HI + BACK_MAX)):
        if monthly(dt.datetime.strptime(r["expiry"], "%Y%m%d").date()):
            by.setdefault(r["expiry"], []).append(dict(r))
    sm = {e: s for e, s in ((e, smile(rows)) for e, rows in by.items()) if s and s["F"]}
    fronts = [e for e, s in sm.items() if FRONT_LO <= s["dte"] <= FRONT_HI]
    if not fronts:
        return None, None, None, None
    f = min(fronts, key=lambda e: abs(sm[e]["dte"] - FRONT))
    backs = [e for e, s in sm.items() if BACK_MIN <= s["dte"] - sm[f]["dte"] <= BACK_MAX]
    b = min(backs, key=lambda e: sm[e]["dte"]) if backs else None
    return f, sm[f], b, sm.get(b)


def history():
    """One row per recorded session: the structure rebuilt on that day's surface."""
    out = []
    for s in db.query("SELECT date, MAX(id) id, spot FROM snaps WHERE symbol='SPX' GROUP BY date ORDER BY date"):
        if s["id"] in _cache:
            row = _cache[s["id"]]
        else:
            f, fs, b, bs = _day(s["id"])
            B = build(fs, bs) if fs else None
            row = None if not B else {"date": s["date"], "spot": s["spot"], "front": f, "back": b, **{k: B[k] for k in ("front_dte", "cost", "theta", "theta_pct", "skew", "gap", "back_est", "vega")}}
            _cache[s["id"]] = row
        if row:
            out.append(row)
    return out


def _pct(vals, v):
    return round(100 * sum(1 for x in vals if x <= v) / len(vals)) if vals and v is not None else None


def standins():
    """The long CBOE histories that stand in for the two drivers: VIX6M less VIX3M (the slope of implied vol from 3 to 6 months) for
    the expiry gap, and the SKEW index for put skew. For each: today, its percentile, and what it did over the next AHEAD sessions
    after days in its lowest, middle and highest third, which is the only reason a low reading would matter."""
    from .history import series
    v3, v6, sk = series("VIX3M", "2009-09-18"), series("VIX6M", "2009-09-18"), series("SKEW", "2009-09-18")
    out = {}
    for name, s in (("slope", (v6 - v3).dropna()), ("skew", sk.dropna())):
        if len(s) < 500:
            continue
        v = s.values
        lo, hi = np.percentile(v, [100 / 3, 200 / 3])
        chg = v[AHEAD:] - v[:-AHEAD]
        base = v[:-AHEAD]
        third = lambda m: {"n": int(m.sum()), "chg": round(float(chg[m].mean()), 2), "up": round(100 * float((chg[m] > 0).mean()))}  # noqa: E731
        out[name] = {"now": round(float(v[-1]), 2), "date": s.index[-1], "since": s.index[0], "pct": _pct(list(v), float(v[-1])), "pct_1y": _pct(list(v[-252:]), float(v[-1])),
                     "cuts": [round(float(lo), 2), round(float(hi), 2)], "after": {"low": third(base <= lo), "mid": third((base > lo) & (base <= hi)), "high": third(base > hi)},
                     "series": [{"d": d, "v": round(float(x), 2)} for d, x in list(s.items())[-504:]]}
    return out


def state():
    """Everything the panel shows: today's structure, its history on the recorded surfaces, the stand-ins, and three plain readings."""
    H = history()
    last = db.query("SELECT id, date, ts, spot FROM snaps WHERE symbol='SPX' ORDER BY date DESC, id DESC LIMIT 1")
    if not last:
        return {"error": "No SPX surface recorded yet."}
    f, fs, b, bs = _day(last[0]["id"])
    if not fs:
        return {"error": f"No monthly expiry {FRONT_LO}–{FRONT_HI} days out in the last recording."}
    B = build(fs, bs)
    if not B:
        return {"error": "The recorded strikes don't reach the 40- and 30-delta puts on that expiry."}
    S = standins()
    hs = lambda k: [r[k] for r in H if r.get(k) is not None]  # noqa: E731
    own = {k: {"now": B.get(k), "n": len(hs(k)), "pct": _pct(hs(k), B.get(k))} for k in ("skew", "gap", "theta_pct")}
    return {"date": last[0]["date"], "ts": last[0]["ts"], "spot": last[0]["spot"], "front": f, "back": b, "build": B, "history": H, "standins": S, "own": own,
            "defs": {"front": FRONT, "lo": FRONT_LO, "hi": FRONT_HI, "d_up": D_UP, "d_short": D_SHORT, "d_call": D_CALL, "ahead": AHEAD}}
