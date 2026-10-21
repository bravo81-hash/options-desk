"""Term structure, calendar scanner, skew/IV trackers and the calendar-trade evidence study.

Vol values returned to the UI are in vol points (15.2 = 15.2%).
"""
import datetime as dt
import math

import numpy as np
import pandas as pd

from . import db
from .history import CBOE_TENORS, cboe_curve_frame, series
from .volmath import forward_vol, percentile, zscore

LOOKBACK = 252  # one year of sessions for z-scores


def _last(s):
    s = s.dropna()
    return (s.index[-1], float(s.iloc[-1])) if len(s) else (None, None)


def _hist(s, n):
    s = s.dropna()
    return [{"d": d, "v": round(float(v), 4)} for d, v in s.iloc[-n:].items()]


def _z(s, n=LOOKBACK):
    s = s.dropna()
    if len(s) < 30:
        return None, None
    window = s.iloc[-n - 1:-1]
    v = float(s.iloc[-1])
    return zscore(window.tolist(), v), percentile(s.iloc[-3 * n:].tolist(), v)


# ------------------------------------------------------------------ term structure
def term_structure():
    df = cboe_curve_frame()
    if df.empty:
        return {"error": "No CBOE history yet. Refresh history from the Recorder tab."}
    last = df.index[-1]
    rows = []
    for lag, label in ((0, "Today"), (5, "1 week ago"), (21, "1 month ago")):
        r = df.iloc[-1 - lag]
        rows.append({"label": label, "date": df.index[-1 - lag],
                     "points": [{"tenor": t, "name": n, "v": None if pd.isna(r.get(n)) else round(float(r[n]), 2)} for n, t in CBOE_TENORS]})
    spreads = {}
    for a, b, label in (("VIX9D", "VIX", "VIX − VIX9D (30d vs 9d)"), ("VIX", "VIX3M", "VIX3M − VIX (93d vs 30d)"), ("VIX3M", "VIX6M", "VIX6M − VIX3M")):
        s = (df[b] - df[a]).dropna()
        z, pct = _z(s)
        spreads[label] = {"now": round(float(s.iloc[-1]), 2), "z": z, "pct": pct, "hist": _hist(s, 504)}
    ratio = (df["VIX"] / df["VIX3M"]).dropna()
    rz, rp = _z(ratio)
    extra = {}
    for sym in ("VVIX", "SKEW", "RVX"):
        s = series(sym, "2015-01-01")
        if len(s):
            z, pct = _z(s)
            extra[sym] = {"now": round(float(s.iloc[-1]), 2), "z": z, "pct": pct, "date": s.index[-1]}
    return {"date": last, "curves": rows, "spreads": spreads,
            "ratio": {"now": round(float(ratio.iloc[-1]), 3), "z": rz, "pct": rp, "hist": _hist(ratio, 504)},
            "vix_hist": {n: _hist(df[n], 504) for n in ("VIX9D", "VIX", "VIX3M")}, "extra": extra}


_FRAME = {}


def _cboe_interp_frame():
    """Arrays for maturity-matched interpolation: rows with the full 9d..1y CBOE curve."""
    key = db.get_meta("cboe_refreshed")
    if _FRAME.get("key") != key:
        df = cboe_curve_frame().dropna()
        _FRAME.update(key=key, dates=df.index.tolist(),
                      tenors=np.array([t for _, t in CBOE_TENORS], dtype=float) / 365.0,
                      vals=df[[n for n, _ in CBOE_TENORS]].to_numpy(dtype=float) / 100.0)
    return _FRAME["dates"], _FRAME["tenors"], _FRAME["vals"]


def _interp_rows(tenors, vals, t):
    """Total-variance interpolation at maturity t (years), vectorised over every row."""
    if t <= tenors[0]:
        return vals[:, 0].copy()
    if t >= tenors[-1]:
        return vals[:, -1].copy()
    j = int(np.searchsorted(tenors, t))
    t1, t2 = tenors[j - 1], tenors[j]
    w1, w2 = vals[:, j - 1] ** 2 * t1, vals[:, j] ** 2 * t2
    w = w1 + (w2 - w1) * (t - t1) / (t2 - t1)
    return np.sqrt(np.maximum(w, 1e-12) / t)


_CACHE = {}


def cboe_pair_contango(front_dte, back_dte):
    """Maturity-matched SPX contango history (vol pts) for a front/back DTE pair from CBOE indices."""
    key = (int(front_dte), int(back_dte), db.get_meta("cboe_refreshed"))
    if key in _CACHE:
        return _CACHE[key]
    dates, tenors, vals = _cboe_interp_frame()
    f = _interp_rows(tenors, vals, max(front_dte, 1) / 365.0)
    b = _interp_rows(tenors, vals, back_dte / 365.0)
    s = pd.Series((b - f) * 100.0, index=dates).dropna()
    _CACHE[key] = s
    return s


def _recorded_pair_contango(symbol, front_dte, back_dte):
    rows = db.query("SELECT date, tenor, atm_iv FROM tenor_daily WHERE symbol=? AND atm_iv IS NOT NULL ORDER BY date", (symbol,))
    by = {}
    for r in rows:
        by.setdefault(r["date"], []).append((r["tenor"] / 365.0, r["atm_iv"]))
    from .volmath import interp_total_variance
    out = {}
    for d, pts in by.items():
        a = interp_total_variance(pts, front_dte / 365.0)
        b = interp_total_variance(pts, back_dte / 365.0)
        if a and b:
            out[d] = (b - a) * 100
    return pd.Series(out, dtype=float)


def latest_snapshot(symbol):
    s = db.query("SELECT * FROM snaps WHERE symbol=? ORDER BY date DESC, id DESC LIMIT 1", (symbol,))
    if not s:
        return None, []
    snap = s[0]
    es = db.query("SELECT * FROM expiry_summary WHERE snap_id=? AND atm_iv IS NOT NULL ORDER BY dte", (snap["id"],))
    return snap, es


def _put_calendar_debit(snap_id, e1, e2, fwd_hint):
    q = db.query("SELECT expiry, strike, mid FROM quotes WHERE snap_id=? AND right='P' AND mid IS NOT NULL AND expiry IN (?,?)",
                 (snap_id, e1, e2))
    a = {r["strike"]: r["mid"] for r in q if r["expiry"] == e1}
    b = {r["strike"]: r["mid"] for r in q if r["expiry"] == e2}
    common = [k for k in a if k in b]
    if not common:
        return None, None
    k = min(common, key=lambda x: abs(x - fwd_hint))
    return k, round(b[k] - a[k], 2)


def realized(symbol, n=20):
    s = series(symbol)
    if len(s) < n + 2:
        return None
    lr = np.log(s / s.shift(1)).dropna()
    return float(lr.iloc[-n:].std() * math.sqrt(252) * 100)


def calendar_scan(symbol="SPX", front_min=3, front_max=45, gap_min=5, gap_max=60):
    snap, es = latest_snapshot(symbol)
    if not snap:
        return {"error": f"No {symbol} snapshot recorded yet. Press 'Record now' on the Recorder tab while TWS is running."}
    rv20 = realized(symbol, 20)
    rec_days = db.query("SELECT COUNT(DISTINCT date) n FROM tenor_daily WHERE symbol=?", (symbol,))[0]["n"]
    pairs = []
    for i, f in enumerate(es):
        if not (front_min <= f["dte"] <= front_max):
            continue
        for b in es[i + 1:]:
            gap = b["dte"] - f["dte"]
            if gap < gap_min or gap > gap_max:
                continue
            fv, bv = f["atm_iv"], b["atm_iv"]
            fwd = forward_vol(fv, f["t"], bv, b["t"])
            cont = (bv - fv) * 100
            z = zsrc = None
            if symbol == "SPX":
                hist = cboe_pair_contango(f["dte"], b["dte"])
                if len(hist) > 60:
                    z = zscore(hist.iloc[-LOOKBACK - 1:-1].tolist(), float(hist.iloc[-1]))
                    zsrc = "CBOE matched"
            if rec_days >= 20:
                rh = _recorded_pair_contango(symbol, f["dte"], b["dte"])
                if len(rh) >= 20:
                    z = zscore(rh.iloc[:-1].tolist(), float(rh.iloc[-1]))
                    zsrc = "recorded"
            k, debit = _put_calendar_debit(snap["id"], f["expiry"], b["expiry"], snap["spot"])
            pairs.append({"front": f["expiry"], "back": b["expiry"], "fdte": int(f["dte"]), "bdte": int(b["dte"]),
                          "front_iv": round(fv * 100, 2), "back_iv": round(bv * 100, 2), "contango": round(cont, 2),
                          "z": None if z is None else round(z, 2), "zsrc": zsrc,
                          "fwd_vol": None if fwd is None else round(fwd * 100, 2),
                          "fwd_premium": None if fwd is None else round(fwd * 100 - fv * 100, 2),
                          "fwd_vs_rv": None if fwd is None or not rv20 else round(fwd * 100 - rv20, 2),
                          "strike": k, "debit": debit})
    return {"symbol": symbol, "date": snap["date"], "ts": snap["ts"], "spot": snap["spot"], "rv20": rv20,
            "recorded_days": rec_days, "pairs": pairs, "gates": strategy_gates(symbol, es, pairs)}


def _nearest_pair(pairs, fd, bd):
    if not pairs:
        return None
    return min(pairs, key=lambda p: abs(p["fdte"] - fd) * 2 + abs(p["bdte"] - bd))


def strategy_gates(symbol, es, pairs):
    """Rule checks folded in from Calendar-Scanner's STRATEGIES.md. Informational only."""
    df = cboe_curve_frame()
    vix, vix3m = (float(df["VIX"].iloc[-1]), float(df["VIX3M"].iloc[-1])) if len(df) else (None, None)
    backwardation = vix is not None and vix > vix3m
    gates = []
    if symbol == "SPX":
        p = _nearest_pair(pairs, 15, 22)
        if p:
            checks = [("Back IV − front IV ≤ 1.0 pt", p["contango"] <= 1.0, f"{p['contango']:+.2f} pts"),
                      ("VIX below VIX3M (no backwardation)", not backwardation, f"VIX {vix:.2f} / VIX3M {vix3m:.2f}")]
            gates.append({"name": "TimeEdge", "pair": p, "rule": "ATM put calendar, ~15 / 22 DTE, entry Thursday ~3:30 pm ET",
                          "checks": checks, "pass": all(c[1] for c in checks)})
        p = _nearest_pair(pairs, 21, 28)
        if p:
            checks = [("VIX below VIX3M (no backwardation)", not backwardation, f"VIX {vix:.2f} / VIX3M {vix3m:.2f}")]
            gates.append({"name": "Triple Calendar", "pair": p, "rule": "3 put calendars ATM and ±expected move, 21 / 28 DTE",
                          "checks": checks, "pass": all(c[1] for c in checks)})
    if symbol == "RUT":
        p = _nearest_pair(pairs, 15, 43)
        if p:
            checks = [("VIX below VIX3M (no backwardation)", not backwardation, f"VIX {vix:.2f} / VIX3M {vix3m:.2f}"),
                      ("Front not above back (calendar in contango)", p["contango"] >= 0, f"{p['contango']:+.2f} pts")]
            gates.append({"name": "TimeZone", "pair": p, "rule": "RUT 14Δ 20-wide PCS + 40Δ put calendar, ~15 / 43 DTE",
                          "checks": checks, "pass": all(c[1] for c in checks)})
    return gates


def pair_detail(symbol, front, back):
    snap, es = latest_snapshot(symbol)
    f = next((e for e in es if e["expiry"] == front), None)
    b = next((e for e in es if e["expiry"] == back), None)
    if not f or not b:
        return {"error": "That expiry pair is not in the latest snapshot."}
    out = {"symbol": symbol, "front": front, "back": back, "fdte": int(f["dte"]), "bdte": int(b["dte"])}
    if symbol == "SPX":
        h = cboe_pair_contango(f["dte"], b["dte"])
        out["matched"] = _hist(h, 504)
        out["matched_src"] = "CBOE VIX9D/VIX/VIX3M/VIX6M/VIX1Y, interpolated to these maturities"
    rh = _recorded_pair_contango(symbol, f["dte"], b["dte"])
    out["matched_recorded"] = _hist(rh, 504)
    # actual-expiration history: this exact pair on every recorded day both expiries were present
    rows = db.query("""SELECT a.date, a.atm_iv fa, b.atm_iv ba FROM expiry_summary a JOIN expiry_summary b
                       ON a.snap_id=b.snap_id AND b.expiry=? WHERE a.symbol=? AND a.expiry=? ORDER BY a.date""", (back, symbol, front))
    out["actual"] = [{"d": r["date"], "v": round((r["ba"] - r["fa"]) * 100, 3)} for r in rows if r["fa"] and r["ba"]]
    return out


# ------------------------------------------------------------------ skew / IV
def skew_iv(symbol="SPX", tenor=30):
    rows = db.query("SELECT * FROM tenor_daily WHERE symbol=? AND tenor=? ORDER BY date", (symbol, tenor))
    rec = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()
    cur = {}
    hist = {}
    if len(rec):
        metrics = {
            "ATM IV": rec["atm_iv"] * 100,
            "Vertical skew (25Δ put − ATM)": (rec["p25_iv"] - rec["atm_iv"]) * 100,
            "Skew slope (10Δ put − 25Δ put)": (rec["p10_iv"] - rec["p25_iv"]) * 100,
            "Risk reversal (25Δ put − 25Δ call)": (rec["p25_iv"] - rec["c25_iv"]) * 100,
        }
        for k, s in metrics.items():
            s = s.dropna()
            if not len(s):
                continue
            z = zscore(s.iloc[:-1].tolist(), float(s.iloc[-1])) if len(s) >= 21 else None
            cur[k] = {"now": round(float(s.iloc[-1]), 2), "z": z, "n": len(s), "src": "recorded"}
            hist[k] = _hist(s, 504)
    proxies = {}
    iv30 = series(f"{symbol}.IV30") * 100
    if len(iv30):
        z, pct = _z(iv30)
        proxies["IV30 (IBKR, 30-day ATM)"] = {"now": round(float(iv30.iloc[-1]), 2), "z": z, "pct": pct, "hist": _hist(iv30, 504)}
    rv = realized(symbol, 20)
    if rv:
        proxies["Realized vol 20d"] = {"now": round(rv, 2)}
    if symbol == "SPX":
        sk = series("SKEW")
        if len(sk):
            z, pct = _z(sk)
            proxies["CBOE SKEW index (tail skew)"] = {"now": round(float(sk.iloc[-1]), 2), "z": z, "pct": pct, "hist": _hist(sk, 504)}
    if symbol == "RUT":
        rvx = series("RVX")
        if len(rvx):
            z, pct = _z(rvx)
            proxies["CBOE RVX (RUT 30-day vol)"] = {"now": round(float(rvx.iloc[-1]), 2), "z": z, "pct": pct, "hist": _hist(rvx, 504)}
    snap, es = latest_snapshot(symbol)
    smile = []
    if snap:
        smile = [{"dte": int(e["dte"]), "expiry": e["expiry"], "atm": _r(e["atm_iv"]), "p25": _r(e["p25_iv"]),
                  "p10": _r(e["p10_iv"]), "c25": _r(e["c25_iv"])} for e in es]
    return {"symbol": symbol, "tenor": tenor, "current": cur, "history": hist, "proxies": proxies,
            "term": smile, "date": snap["date"] if snap else None, "recorded_days": len(rec)}


def _r(v):
    return None if v is None else round(v * 100, 2)


# ------------------------------------------------------------------ evidence
FEATURES = [
    ("vix_vix3m", "VIX / VIX3M", "higher = flatter / backwardated term structure"),
    ("vix9d_vix", "VIX9D / VIX", "higher = near-term fear above 30-day"),
    ("cont_z", "Contango z (VIX − VIX9D)", "low = front vol unusually high vs 30d"),
    ("vix", "VIX", ""),
    ("vix_chg5", "VIX 5-day change", "rising vol into entry"),
    ("vvix", "VVIX", "vol of vol"),
    ("spx_ret5", "SPX 5-day return %", ""),
    ("vrp", "VIX − realized 10d", "low = options cheap vs realized moves"),
    ("slope_15_22", "Term slope 15→22 DTE (pts)", "TimeEdge abort rule skips entries above 1.0"),
]


def evidence():
    from .trades import CALENDAR_FAMILY, journal
    trades, files = journal()
    df = cboe_curve_frame("2024-01-01")
    vvix = series("VVIX", "2024-01-01")
    spx = series("SPX", "2024-01-01")
    if df.empty:
        return {"error": "Refresh CBOE history first."}
    rv10 = None
    if len(spx) > 15:
        rv10 = (np.log(spx / spx.shift(1)).rolling(10).std() * math.sqrt(252) * 100)
    cz = (df["VIX"] - df["VIX9D"])
    czz = (cz - cz.rolling(LOOKBACK).mean().shift(1)) / cz.rolling(LOOKBACK).std().shift(1)
    dates = df.index.tolist()
    sd, st, sv = _cboe_interp_frame()
    slope = pd.Series((_interp_rows(st, sv, 22 / 365) - _interp_rows(st, sv, 15 / 365)) * 100, index=sd)

    def asof(s, d):
        if s is None or not len(s):
            return None
        s2 = s.loc[:d].dropna()
        return float(s2.iloc[-1]) if len(s2) else None

    rows = []
    for t in trades:
        if t["strategy"] not in CALENDAR_FAMILY or t["status"] != "Closed" or t["pnl"] is None or not t["opened"]:
            continue
        d = t["opened"].isoformat()
        idx = [x for x in dates if x <= d]
        if len(idx) < 6:
            continue
        r0 = df.loc[idx[-1]]
        r5 = df.loc[idx[-6]]
        feat = {
            "vix_vix3m": r0["VIX"] / r0["VIX3M"], "vix9d_vix": r0["VIX9D"] / r0["VIX"],
            "cont_z": asof(czz, d), "vix": r0["VIX"], "vix_chg5": r0["VIX"] - r5["VIX"],
            "vvix": asof(vvix, d), "spx_ret5": None, "vrp": None, "slope_15_22": asof(slope, d),
        }
        s_now, s_5 = asof(spx, d), asof(spx, idx[-6])
        if s_now and s_5:
            feat["spx_ret5"] = (s_now / s_5 - 1) * 100
        rv = asof(rv10, d)
        if rv:
            feat["vrp"] = r0["VIX"] - rv
        rows.append({**{k: (round(v, 4) if isinstance(v, float) else v) for k, v in feat.items()},
                     "date": d, "closed": t["closed"].isoformat() if t["closed"] else None, "strategy": t["strategy"],
                     "name": t["name"], "pnl": t["pnl"], "ret_pct": t["ret_pct"], "source": t["source"], "win": t["pnl"] > 0})
    if not rows:
        return {"error": "No closed calendar-family trades found in the journal files.", "files": files}
    ev = pd.DataFrame(rows)
    feats = []
    for key, label, hint in FEATURES:
        x = ev.dropna(subset=[key])
        if len(x) < 8:
            continue
        w, l = x[x.win], x[~x.win]
        best = None
        for side in ("above", "below"):
            for q in np.linspace(0.1, 0.9, 17):
                thr = float(x[key].quantile(q))
                skip = x[key] > thr if side == "above" else x[key] < thr
                kept, skipped = x[~skip], x[skip]
                if len(skipped) < 3 or len(kept) < 5:
                    continue
                gain = -skipped.pnl.sum()  # P&L improvement from skipping those trades
                cand = {"side": side, "threshold": round(thr, 3), "skipped": int(len(skipped)),
                        "skipped_losers": int((~skipped.win).sum()), "skipped_winners": int(skipped.win.sum()),
                        "pnl_skipped": round(float(skipped.pnl.sum()), 0), "pnl_kept": round(float(kept.pnl.sum()), 0)}
                if best is None or gain > -best["pnl_skipped"]:
                    best = cand
        feats.append({"key": key, "label": label, "hint": hint, "n": int(len(x)),
                      "win_median": None if not len(w) else round(float(w[key].median()), 3),
                      "loss_median": None if not len(l) else round(float(l[key].median()), 3),
                      "best_rule": best})
    by = ev.groupby("strategy").agg(n=("pnl", "size"), wins=("win", "sum"), pnl=("pnl", "sum")).reset_index()
    return {"files": files, "n": len(ev), "trades": ev.sort_values("date").to_dict("records"),
            "features": feats, "by_strategy": by.to_dict("records"),
            "note": "Entry-day values use the close of the session the trade was opened in (entries are within the last hour). "
                    "Small sample: treat any rule as a hypothesis to watch, not a proven filter."}


def inventory():
    rows = db.query("SELECT symbol, COUNT(*) n, MIN(date) a, MAX(date) b FROM index_daily GROUP BY symbol ORDER BY symbol")
    snaps = db.query("SELECT symbol, COUNT(*) n, MIN(date) a, MAX(date) b, MAX(ts) last FROM snaps GROUP BY symbol")
    return {"history": rows, "snapshots": snaps}
