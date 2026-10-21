"""VIX conditions: which VIX / SPX / RUT / credit conditions are active now, what followed them historically,
and what that implies for size (full / reduce / half / stand aside) and structure choice.

History: SPX closes since 1990 (yfinance ^GSPC), VIX family from index_daily (CBOE + IBKR; VIX3M from 2009,
VIX9D from 2011, VVIX from 2006, RVX from 2009), RUT (^RUT), HYG total-return (dividend-adjusted).
Forward outcome over the next 21 sessions: SPX return, % up, chance of a >=5% drawdown at some point,
VIX change over 10 sessions, RUT return. Event-type conditions are de-clustered (one count per 5 sessions).
The historical table is rebuilt once a day; the "active now" checks use the latest (live, via IBKR) closes.
"""
import datetime as dt
import json

import numpy as np
import pandas as pd

from . import db
from .history import series

# id, kind, label, what to do
CONDITIONS = [
    ("hyg_crash", "sitout", "HYG down 1.5% or more today (credit crash override)",
     "No new short-put risk. Hedge or hold cash until credit stabilises."),
    ("vix40", "sitout", "VIX 40 or higher",
     "Only very small size, or wait for the term structure to come out of backwardation."),
    ("backward", "caution", "VIX/VIX3M at or above 1 (backwardation)",
     "Premium is fat but the next leg down is common. Wait for it to end before adding A14s; calendars invert, stand down."),
    ("neg_vrp", "caution", "VIX below 20-day realised vol (negative premium)",
     "Options are cheap for how much the market is moving. Reduce short-vega size."),
    ("below200", "caution", "SPX below its 200-day average",
     "Drawdown risk doubles. Half size on A14s or move the shorts further out."),
    ("hi_vix_up", "caution", "SPX within 1% of a 52-week high while VIX jumps 5%+",
     "Protection being bought into highs. Don't add bullish exposure; neutral or long-vega structures fit better."),
    ("vvix_calm", "caution", "VVIX 110+ while VIX is under 18",
     "A spike is being priced in VIX options. Don't sell cheap vega; calendars (long vega) fit better."),
    ("complacent", "caution", "SPX down 1%+ but VIX flat or lower",
     "A complacent sell-off. Not a dip to sell puts into."),
    ("front_inv", "caution", "VIX9D at or above VIX (near-term fear)",
     "Wait for VIX9D to drop back below VIX before opening A14s."),
    ("rvx_narrow", "caution", "RVX less than 3 pts above VIX (thin RUT premium)",
     "RUT premium barely pays: prefer SPX over RUT for new trades."),
    ("back_end", "take", "Backwardation just ended (VIX/VIX3M back below 0.97)",
     "Historically the best re-entry after a scare: sell put premium (A14) as the curve normalises."),
    ("rich_vrp", "take", "VIX 8+ pts above 20-day realised vol (rich premium)",
     "Best backdrop for premium selling: A14 / short premium at normal size."),
    ("rvx_wide", "take", "RVX 8+ pts above VIX (rich RUT premium)",
     "Favours RUT A14s over SPX."),
    ("hv7", "take", "HV7: SPX down 2%+ and VIX 27+ today",
     "Your HV7 entry (3:45–4:00 pm), small size: the next 5% leg down still followed often."),
    ("vix_up5", "take", "VIX up 5 days in a row",
     "Usually a buying opportunity rather than a warning."),
]
BUCKETS = [(0, 12), (12, 15), (15, 20), (20, 25), (25, 30), (30, 40), (40, 200)]
EVENTS = {"back_end", "hi_vix_up", "vvix_calm", "complacent", "hv7", "vix_up5", "hyg_crash"}


def _ser(name):
    s = series(name).dropna()
    s.index = pd.to_datetime(s.index)
    return s


def _yf(sym, adjusted):
    from .market import fetch_yf, fetch_yf_max
    fetch_yf_max([sym])
    key = sym + "|adj" if adjusted else sym
    rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=? ORDER BY date", (key,))
    s = pd.Series({r["date"]: r["c"] for r in rows}, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.dropna()


def frame():
    spx_y = _yf("^GSPC", False)
    spx_ib = _ser("SPX")  # IBKR daily incl. today's live bar
    spx = pd.concat([spx_y[spx_y.index < spx_ib.index.min()] if len(spx_ib) else spx_y, spx_ib]) if len(spx_ib) else spx_y
    spx = spx[~spx.index.duplicated(keep="last")].sort_index()
    rut_ib, rut_y = _ser("RUT"), _yf("^RUT", False)
    rut = pd.concat([rut_y[rut_y.index < rut_ib.index.min()], rut_ib]) if len(rut_ib) else rut_y
    rut = rut[~rut.index.duplicated(keep="last")].sort_index()
    df = pd.DataFrame({"spx": spx, "vix": _ser("VIX")}).dropna()
    df = df[df.index >= "1990-01-02"]
    for k, s in (("rut", rut), ("v3m", _ser("VIX3M")), ("v9d", _ser("VIX9D")), ("vvix", _ser("VVIX")), ("rvx", _ser("RVX")),
                 ("hyg", _yf("HYG", True))):
        df[k] = s.reindex(df.index)
    # read every series on the same date: stop at the latest date VIX3M has (a partial day can carry VIX only)
    lv = df["v3m"].last_valid_index()
    if lv is not None:
        df = df[df.index <= lv].copy()
    df["r"] = df.spx.pct_change() * 100
    df["dv"] = df.vix.diff()
    df["dvp"] = df.vix.pct_change() * 100
    lr = np.log(df.spx).diff()
    df["rv20"] = lr.rolling(20).std() * np.sqrt(252) * 100
    df["sma200"] = df.spx.rolling(200).mean()
    df["hi252"] = df.spx.rolling(252).max()
    df["ivts"] = df.vix / df.v3m
    df["hyg_r"] = df.hyg.pct_change() * 100
    df["rvx_spread"] = df.rvx - df.vix
    fut = df.spx.shift(-21)
    df["f21"] = (fut / df.spx - 1) * 100
    mins = pd.concat([df.spx.shift(-k) for k in range(1, 22)], axis=1).min(axis=1)
    df["dd21"] = (mins / df.spx - 1) * 100
    df["vf10"] = df.vix.shift(-10) - df.vix
    df["rf21"] = (df.rut.shift(-21) / df.rut - 1) * 100
    return df


def masks(df):
    return {
        "hyg_crash": df.hyg_r <= -1.5,
        "vix40": df.vix >= 40,
        "backward": df.ivts >= 1.0,
        "neg_vrp": df.vix < df.rv20,
        "below200": df.spx < df.sma200,
        "hi_vix_up": (df.spx >= df.hi252 * 0.99) & (df.dvp >= 5),
        "vvix_calm": (df.vvix >= 110) & (df.vix < 18),
        "complacent": (df.r <= -1) & (df.dvp <= 0),
        "front_inv": df.v9d >= df.vix,
        "rvx_narrow": df.rvx_spread <= 3,
        "back_end": (df.ivts.shift(1) >= 1.0) & (df.ivts < 0.97),
        "rich_vrp": (df.vix - df.rv20) >= 8,
        "rvx_wide": df.rvx_spread >= 8,
        "hv7": (df.r <= -2) & (df.vix >= 27),
        "vix_up5": (df.dv > 0).rolling(5).sum() == 5,
    }


def _declump(m, gap=5):
    idx = np.where(m.fillna(False).values)[0]
    keep, last = [], -10 ** 9
    for i in idx:
        if i - last > gap:
            keep.append(i)
            last = i
    out = pd.Series(False, index=m.index)
    out.iloc[keep] = True
    return out


def _stats(df, m):
    x = df[m.fillna(False)].dropna(subset=["f21"])
    if len(x) < 5:
        return None
    return {"n": int(len(x)), "ret21": float(x.f21.mean()), "up21": float((x.f21 > 0).mean() * 100),
            "dd5": float((x.dd21 <= -5).mean() * 100), "dd3": float((x.dd21 <= -3).mean() * 100),
            "vix10": float(x.vf10.mean()), "rut21": float(x.rf21.mean()) if x.rf21.notna().any() else None,
            "since": x.index[0].date().isoformat()}


def history_stats(df):
    key = f"vixcond:{dt.date.today().isoformat()}"
    cached = db.get_meta(key)
    if cached:
        return json.loads(cached)
    ms = masks(df)
    out = {"base": _stats(df, pd.Series(True, index=df.index)), "cond": {}, "bucket": {}}
    for cid, *_ in CONDITIONS:
        m = ms[cid]
        out["cond"][cid] = _stats(df, _declump(m) if cid in EVENTS else m)
    for lo, hi in BUCKETS:
        out["bucket"][f"{lo}-{hi}"] = _stats(df, (df.vix >= lo) & (df.vix < hi))
    db.set_meta(key, json.dumps(out))
    return out


def now():
    df = frame()
    hs = history_stats(df)
    ms = masks(df)
    last = df.iloc[-1]
    rows = []
    for cid, kind, label, advice in CONDITIONS:
        v = ms[cid].iloc[-1]
        rows.append({"id": cid, "kind": kind, "label": label, "advice": advice, "active": bool(v) if pd.notna(v) else False,
                     "stats": hs["cond"].get(cid)})
    lo, hi = next((b for b in BUCKETS if b[0] <= last.vix < b[1]), BUCKETS[-1])
    bucket = {"range": f"{lo}–{hi if hi < 200 else '+'}", "stats": hs["bucket"].get(f"{lo}-{hi}")}
    active = [r for r in rows if r["active"]]
    sit = [r for r in active if r["kind"] == "sitout"]
    cau = [r for r in active if r["kind"] == "caution"]
    take = [r for r in active if r["kind"] == "take"]
    bdd = (bucket["stats"] or {}).get("dd5") or 0
    if sit:
        size, why = "Stand aside", "a sit-out condition is active"
    elif len(cau) >= 2 or bdd >= 25:
        size, why = "Half size", f"{len(cau)} caution conditions" if len(cau) >= 2 else f"VIX {bucket['range']}: a 5% drawdown followed {bdd:.0f}% of the time"
    elif cau:
        size, why = "Reduce about a quarter", "one caution condition"
    else:
        size, why = "Full size", "no caution conditions"
    # timing patterns (whole history): weekday and monthly-expiry week
    today = dt.date.today()
    tnotes = []
    if today.weekday() == 0:
        tnotes.append("Monday: VIX has risen on 62% of Mondays (+0.36 pts on average) — a better day to sell vega than Friday's close.")
    if today.weekday() == 4:
        tnotes.append("Friday: VIX has fallen on 63% of Fridays — cheapest point of the week to buy vega (calendars); poorer for selling it.")
    third_fri = next(d for d in (dt.date(today.year, today.month, x) for x in range(15, 22)) if d.weekday() == 4)
    if 0 <= (third_fri - today).days <= 4:
        tnotes.append("Monthly-expiry week: VIX has fallen into expiry on 61% of these weeks (−0.5 pts on average) — helps short vega, hurts fresh calendars.")
    readings = {"date": df.index[-1].date().isoformat(), "vix": float(last.vix), "ivts": float(last.ivts) if pd.notna(last.ivts) else None,
                "vrp": float(last.vix - last.rv20) if pd.notna(last.rv20) else None, "rv20": float(last.rv20) if pd.notna(last.rv20) else None,
                "vvix": float(last.vvix) if pd.notna(last.vvix) else None, "r9": float(last.v9d / last.vix) if pd.notna(last.v9d) else None,
                "rvx_spread": float(last.rvx_spread) if pd.notna(last.rvx_spread) else None, "spx_r": float(last.r),
                "vs200": float(100 * (last.spx / last.sma200 - 1)) if pd.notna(last.sma200) else None,
                "hyg_r": float(last.hyg_r) if pd.notna(last.hyg_r) else None}
    prefer = None
    if readings["rvx_spread"] is not None:
        prefer = "RUT" if readings["rvx_spread"] >= 8 else "SPX" if readings["rvx_spread"] <= 3 else None
    return {"readings": readings, "conditions": rows, "bucket": bucket, "base": hs["base"], "size": size, "size_why": why,
            "timing": tnotes, "prefer": prefer}
