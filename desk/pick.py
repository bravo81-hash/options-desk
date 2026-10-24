"""Today's pick: which structure (put calendar = time spread, or A14 put BWB = single expiry) on which index
(SPX or RUT) has the better edge right now.

Both structures are priced from the same TWS chain (the A14 scanner's), with the same smile, the same exit
horizon and the same odds (lognormal at the chosen vol), so their expected returns are comparable. On top of
that model edge come your own rules and track record:
* calendars: VIX/VIX3M below 0.90 and the index above its 20-day average (2009-2026 model backtest; the old
  0.834 line came from one cluster of June 2026 losses); TimeEdge / Triple Calendar / TimeZone gates; your
  calendar-family results above and below 0.834 as context;
* A14: the index above or below its 20-day average, and your A14 results in each case.
The model edge is ranked per day held, so a calendar held to its front expiry and a BWB held for the
exit days compete on how hard the capital works.
"""
import json
import math

import numpy as np

from . import a14, db
from .history import series

IVTS_LINE = 0.834  # your own calendar record is still split here (context only)
CAL_MAX_IVTS = 0.90  # calendar gate from the backtest


def _ivts():
    v, v3 = series("VIX").dropna(), series("VIX3M").dropna()
    return float(v.iloc[-1] / v3.iloc[-1]) if len(v) and len(v3) else None


def calendars(sym, exit_days=14, vol_basis="rv20", top=10):
    """Put calendars (short front, long back, same strike) on the A14 chain, scored like the BWBs."""
    blob = json.loads(db.get_meta("a14_chain") or "{}")
    sb = blob.get("symbols", {}).get(sym)
    if not sb:
        return []
    S0, step = sb["spot"], a14.GRID[sym]["step"]
    sms = a14._smiles(sb)
    rv = a14.realised_vol(sym)
    exps = sorted((e for e in sms if 7 <= sms[e]["dte"] <= 50), key=lambda e: sms[e]["dte"])
    out = []
    for f in exps:
        fs = sms[f]
        backs = [e for e in sms if fs["dte"] + 6 <= sms[e]["dte"] <= fs["dte"] + 60]
        atm_k = round(fs["F"] / step) * step
        for b in backs:
            bs_ = sms[b]
            for k in (atm_k, atm_k - step, atm_k - 2 * step):
                if k not in fs["strikes"] or k not in bs_["strikes"]:
                    continue
                ivf, ivb = float(a14._iv_at(fs, k)), float(a14._iv_at(bs_, k))
                pf = float(a14.put_price(fs["F"], k, fs["T"], ivf))
                pb = float(a14.put_price(bs_["F"], k, bs_["T"], ivb))
                debit = pb - pf
                if debit <= 0.05:
                    continue
                h = min(exit_days, max(fs["dte"] - 1, 1))
                atm = float(a14._iv_at(fs, fs["F"]))
                sd_h = atm * math.sqrt(h / 365)
                x = np.linspace(-4 * sd_h, 3 * sd_h, 71)
                Fh = fs["F"] * np.exp(x)
                Tf, Tb = max(fs["T"] - h / 365, 1e-6), max(bs_["T"] - h / 365, 1e-6)

                def value(F, dv=0.0):
                    return a14.put_price(F * bs_["F"] / fs["F"], k, Tb, ivb + dv) - a14.put_price(F, k, Tf, ivf + dv)

                pnl_h = (value(Fh) - debit) * 100
                sig = {"rv20": rv or atm * 0.8, "iv": atm}.get(vol_basis, atm)
                sig_h = sig * math.sqrt(h / 365)
                w = np.exp(-0.5 * ((x + 0.5 * sig_h ** 2) / sig_h) ** 2)
                w /= w.sum()
                e_h = float(pnl_h @ w)
                risk = debit * 100
                t_now = (float(a14.put_price(bs_["F"], k, bs_["T"] - 1 / 365, ivb) - a14.put_price(fs["F"], k, fs["T"] - 1 / 365, ivf)) - debit) * 100
                vega = (float(a14.put_price(bs_["F"], k, bs_["T"], ivb + 0.01) - a14.put_price(fs["F"], k, fs["T"], ivf + 0.01)) - debit) * 100
                i1 = int(np.argmin(np.abs(x + sd_h)))
                ivdrop = float(((value(Fh, -0.02) - debit) * 100) @ w)
                out.append({"structure": "calendar", "sym": sym, "front": f, "back": b, "fdte": fs["dte"], "bdte": bs_["dte"], "strike": k,
                            "strike_pct": 100 * (k / S0 - 1), "debit": round(debit, 2), "risk": round(risk), "h": h,
                            "exp_h": round(e_h), "exp_risk": 100 * e_h / risk, "exp_day": 100 * e_h / risk / h,
                            "pop_h": float((pnl_h > 0) @ w), "theta": round(t_now, 2), "vega": round(vega, 2),
                            "down1sd_h": round(float(pnl_h[i1])), "iv_drop2": round(ivdrop),
                            "contango": 100 * (ivb - ivf),
                            "label": f"{sym} {int(k)}P {f[4:6]}/{f[6:]} → {b[4:6]}/{b[6:]}"})
    out.sort(key=lambda c: -c["exp_day"])
    return out[:top]


def bwbs(sym, exit_days=14, vol_basis="rv20", top=10):
    res = a14.scan(symbols=(sym,), exit_days=exit_days, vol_basis=vol_basis)
    cs = [c for c in res.get("candidates", []) if c["usual"]] or res.get("candidates", [])
    for c in cs:
        c["structure"] = "bwb"
        c["exp_day"] = c["exp_risk"] / max(c["h"], 1)
        c["label"] = f"{sym} {int(c['upper'])}/{int(c['short'])}/{int(c['lower'])} {c['expiry'][4:6]}/{c['expiry'][6:]}"
    cs.sort(key=lambda c: -c["exp_day"])
    return cs[:top]


def _calendar_record(evidence_trades):
    """Your calendar-family trades split at VIX/VIX3M 0.834."""
    out = {}
    for side, test in (("above", lambda v: v > IVTS_LINE), ("below", lambda v: v <= IVTS_LINE)):
        t = [x for x in evidence_trades if x.get("vix_vix3m") is not None and test(x["vix_vix3m"])]
        out[side] = {"n": len(t), "win": sum(1 for x in t if x["pnl"] > 0) / len(t) if t else None,
                     "pnl": sum(x["pnl"] for x in t), "avg": sum(x["pnl"] for x in t) / len(t) if t else None}
    return out


def _cal_band_odds(ivts):
    """Backtest line for today's VIX/VIX3M step (TimeEdge card exits), or '' while it is computing."""
    from .backtest import results
    try:
        fine = results().get("cal", {}).get("fine") or []
        b = next((x for x in fine if x["lo"] <= ivts < x["hi"]), None)
        return f": since 2009, calendars entered at {b['lo']:.2f}–{min(b['hi'], 9):.2f} averaged {b['avg']:+.1f}% of the debit, {round(100 * b['win'])}% winners ({b['n']}, model)" if b else ""
    except Exception:
        return ""


def today(exit_days=14, vol_basis="rv20"):
    from . import analytics
    if not db.get_meta("a14_chain"):
        return {"error": "No chain yet: press Fetch chain on the A14 scanner (TWS must be running)."}
    ivts = _ivts()
    st = a14.stats()
    ev = analytics.evidence()
    cal_rec = _calendar_record(ev.get("trades", []))
    gates = {}
    for sym in ("SPX", "RUT"):
        try:
            gates[sym] = analytics.calendar_scan(sym).get("gates", [])
        except Exception:
            gates[sym] = []
    cells = []
    for sym in ("SPX", "RUT"):
        tr = st["now"].get(sym) or {}
        up = (tr.get("vs_sma20") or 0) > 0
        b = bwbs(sym, exit_days, vol_basis)
        c = calendars(sym, exit_days, vol_basis)
        bt = st["by_trend"]["above" if up else "below"]
        checks_b = [{"ok": up, "text": f"Short-term trend (20-day): {sym} {'above' if up else 'below'} its average ({tr.get('vs_sma20', 0):+.1f}%): your A14s averaged {bt['ret']:.1f}% ({bt['n']} trades) entered like this"}]
        g_list = gates.get(sym, [])
        side = "above" if ivts is not None and ivts > IVTS_LINE else "below"
        checks_c = [{"ok": ivts is not None and ivts < CAL_MAX_IVTS,
                     "text": f"VIX/VIX3M {ivts:.3f} {'below' if ivts is not None and ivts < CAL_MAX_IVTS else 'at or above'} 0.90{_cal_band_odds(ivts)}"
                             f"; your own calendars {'above' if side == 'above' else 'at or below'} 0.834: ${cal_rec[side]['pnl']:,.0f} over {cal_rec[side]['n']} trades"}]
        for g in g_list:
            checks_c.append({"ok": g["pass"], "text": f"{g['name']} rules {'pass' if g['pass'] else 'fail'}: " +
                             "; ".join(f"{t} ({v})" for t, ok_, v in g["checks"] if not ok_) if not g["pass"] else f"{g['name']} rules pass"})
        for struct, best, checks in (("bwb", b[0] if b else None, checks_b), ("calendar", c[0] if c else None, checks_c)):
            passed = sum(1 for x in checks if x["ok"])
            cells.append({"sym": sym, "structure": struct, "best": best, "alts": (b if struct == "bwb" else c)[1:4],
                          "checks": checks, "checks_ok": passed == len(checks), "checks_passed": passed, "checks_n": len(checks)})
    # pick: best model edge per day among cells whose own-rule checks all pass; fall back to the best partial
    ranked = sorted([x for x in cells if x["best"]], key=lambda x: (x["checks_ok"], x["checks_passed"] / max(x["checks_n"], 1), x["best"]["exp_day"]), reverse=True)
    pick = ranked[0] if ranked else None
    for i, x in enumerate(ranked):
        x["rank"] = i + 1
    return {"ivts": ivts, "trend": st["now"], "cells": cells, "pick": pick and {"sym": pick["sym"], "structure": pick["structure"]},
            "chain_ts": json.loads(db.get_meta("a14_chain"))["ts"], "exit_days": exit_days, "vol_basis": vol_basis, "cal_record": cal_rec,
            "a14_trend": st["by_trend"]}
