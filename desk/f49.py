"""F49: the far-OTM put tent (the user's idea of 9 Nov 2026, named 11 Nov). A put broken-wing butterfly 1/-2/1 whose shorts sit one
at-the-money straddle below the index (about 0.8 sd), at the Friday expiry nearest 49 days. The wings are in straddle units too:
upper long UP_X above the shorts, lower long LOW_X below (100 and 150 points on SPX on 9 Nov).

The card is what was tested on 9 Nov, nothing more: +7% target, exit on a close below the shorts, out at 14 DTE, never adjusted,
Friday entries, at most CAP ids a ticker, the A14 readiness size. That test (SPX, 2009-2026, skew refitted on 18 recorded days) made
+4.6% a year with a 10.5% drawdown; the edge rests on that short skew record and on fills, so it is thin. This scanner prices the
shape off the fetched chain's own quotes. Read-only: a reference, not an order."""
import datetime as dt
import json

import numpy as np

from . import a14, a14rules, db

SHORT_X, UP_X, LOW_X = 1.0, 0.2375, 0.3575  # in straddles: shorts below spot, upper long above the shorts, lower long below them
SHORTS = (0.9, 1.0, 1.1)  # the candidates shown: a little nearer, the rule, a little further
TARGET, TIME_DTE, CAP = 7.0, 14, 4
WORST_NAV = 7.5  # an id's worst case at full size, % of NAV: the size the test used (the A14 rule's)
W = np.array([1.0, -2.0, 1.0])


def straddle(sb, expiry):
    """(strike, price): the call and put mids at the strike nearest the forward."""
    rows = [r for r in sb["rows"] if r["expiry"] == expiry and r.get("mid")]
    F = next((r["fwd"] for r in rows if r.get("fwd")), sb["spot"])
    both = {}
    for r in rows:
        both.setdefault(r["strike"], {})[r["right"]] = r["mid"]
    ks = [k for k, v in both.items() if "C" in v and "P" in v]
    if not ks:
        return None, None
    k = min(ks, key=lambda x: abs(x - F))
    return k, both[k]["C"] + both[k]["P"]


def candidate(sym, sb, sm, expiry, em, x):
    """One tent with its shorts x straddles below spot, priced on the chain's quotes (the smile where a quote is missing)."""
    S, ks = sb["spot"], sm["strikes"]
    near = lambda v: min(ks, key=lambda k: abs(k - v))  # noqa: E731
    short = near(S - x * em)
    upper, lower = near(short + UP_X * em), near(short - LOW_X * em)
    reach = short - LOW_X * em >= ks[0] - 1e-9
    if not (lower < short < upper) or short - lower < upper - short:
        return None
    K, F, T = np.array([upper, short, lower], float), sm["F"], sm["T"]
    ivs = a14._iv_at(sm, K)
    q = {r["strike"]: r for r in sb["rows"] if r["expiry"] == expiry and r["right"] == "P"}
    model = a14.put_price(F, K, T, ivs)
    mids = [q.get(k, {}).get("mid") for k in K]
    quoted = all(m for m in mids)
    px = np.array(mids, float) if quoted else model
    credit = -float((px * W).sum())
    nat = None
    if all(q.get(k, {}).get("bid") and q.get(k, {}).get("ask") for k in K):
        nat = -(q[upper]["ask"] - 2 * q[short]["bid"] + q[lower]["ask"])  # buy the longs at the ask, sell the shorts at the bid
    U, L = upper - short, short - lower
    risk = max(L - U - credit, -credit, 0.05) * 100
    off = float((model * W).sum()) + credit  # the quotes against the smile model, so the curves start at 0
    val = lambda f, t, bump=0.0: float((a14.put_price(f, K, max(t, 1e-6), ivs + bump) * W).sum())  # noqa: E731
    pnl = lambda f, t, bump=0.0: (val(f, t, bump) - val(F, T)) * 100  # noqa: E731
    h, fs = F * 5e-4, F * short / S
    t14 = TIME_DTE / 365
    xs = sorted({float(v) for v in np.linspace(lower - 1.5 * L, S * 1.04, 61)} | {float(upper), float(short), float(lower)})  # the strikes too, so the peak is drawn
    return {"sym": sym, "x": x, "expiry": expiry, "dte": sm["dte"], "upper": upper, "short": short, "lower": lower, "U": U, "L": L, "below_pct": round(100 * (short / S - 1), 2),
            "credit": round(credit, 2), "credit_nat": None if nat is None else round(nat, 2), "quoted": quoted, "model_gap": round(off, 2), "risk": round(risk),
            "credit_pct": round(100 * credit * 100 / risk, 1), "delta": round((val(F + h, T) - val(F - h, T)) / (2 * h) * 100, 2),
            "theta": round((val(F, T - 1 / 365) - val(F, T)) * 100, 1), "vega": round((val(F, T, 0.01) - val(F, T)) * 100, 1),
            "at_shorts": {"now": round(pnl(fs, T)), "wk2": round(pnl(fs, T - 14 / 365)), "wk2_iv5": round(pnl(fs, T - 14 / 365, 0.05)), "d14": round(pnl(fs, t14))},
            "target_usd": round(risk * TARGET / 100), "reach": reach,
            "curve": {"xs": [round(v, 1) for v in xs], "now": [round(pnl(F * v / S, T)) for v in xs], "d14": [round(pnl(F * v / S, t14)) for v in xs],
                      "exp": [round((float((np.maximum(K - v, 0) * W).sum()) + credit) * 100) for v in xs]}}


def scan(blob, sizes, nav):
    """{ticker: {expiry, straddle, cands, note}} off the fetched chain. sizes: the readiness bar's size per ticker; nav: the smaller NAV, US$."""
    out = {}
    for sym in ("SPX", "RUT"):
        sb = (blob.get("symbols") or {}).get(sym)
        if not sb:
            out[sym] = {"note": "No chain fetched for this ticker."}
            continue
        sms = a14._smiles(sb)
        e = a14rules.expiry_for(sms)
        if not e:
            out[sym] = {"note": f"No Friday expiry in {a14rules.DTE_LO}–{a14rules.DTE_HI} DTE on the fetched chain."}
            continue
        k, em = straddle(sb, e)
        if not em:
            out[sym] = {"note": "No at-the-money call and put quotes on that expiry: fetch the chain with the market open."}
            continue
        size = sizes.get(sym)
        cands = [c for c in (candidate(sym, sb, sms[e], e, em, x) for x in SHORTS) if c]
        for c in cands:
            full = int(nav * WORST_NAV / 100 / c["risk"]) if nav and c["risk"] > 0 else None
            c["lots_full"] = full
            c["lots"] = None if full is None or size is None else int(nav * WORST_NAV / 100 * a14rules.STEP_SIZE.get(size, 0.0) / c["risk"])
            c["rule"] = c["x"] == SHORT_X
        short_reach = [c for c in cands if not c["reach"]]
        out[sym] = {"spot": sb["spot"], "expiry": e, "dte": sms[e]["dte"], "straddle": round(em, 2), "straddle_k": k, "em_pct": round(100 * em / sb["spot"], 2), "size": size, "cands": cands,
                    "note": "The fetched chain stops above the lower long: fetch the chain again (it now reaches further down for these expiries)." if short_reach or not cands else None}
    return out


def state(ready=None):
    """Everything the F49 panel shows: the card, the candidates per ticker, the size and the cap they are read against."""
    from . import journal, limitcfg
    J = journal.closed()
    navs = dict(J["nav_now"])
    a14navs = {a: v for a, v in navs.items() if a in {r["acct"] for r in J["book"] if r["strategy"] in ("A14", "F49")}} or navs
    nav = min(a14navs.values()) if a14navs else None
    sizes = {s["name"].split()[-1]: s["size"] for s in (ready or {}).get("strategies") or [] if s["name"].startswith("A14 ")}
    raw = db.get_meta("a14_chain")
    blob = json.loads(raw) if raw else {}
    today = dt.datetime.now(a14rules.ET).date()
    return {"card": {"target": TARGET, "time_dte": TIME_DTE, "cap": CAP, "worst_nav": WORST_NAV, "short_x": SHORT_X, "up_x": UP_X, "low_x": LOW_X,
                     "entry_dte": a14rules.ENTRY_DTE, "dte_lo": a14rules.DTE_LO, "dte_hi": a14rules.DTE_HI},
            "chain_ts": blob.get("ts"), "navs": a14navs, "nav": nav, "entry_day": a14rules.entry_day(today), "entry_next": a14rules.entry_next(today).isoformat(),
            "cap_pct": limitcfg.value("cap:F49"), "sizes_known": bool(sizes), "scan": scan(blob, sizes, nav) if blob else {}}
