"""A14 scanner: put broken-wing butterflies on SPX and RUT, the way you trade them.

Structure (1 lot): +1 upper put (U above the short), -2 short puts, +1 lower put (L below the short), L >= U.
Your A14 entries in ONE (June-Oct 2026): upper long -1%..+1% from spot, short 0.5-3.5% OTM, SPX widths
50-100 up / 60-150 down, RUT 40-75 up / 50-125 down, entered near zero cost, 13-86 DTE.

Pricing: a focused live chain from TWS (puts on a 25-point SPX / 10-point RUT grid plus near-the-money calls),
own IV from mids off the put-call-parity forward, a per-expiry smile (OTM puts below the forward, OTM calls
above), and every leg priced from that smile so the ranking is not driven by one stale quote.
Scenario at the planned exit (T+H days): sticky-strike Black-76 on the smile; odds from a lognormal with
the chosen volatility (20-day realised by default: the market usually prices more than it realises).
"""
import csv
import datetime as dt
import json
import math
import re
import threading

import numpy as np

from . import db, load_config
from .chain import LOCK, connect, dte, option_params, snapshot, underlying
from .history import series
from .recorder import ET, fit_rows

GRID = {"SPX": {"step": 25, "lo": 0.92, "hi": 1.02, "up": [50, 75, 100, 125], "extra": [25, 50, 75]},
        "RUT": {"step": 10, "lo": 0.89, "hi": 1.02, "up": [30, 40, 50, 60, 75], "extra": [10, 20, 30, 50]}}
status = {"running": False, "log": [], "last": None}


def _log(m):
    status["log"] = (status["log"] + [f"{dt.datetime.now():%H:%M:%S}  {m}"])[-30:]


# ------------------------------------------------------------------ normal cdf / Black-76 (numpy, no scipy)
def _ncdf(x):
    x = np.asarray(x, dtype=float)
    t = 1.0 / (1.0 + 0.2316419 * np.abs(x))
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    p = 1.0 - np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi) * poly
    return np.where(x >= 0, p, 1.0 - p)


def put_price(F, K, T, sig):
    F, K, T, sig = np.broadcast_arrays(*(np.asarray(a, dtype=float) for a in (F, K, T, sig)))
    out = np.maximum(K - F, 0.0)
    live = (T > 1e-6) & (sig > 1e-6)
    sT = np.where(live, sig * np.sqrt(np.where(live, T, 1.0)), 1.0)
    d1 = (np.log(F / K) + 0.5 * sT * sT) / sT
    d2 = d1 - sT
    val = K * _ncdf(-d2) - F * _ncdf(-d1)
    return np.where(live, val, out)


# ------------------------------------------------------------------ chain
def _expiries(params, lo, hi):
    """Fridays and month-end expiries in the DTE window."""
    out = []
    for e in sorted(params):
        d = dt.datetime.strptime(e, "%Y%m%d").date()
        n = dte(e)
        if not (lo <= n <= hi):
            continue
        nxt = d + dt.timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += dt.timedelta(days=1)
        eom = nxt.month != d.month
        if d.weekday() == 4 or eom:  # (AM monthlies are already keyed by their Friday)
            out.append(e)
    return out


def fetch_chain(symbols=("SPX", "RUT"), dte_min=7, dte_max=110):
    from ib_async import Option
    if not LOCK.acquire(blocking=False):
        return {"error": "Another chain fetch is running."}
    status["running"] = True
    ib = None
    try:
        ib = connect()
        out = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "symbols": {}}
        for sym in symbols:
            g = GRID[sym]
            und, spot = underlying(ib, sym)
            if not spot:
                _log(f"{sym}: no price")
                continue
            params = option_params(ib, und)
            exps = _expiries(params, dte_min, dte_max)
            cons = []
            back = {}
            for e in exps:
                cls, strikes, ib_e = params[e]
                back[ib_e] = e
                put_k = [k for k in strikes if k % g["step"] == 0 and g["lo"] * spot <= k <= g["hi"] * spot]
                call_k = [k for k in strikes if k % g["step"] == 0 and 0.995 * spot <= k <= g["hi"] * spot]
                cons += [Option(sym, ib_e, k, "P", "SMART", tradingClass=cls) for k in put_k]
                cons += [Option(sym, ib_e, k, "C", "SMART", tradingClass=cls) for k in call_k]
            _log(f"{sym}: spot {spot:.2f}, {len(exps)} expiries, {len(cons)} contracts")
            rows = snapshot(ib, cons)
            for r in rows:
                r["expiry"] = back.get(r["expiry"], r["expiry"])
                r["dte"] = max(dte(r["expiry"]), 0)
            fit_rows(rows, spot)
            out["symbols"][sym] = {"spot": spot, "rows": [{k: r.get(k) for k in ("expiry", "dte", "strike", "right", "trading_class",
                                                                                 "bid", "ask", "mid", "iv", "ib_iv", "fwd")} for r in rows]}
            _log(f"{sym}: {sum(1 for r in rows if r.get('iv'))} quotes with an IV")
        db.set_meta("a14_chain", json.dumps(out))
        status["last"] = out["ts"]
        return {"ok": True, "ts": out["ts"]}
    except Exception as e:
        _log(f"chain fetch failed: {e}")
        return {"error": f"Could not fetch the chain from TWS: {e}"}
    finally:
        if ib is not None:
            ib.disconnect()
        status["running"] = False
        LOCK.release()


def refresh_async(**kw):
    if status["running"]:
        return False
    threading.Thread(target=fetch_chain, kwargs=kw, daemon=True).start()
    return True


# ------------------------------------------------------------------ smile per expiry
def _smiles(sym_blob):
    """{expiry: dict(F, T, dte, ks, ivs)} from OTM quotes (puts below the forward, calls above)."""
    by = {}
    for r in sym_blob["rows"]:
        by.setdefault(r["expiry"], []).append(r)
    out = {}
    for e, rows in by.items():
        F = next((r["fwd"] for r in rows if r.get("fwd")), sym_blob["spot"])
        pts = {}
        for r in rows:
            iv = r.get("iv")
            if not iv:
                continue
            if (r["right"] == "P" and r["strike"] <= F * 1.004) or (r["right"] == "C" and r["strike"] >= F * 0.996):
                pts.setdefault(r["strike"], []).append(iv)
        if len(pts) < 4:
            continue
        ks = np.array(sorted(pts))
        ivs = np.array([float(np.mean(pts[k])) for k in ks])
        d = rows[0]["dte"]
        out[e] = {"F": F, "dte": d, "T": max(d, 0.5) / 365.0, "ks": ks, "ivs": ivs, "cls": rows[0].get("trading_class"),
                  "strikes": sorted({r["strike"] for r in rows if r["right"] == "P"})}
    return out


def _iv_at(sm, k):
    return np.interp(k, sm["ks"], sm["ivs"])  # flat beyond the quoted wings


def realised_vol(sym, n=20):
    s = series(sym).dropna()
    if len(s) < n + 1:
        return None
    lr = np.diff(np.log(s.values[-(n + 1):]))
    return float(np.std(lr, ddof=1) * math.sqrt(252))


STRESS_MOVE, STRESS_VOL = -0.05, 0.05  # stress at the exit date: index -5%, every strike's IV +5 vol points
_HOLD = {"t": None, "v": {}}


def typical_hold():
    """Average days held of your closed A14s per entry-DTE bucket (Journal / ONE), cached 10 minutes."""
    now = dt.datetime.now()
    if _HOLD["t"] is None or (now - _HOLD["t"]).total_seconds() > 600:
        try:
            _HOLD["v"] = {b: v["dit"] for b, v in stats()["by_dte"].items() if v["n"] >= 2}
        except Exception:
            _HOLD["v"] = {}
        _HOLD["t"] = now
    return _HOLD["v"]


def hold_days(d, exit_days=None):
    """Days to the modelled exit: a fixed number, or (None / 'auto') your typical hold for this entry DTE."""
    if exit_days in (None, "auto"):
        exit_days = round(typical_hold().get(bucket(d)) or 14)
    return int(min(exit_days, max(d - 1, 1)))


# ------------------------------------------------------------------ scan
def scan(symbols=("SPX", "RUT"), dte_min=14, dte_max=45, exit_days=None, vol_basis="rv20", vol_custom=None,
         min_credit=-1.0, up_lo=-1.5, up_hi=1.0, top=40):
    raw = db.get_meta("a14_chain")
    if not raw:
        return {"error": "No chain yet: press Fetch chain from TWS (TWS must be running)."}
    blob = json.loads(raw)
    cands, heat = [], {}
    meta = {"ts": blob["ts"], "symbols": {}}
    for sym in symbols:
        sb = blob["symbols"].get(sym)
        if not sb:
            continue
        g, S0 = GRID[sym], sb["spot"]
        sms = _smiles(sb)
        rv = realised_vol(sym)
        meta["symbols"][sym] = {"spot": S0, "rv20": rv, "expiries": len(sms)}
        for e, sm in sorted(sms.items()):
            if not (dte_min <= sm["dte"] <= dte_max):
                continue
            ks = np.array(sm["strikes"])
            kset = set(ks.tolist())
            ups = ks[(ks >= S0 * (1 + up_lo / 100)) & (ks <= S0 * (1 + up_hi / 100))]
            combos = [(u, u - U, u - U - (U + x)) for u in ups for U in g["up"] for x in g["extra"]
                      if (u - U) in kset and (u - U - (U + x)) in kset]
            if not combos:
                continue
            C = np.array(combos)  # columns: upper, short, lower
            T, F0 = sm["T"], sm["F"]
            ivs = _iv_at(sm, C)
            px = put_price(F0, C, T, ivs)
            credit = 2 * px[:, 1] - px[:, 0] - px[:, 2]
            U = C[:, 0] - C[:, 1]
            L = C[:, 1] - C[:, 2]
            max_profit = U + credit
            risk = np.maximum(np.maximum(L - U - credit, -credit), 0.05)
            # greeks at T+0 by bumping (per lot, $)
            def val(F, t, bump=0.0):
                return (put_price(F, C, t, ivs + bump) * np.array([1, -2, 1])).sum(axis=1)
            v0 = val(F0, T)
            dF = F0 * 0.001
            delta = (val(F0 + dF, T) - val(F0 - dF, T)) / (2 * dF) * 100
            gamma = (val(F0 + dF, T) - 2 * v0 + val(F0 - dF, T)) / dF ** 2 * 100
            theta = (val(F0, max(T - 1 / 365, 1e-6)) - v0) * 100
            vega = (val(F0, T, 0.01) - v0) * 100
            # scenario at the exit: spot grid in implied-sigma units, sticky strike
            h = hold_days(sm["dte"], exit_days)
            Th = max(T - h / 365, 1e-6)
            stress = ((put_price(F0 * (1 + STRESS_MOVE), C, Th, ivs + STRESS_VOL) * np.array([1, -2, 1])).sum(axis=1) - v0) * 100
            atm = float(_iv_at(sm, F0))
            sd_h = atm * math.sqrt(h / 365)
            x = np.linspace(-4 * sd_h, 3 * sd_h, 71)
            Fh = F0 * np.exp(x)
            vh = (put_price(Fh[None, :, None], C[:, None, :], Th, ivs[:, None, :]) * np.array([1, -2, 1])).sum(axis=2)
            pnl_h = (vh - v0[:, None]) * 100  # $ per lot
            sig = {"rv20": rv or atm * 0.8, "iv": atm}.get(vol_basis, (vol_custom or 15) / 100)
            sig_h = sig * math.sqrt(h / 365)
            w = np.exp(-0.5 * ((x + 0.5 * sig_h ** 2) / sig_h) ** 2)
            w /= w.sum()
            exp_pnl = pnl_h @ w
            pop = (pnl_h > 0) @ w
            pos = pnl_h >= 0
            tent_lo = np.where(pos.any(axis=1), x[np.argmax(pos, axis=1)], np.nan)
            tent_hi = np.where(pos.any(axis=1) & ~pos[:, -1], x[len(x) - 1 - np.argmax(pos[:, ::-1], axis=1)], np.nan)  # NaN: no upside loss
            i1 = int(np.argmin(np.abs(x + sd_h)))
            for j in range(len(C)):
                if min_credit is not None and credit[j] < min_credit:
                    continue
                short_pct = 100 * (C[j, 1] / S0 - 1)
                c = {"sym": sym, "expiry": e, "cls": sm["cls"], "dte": sm["dte"], "upper": C[j, 0], "short": C[j, 1], "lower": C[j, 2],
                     "U": float(U[j]), "L": float(L[j]), "credit": round(float(credit[j]), 2),
                     "max_profit": round(float(max_profit[j]) * 100), "risk": round(float(risk[j]) * 100),
                     "ror": float(max_profit[j] / risk[j]), "delta": round(float(delta[j]), 2), "gamma": float(gamma[j]),
                     "theta": round(float(theta[j]), 2), "vega": round(float(vega[j]), 2),
                     "theta_risk": float(100 * theta[j] / (risk[j] * 100)), "exp_h": round(float(exp_pnl[j])),
                     "exp_risk": float(100 * exp_pnl[j] / (risk[j] * 100)), "pop_h": float(pop[j]),
                     "tent_lo": None if np.isnan(tent_lo[j]) else float(100 * (math.exp(tent_lo[j]) * F0 / S0 - 1)),
                     "tent_hi": None if np.isnan(tent_hi[j]) else float(100 * (math.exp(tent_hi[j]) * F0 / S0 - 1)),
                     "down1sd_h": round(float(pnl_h[j, i1])), "h": h,
                     "stress_h": round(float(stress[j])), "stress_risk": float(100 * stress[j] / (risk[j] * 100)),
                     "exp_day": float(100 * exp_pnl[j] / (risk[j] * 100)) / h,
                     "upper_pct": 100 * (C[j, 0] / S0 - 1), "short_pct": short_pct, "atm_iv": atm,
                     "short_sd": (C[j, 1] / F0 - 1) / (atm * math.sqrt(T)),
                     "usual": bool(C[j, 0] >= S0 * 0.99 and C[j, 0] <= S0 * 1.01 and -3.5 <= short_pct <= -0.5)}
                cands.append(c)
                hk = (sym, e)
                bucket = round(short_pct * 2) / 2
                cur = heat.setdefault(hk, {}).get(bucket)
                if cur is None or c["exp_risk"] > cur["exp_risk"]:
                    heat[hk][bucket] = {"exp_risk": c["exp_risk"], "label": f"{int(c['upper'])}/{int(c['short'])}/{int(c['lower'])}"}
    if not cands:
        return {"error": "No candidates in that window (is the chain empty for those expiries?).", **meta}
    meta["count"] = len(cands)
    meta["hist"] = _hist_scores(cands)
    heat_out = [{"sym": k[0], "expiry": k[1], "cells": {str(b): v for b, v in sorted(cells.items())}} for k, cells in sorted(heat.items())]
    return {**meta, "candidates": cands, "heat": heat_out, "params": {"exit_days": exit_days or "auto", "vol_basis": vol_basis, "hold": typical_hold(),
                                                                 "stress": {"move": STRESS_MOVE, "vol": STRESS_VOL}}}


HIST_MIN_N = 80  # use today's VIX/VIX3M band when it has at least this many past entries, else all entries


def _hist_scores(cands):
    """Each candidate replayed since 2009 (desk/backtest.shape_score): its strikes in today's model-sd units,
    rebuilt on every past Friday at the same DTE, managed with your trade-plan exits. Adds hist_* fields;
    ranking defaults to hist_day = average return per day held, in today's term-structure band."""
    from . import backtest
    from .readiness import ivts_band
    try:
        D = backtest.data()
        band = ivts_band(float(D["vix"][-1] / D["vix3m"][-1]))
        sds = {}
        for c in cands:
            k = (c["sym"], int(c["dte"]))
            if k not in sds:
                sds[k] = backtest.sd_now(D, *k)
            sd = sds[k]
            S0 = c["upper"] / (1 + c["upper_pct"] / 100)
            x = [round(math.log(K / S0) / sd, 2) for K in (c["upper"], c["short"], c["lower"])]
            sc = backtest.shape_score(D, c["sym"], int(c["dte"]), x)
            b = sc.get(band["band"])
            use = b if b and b["n"] >= HIST_MIN_N else sc["all"]
            c["hist_all"], c["hist_band"] = sc["all"], b
            c["hist_basis"] = "band" if use is b else "all"
            if use:
                c.update(hist_day=use["per_day"], hist_avg=use["avg"], hist_win=use["win"], hist_ptgt=use["p_target"],
                         hist_pstop=use["p_stop"], hist_days=use["days"], hist_p5=use["p5"], hist_big=use["big_loss"])
        return {"band": band["band"], "label": band["label"], "min_n": HIST_MIN_N, "rule": "target +5% (21 DTE or less) or +7%, stop −20%, out at 2 DTE, slow trades closed at the next green close"}
    except Exception as e:
        _log(f"history scores unavailable: {e}")
        return {"error": str(e)}


def curve(sym, expiry, upper, short, lower, exit_days=None):
    """Risk-graph curves for one candidate: today, at the exit, at expiry ($ per lot vs spot)."""
    blob = json.loads(db.get_meta("a14_chain") or "{}")
    sb = blob.get("symbols", {}).get(sym)
    sm = _smiles(sb).get(expiry) if sb else None
    if not sm:
        return {"error": "Expiry not in the fetched chain."}
    S0, F0, T = sb["spot"], sm["F"], sm["T"]
    C = np.array([upper, short, lower], dtype=float)
    ivs = _iv_at(sm, C)
    wts = np.array([1, -2, 1])
    v0 = float((put_price(F0, C, T, ivs) * wts).sum())
    atm = float(_iv_at(sm, F0))
    span = max(4 * atm * math.sqrt(T), 0.06)
    S = np.linspace(S0 * (1 - span), S0 * (1 + span * 0.6), 161)
    fwd_ratio = F0 / S0
    h = hold_days(sm["dte"], exit_days)

    def at(t_left, bump=0.0):
        F = S * fwd_ratio ** (t_left / T if T else 0)
        return ((put_price(F[:, None], C[None, :], max(t_left, 1e-6), ivs[None, :] + bump) * wts).sum(axis=1) - v0) * 100

    em = S0 * atm * math.sqrt(T)
    return {"spot": S0, "S": S.round(2).tolist(), "now": at(T).round(1).tolist(), "exit": at(T - h / 365).round(1).tolist(),
            "stress": at(T - h / 365, STRESS_VOL).round(1).tolist(), "stress_vol": STRESS_VOL, "stress_move": STRESS_MOVE,
            "expiry": at(1e-6).round(1).tolist(), "h": h, "em": em, "em_h": S0 * atm * math.sqrt(h / 365), "atm_iv": atm,
            "strikes": [upper, short, lower]}


# ------------------------------------------------------------------ your A14 history (ONE)
def history():
    """Entry structure and outcome of every A14 trade in the latest ONE Summary Report."""
    from .trades import _newest
    path = _newest(load_config()["trade_files"]["one_glob"])
    if not path:
        return {"trades": []}

    def pdt(s):
        for f in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p"):
            try:
                return dt.datetime.strptime(s, f)
            except ValueError:
                pass
        return None

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    trades, cur = [], None
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.reader(fh):
            if len(r) > 15 and r[0] == "" and r[2] in ("Open", "Closed", "Expired") and r[1]:
                cur = {"group": r[1], "status": r[2], "und": r[3], "name": r[7], "dte": num(r[10]), "dit": num(r[11]),
                       "margin": num(r[12]), "pnl": num(r[14]), "ret": num(r[15]), "legs": []}
                trades.append(cur)
            elif len(r) > 17 and r[0] == "" and r[1] == "" and cur is not None and r[5] in ("Buy", "Sell"):
                t = pdt(r[4])
                if t and re.search(r"\d{8}$", r[7]):
                    cur["legs"].append({"t": t, "side": r[5], "qty": num(r[6]) or 0, "k": float(r[7][-8:]) / 1000,
                                        "right": r[7][-9], "px": num(r[12]) or 0})
    out = []
    for t in trades:
        if not re.search(r"\bA14\b", t["name"]) or not t["legs"]:
            continue
        t0 = min(l["t"] for l in t["legs"])
        ent = [l for l in t["legs"] if (l["t"] - t0).total_seconds() < 600]
        us = (t0 - dt.timedelta(hours=14)).date().isoformat()  # ONE times are Sydney local
        s = series(t["und"], (dt.date.fromisoformat(us) - dt.timedelta(days=7)).isoformat())
        s = s[s.index <= us]
        spot = float(s.iloc[-1]) if len(s) else None
        longs = sorted({l["k"] for l in ent if l["side"] == "Buy"})
        shorts = sorted({l["k"] for l in ent if l["side"] == "Sell"})
        row = {"und": t["und"], "status": t["status"], "name": t["name"], "entry": us, "dte": t["dte"], "dit": t["dit"],
               "pnl": t["pnl"], "ret": t["ret"], "margin": t["margin"], "adjustments": len(t["legs"]) - len(ent), "account": t["group"]}
        if len(longs) == 2 and len(shorts) == 1:
            row.update({"upper": longs[1], "short": shorts[0], "lower": longs[0], "U": longs[1] - shorts[0], "L": shorts[0] - longs[0]})
            if spot:
                row.update({"short_pct": 100 * (shorts[0] / spot - 1), "upper_pct": 100 * (longs[1] / spot - 1)})
        out.append(row)
    return {"trades": out, "file": path}


# ------------------------------------------------------------------ trend and capital-use benchmarks
DTE_BUCKETS = [(0, 21, "≤21"), (22, 45, "22–45"), (46, 70, "46–70"), (71, 999, "71+")]


def bucket(d):
    return next((lab for lo, hi, lab in DTE_BUCKETS if d is not None and lo <= d <= hi), None)


def trend(sym, on=None):
    """Underlying vs its 20-session average and its 5-session change, as of `on` (ISO date) or the latest bar."""
    s = series(sym).dropna()
    if on:
        s = s[s.index <= on]
    if len(s) < 21:
        return None
    last = float(s.iloc[-1])
    return {"date": s.index[-1], "close": last, "vs_sma20": 100 * (last / float(s.iloc[-20:].mean()) - 1),
            "ret5": 100 * (last / float(s.iloc[-6]) - 1)}


def stats():
    """Closed A14 trades in ONE: return per day by entry DTE, and by trend at entry (above/below the 20-day average)."""
    rows = [t for t in history()["trades"] if t["status"] == "Closed" and t.get("ret") is not None]
    by_b, by_t = {}, {"above": [], "below": []}
    for t in rows:
        dit = max(t.get("dit") or 1, 1)
        b = bucket(t.get("dte"))
        if b:
            by_b.setdefault(b, []).append((t["ret"], dit))
        tr = trend(t["und"], t["entry"])
        if tr:
            by_t["above" if tr["vs_sma20"] > 0 else "below"].append(t["ret"])
    out_b = {b: {"n": len(v), "ret": sum(r for r, _ in v) / len(v), "dit": sum(d for _, d in v) / len(v),
                 "per_day": sum(r / d for r, d in v) / len(v)} for b, v in by_b.items()}
    out_t = {k: {"n": len(v), "ret": sum(v) / len(v) if v else None} for k, v in by_t.items()}
    return {"by_dte": out_b, "by_trend": out_t, "n": len(rows), "speed": speed(rows, out_b),
            "now": {s: trend(s) for s in GRID}}


def speed(rows, by_b):
    """Capital pace (return on margin per day held). Target = what your closed 22-45 DTE A14s earned per day
    (config "speed_target" overrides); slow = under half of it. Plus your A14 pace by entry month."""
    cfg = load_config().get("speed_target")
    b = by_b.get("22–45")
    target = float(cfg) if cfg else (b["per_day"] if b and b["n"] >= 5 else 0.4)
    months = {}
    for t in rows:
        m = months.setdefault(t["entry"][:7], [])
        m.append((t["ret"] / max(t.get("dit") or 1, 1), t.get("dit") or 0, t.get("dte") or 0))
    by_m = [{"month": k, "n": len(v), "per_day": sum(x[0] for x in v) / len(v), "dit": sum(x[1] for x in v) / len(v),
             "dte": sum(x[2] for x in v) / len(v)} for k, v in sorted(months.items())]
    return {"target": target, "slow": target / 2, "source": "config" if cfg else "your closed 22–45 DTE A14s", "by_month": by_m}
