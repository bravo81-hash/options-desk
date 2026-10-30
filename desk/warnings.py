"""Market Warnings v2 (the Market tab's six warnings, same rules as the Pine script) and the Regime box's
offense-vs-defense rotation, computed server-side with their history, so the readiness verdict can weigh them.

Tested 2010+ (VIX3M and ES volume era) on what followed over 21 sessions. More warnings = a bigger chance of
a 5% drawdown (0 -> ~11%, 3+ -> ~24%), but forward returns are not worse: warnings measure how rough the
next weeks are likely to be, not direction. Breadth has only ~1 year of computed history, so it is shown but
the risk estimate uses the five tested warnings.
"""
import datetime as dt
import json

import numpy as np
import pandas as pd

from . import db
from .history import series
from .market import fetch_yf, fetch_yf_max


def _bars(sym, adj=False, period="max"):
    fetch_yf_max([sym])
    key = sym + "|adj" if adj else sym
    rows = db.query("SELECT date, o, h, l, c, v FROM bars_daily WHERE symbol=? ORDER BY date", (key,))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.pop("date"))
    return df


def _ser(n):
    s = series(n).dropna()
    s.index = pd.to_datetime(s.index)
    return s


def _asof(s, idx):
    """Like the page: the latest reading on or before each date, at most 3 sessions old (a late series can miss a bar)."""
    return s.reindex(idx.union(s.index)).ffill(limit=3).reindex(idx)


def _ivts(vix, v3, idx):
    """VIX/VIX3M from one day: CBOE's files land hours apart, and a ratio across two days is a wrong number."""
    return _asof((vix / v3).dropna(), idx)


def _ema_like(a, n, alpha):
    out = np.full(len(a), np.nan)
    prev, run, s, vals = None, 0, 0.0, a.values
    for i, x in enumerate(vals):
        if prev is None:
            if np.isnan(x):
                run, s = 0, 0.0
                continue
            run += 1
            s += x
            if run > n:
                s -= vals[i - n]
            if run >= n:
                prev = s / n
                out[i] = prev
        elif not np.isnan(x):
            prev = alpha * x + (1 - alpha) * prev
            out[i] = prev
    return pd.Series(out, index=a.index)


def _ema(a, n):
    return _ema_like(a, n, 2 / (n + 1))


def _wma(a, n):
    w = np.arange(1, n + 1)
    return a.rolling(n).apply(lambda x: (x * w).sum() / w.sum(), raw=True)


def _zs(a, n):
    return (a - a.rolling(n).mean()) / a.rolling(n).std(ddof=0)


def frame():
    spy = _bars("SPY")
    es = _bars("ES=F")
    df = spy[["c", "h", "l", "v"]].copy()
    df["es_c"] = es.c.reindex(df.index) if len(es) else np.nan
    df["es_v"] = es.v.reindex(df.index) if len(es) else np.nan
    df["br50"] = _asof(_ser("BR.SPX.50"), df.index)
    df["br200"] = _asof(_ser("BR.SPX.200"), df.index)
    c = df.c
    h = _wma(2 * _wma(c, 7) - _wma(c, 15), 3)  # HMA(15)
    s50 = c.rolling(50).mean()
    df["dsum"] = np.where(s50.diff() > 0, 1, -1) + np.where(h.diff() > 0, 1, -1) + np.where(h > s50, 1, -1) + np.where(c > h, 1, -1)
    tr = pd.concat([df.h - df.l, (df.h - c.shift()).abs(), (df.l - c.shift()).abs()], axis=1).max(axis=1)
    df["atrZ"] = _zs(_ema(tr, 20), 20)
    df["obvZ"] = _zs((np.sign(c.diff()).fillna(0) * df.v).cumsum(), 20)
    df["fiEq"] = _ema(c.diff() * df.v, 13) / 1e6
    es_fi = _ema(es.c.diff() * es.v, 13) / 1e6 if len(es) else pd.Series(dtype=float)
    df["fiEs"] = _asof(es_fi, df.index) if len(es) else np.nan
    df["ivts"] = _ivts(_ser("VIX"), _ser("VIX3M"), df.index)
    hi20 = c.rolling(20).max()
    df["brN"] = (df.br200 < 50).astype(int) + ((c >= hi20) & (df.br50 < df.br50.shift(20))).astype(int)
    df["w_trend"] = (df.dsum < 0).astype(int)
    df["w_atr"] = (df.atrZ >= 1).astype(int)
    df["w_obv"] = (df.obvZ < -1).astype(int)
    df["w_ivts"] = (df.ivts >= 0.9).astype(int)
    df["w_fi"] = ((df.fiEq <= -141) | (df.fiEs <= -15)).astype(int)
    df["w_br"] = (df.brN > 0).astype(int)
    df["total5"] = df[["w_trend", "w_atr", "w_obv", "w_ivts", "w_fi"]].sum(axis=1)
    df["total6"] = df.total5 + df.w_br
    # offense vs defense, 20-session returns (dividend-adjusted sector ETFs)
    r20 = {}
    for t in ("XLK", "XLY", "XLC", "XLP", "XLU", "XLV"):
        b = _bars(t, adj=True)
        r20[t] = (b.c / b.c.shift(20) - 1) * 100 if len(b) else pd.Series(dtype=float)
    off = pd.concat([r20["XLK"], r20["XLY"], r20["XLC"]], axis=1).mean(axis=1)
    dfn = pd.concat([r20["XLP"], r20["XLU"], r20["XLV"]], axis=1).mean(axis=1)
    df["offdef"] = (off - dfn).reindex(df.index)
    fut = c.shift(-21)
    df["f21"] = (fut / c - 1) * 100
    mins = pd.concat([c.shift(-k) for k in range(1, 22)], axis=1).min(axis=1)
    df["dd21"] = (mins / c - 1) * 100
    return df


def _st(df, m):
    x = df[m.fillna(False)].dropna(subset=["f21"])
    if len(x) < 10:
        return None
    return {"n": int(len(x)), "ret21": float(x.f21.mean()), "up21": float((x.f21 > 0).mean() * 100),
            "dd5": float((x.dd21 <= -5).mean() * 100), "since": x.index[0].date().isoformat()}


def stats(df):
    key = f"warnstats:{dt.date.today().isoformat()}"
    cached = db.get_meta(key)
    if cached:
        return json.loads(cached)
    era = pd.Series(df.index >= "2010-01-01", index=df.index)
    out = {"base": _st(df, era), "total": {}, "component": {}, "rotation": {}}
    for k in range(0, 6):
        out["total"][str(k)] = _st(df, era & (df.total5 == k))
    for col in ("w_trend", "w_atr", "w_obv", "w_ivts", "w_fi"):
        out["component"][col] = _st(df, era & (df[col] == 1))
    allr = pd.Series(df.offdef.notna(), index=df.index)
    out["rotation"]["defensive"] = _st(df, allr & (df.offdef <= -1))
    out["rotation"]["neutral"] = _st(df, allr & (df.offdef > -1) & (df.offdef < 1))
    out["rotation"]["offensive"] = _st(df, allr & (df.offdef >= 1))
    out["rotation"]["base"] = _st(df, allr)
    db.set_meta(key, json.dumps(out))
    return out


def now():
    df = frame()
    st = stats(df)
    L = df.iloc[-1]
    names = {"w_trend": "DSSTFS trend stack negative", "w_atr": "ATR z-score ≥ 1", "w_obv": "OBV z-score < −1",
             "w_ivts": "VIX/VIX3M ≥ 0.90", "w_fi": "Force Index (SPY or ES) washout", "w_br": "Breadth (S&P below 200d / divergence)"}
    comps = [{"id": k, "label": v, "on": bool(L[k]), "stats": st["component"].get(k)} for k, v in names.items()]
    t5, t6 = int(L.total5), int(L.total6)
    od = float(L.offdef) if pd.notna(L.offdef) else None
    rot = "defensive" if od is not None and od <= -1 else "offensive" if od is not None and od >= 1 else "neutral"
    return {"date": df.index[-1].date().isoformat(), "total5": t5, "total6": t6, "components": comps,
            "total_stats": st["total"].get(str(min(t5, 5))), "base": st["base"],
            "rotation": {"value": od, "state": rot, "stats": st["rotation"].get(rot), "base": st["rotation"]["base"]},
            "all_totals": st["total"]}
