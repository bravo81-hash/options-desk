"""Trade readiness: one size call for new premium-selling trades, built from every tested input.

Common currency: the chance SPX fell 5% or more at some point in the next 21 sessions after days like today
(normally ~16%). Each input contributes its own historical estimate; the verdict uses the highest one (the
inputs overlap, so adding them would double count) and names which input set it:
* VIX level band (1990+) and the active VIX conditions (VIX/SPX/RUT/credit, 1990+);
* Market warnings, the five tested ones (2010+);
* sector rotation, offense vs defense (1999+).
Size: under 17% full, 17-23% three-quarter, 23-30% half, 30%+ (or any sit-out condition) stand aside.
Strategy rules then step individual structures down: A14 with VIX/VIX3M at 0.90+ (flat: one step, one more below
the 20-day average; backwardation: stand aside), thin RUT premium. Below the 20-day average with the term structure
normal (0.834-0.90) is not a step down: it was the model's best A14 cell since 2009 (45 DTE: SPX +2.2%, RUT +2.3% a
trade); in steep contango it still is (rare, and negative in the model: SPX -6.1% over 10 entries, RUT -0.9% over 43).
A14 also steps down one with VIX9D/VIX at 0.90+ in a steep or normal term structure (front of the curve under stress):
worse than below 0.90 in all 16 splits tested (SPX/RUT x 21-60 DTE x 2011-18 / 2019-26; SPX 45 DTE +4.3% vs 0.0% and
+2.3% vs -0.5%); calendars stand aside at
VIX/VIX3M 0.90+ and step down below the 20-day average or into high-impact US releases (CPI, FOMC, payrolls,
PCE, GDP) inside the next two sessions. The term-structure and trend rules are from the 2009-2026 model backtest
(desk/backtest.py): calendars entered under 0.90 with the index above its 20-day average averaged about +4%
of the debit a trade, those at 0.834-1.00 (the old gate) about -0.6%.
"""
import datetime as dt

from . import vixcond, warnings
from .a14 import stats as a14_stats, trend

STEPS = ["Stand aside", "Quarter size", "Half size", "Three-quarter size", "Full size"]
BIG = ("CPI", "FOMC", "Federal Funds", "Fed Chair", "Non-Farm", "Nonfarm", "PCE", "GDP", "Powell")


def size_for(p):
    return "Full size" if p < 17 else "Three-quarter size" if p < 23 else "Half size" if p < 30 else "Stand aside"


def step_down(size, n=1):
    return STEPS[max(0, STEPS.index(size) - n)]


def ivts_band(v):
    """One VIX/VIX3M scale for the whole app, with what each band means for each structure."""
    if v is None:
        return {"band": "unknown", "label": "–", "a14": "", "cal": ""}
    if v >= 1.0:
        return {"band": "backwardation", "label": "Backwardation", "a14": "stand aside: A14s entered here lost on average since 2009 (model)", "cal": "blocked: front IV above back"}
    if v >= 0.90:
        return {"band": "flat", "label": "Flat — stress building", "a14": "size down: A14s entered here lost on average since 2009 (model)",
                "cal": "avoid: calendars entered at 0.90+ lost on average since 2009 (model)"}
    if v > 0.834:
        return {"band": "normal", "label": "Normal contango", "a14": "ok", "cal": "ok"}
    return {"band": "steep", "label": "Steep contango — calm", "a14": "ok: calmest backdrop",
            "cal": "ok: the best calendar zone since 2009 (model); your June 2–4 losses were one shock"}


BANDS = ["steep", "normal", "flat", "backwardation"]


FRONT_LINE = 0.90  # VIX9D/VIX at or above this: the front of the curve is under stress


def a14_steps(band, trend_up, front=None):
    """Steps down for an A14 from the term-structure band, the short-term trend and VIX9D/VIX; None = stand aside."""
    if band == "backwardation":
        return None
    n = 1 if band == "flat" else 0
    if not trend_up and band != "normal":
        n += 1
    if band in ("steep", "normal") and front is not None and front >= FRONT_LINE:
        n += 1
    return n


def cal_steps(band, trend_up, front=None):
    """Steps down for a calendar (before the release rule); None = stand aside."""
    if band in ("flat", "backwardation"):
        return None
    return 0 if trend_up else 1


RULES = {"A14": a14_steps, "Calendar": cal_steps}


def apply(size, steps):
    return "Stand aside" if steps is None else step_down(size, steps)


def matrix(front=None):
    """What the term-structure, trend and front-of-curve rules do in every cell (at today's VIX9D/VIX), before the
    market size and the other flags."""
    return {name: {b: {t: f(b, t == "above", front) for t in ("above", "below")} for b in BANDS} for name, f in RULES.items()}


def _skew_note():
    """Information only: in a normal term structure the SKEW index split RUT A14 results in the model."""
    try:
        from . import backtest
        from .history import series
        R = backtest.cached()
        g = R["conds"]["A14 RUT"]["normal_skew"]
        sk = series("SKEW").dropna()
        v = float(sk.iloc[-1])
        b = "<126" if v < 126 else "126–142" if v < 142 else "142+"
        other = {"<126": ["142+"], "142+": ["<126"], "126–142": ["<126", "142+"]}[b]
        return (f"SKEW {v:.0f}: in a normal term structure RUT A14s averaged {g[b]['avg']:+.1f}% with SKEW {b} ({g[b]['n']} entries) vs "
                + " and ".join(f"{g[o]['avg']:+.1f}% at {o}" for o in other) + " (model, information only)")
    except Exception:
        return None


def _events():
    from .market import calendar
    today = dt.date.today()
    try:
        ev = calendar(today.isoformat(), (today + dt.timedelta(days=3)).isoformat()).get("result", [])
    except Exception:
        return []
    return [e for e in ev if any(k.lower() in e.get("title", "").lower() for k in BIG)]


def now():
    V = vixcond.now()
    W = warnings.now()
    base = V["base"]["dd5"]
    inputs = []
    b = V["bucket"]["stats"] or {}
    inputs.append({"name": f"VIX level {V['bucket']['range']}", "reading": f"VIX {V['readings']['vix']:.2f}", "dd5": b.get("dd5"), "n": b.get("n"), "since": b.get("since"), "kind": "level"})
    ts = W["total_stats"] or {}
    inputs.append({"name": f"Market warnings {W['total6']} of 6", "reading": ", ".join(c["label"] for c in W["components"] if c["on"]) or "none on",
                   "dd5": ts.get("dd5"), "n": ts.get("n"), "since": ts.get("since"), "kind": "warnings"})
    R = W["rotation"]
    rs = R["stats"] or {}
    inputs.append({"name": f"Sector rotation: {R['state']}", "reading": f"offense − defense {R['value']:+.1f} pts (20 days)" if R["value"] is not None else "–",
                   "dd5": rs.get("dd5"), "n": rs.get("n"), "since": rs.get("since"), "kind": "rotation"})
    for c in V["conditions"]:
        if c["active"] and c["stats"]:
            inputs.append({"name": c["label"], "reading": c["kind"], "dd5": c["stats"]["dd5"], "n": c["stats"]["n"], "since": c["stats"]["since"], "kind": c["kind"]})
    sit = [c for c in V["conditions"] if c["active"] and c["kind"] == "sitout"]
    scored = [i for i in inputs if i["dd5"] is not None]
    top = max(scored, key=lambda i: i["dd5"]) if scored else None
    risk = top["dd5"] if top else base
    size = "Stand aside" if sit else size_for(risk)
    why = (f"{sit[0]['label']} (sit-out rule)" if sit else
           f"{top['name']}: a 5% drop followed {top['dd5']:.0f}% of the time (normally {base:.0f}%)" if top else "no data")
    # trends (named the same everywhere)
    trends = {}
    for s in ("SPX", "RUT"):
        t = trend(s) or {}
        trends[s] = {"short": t.get("vs_sma20"), "short_up": (t.get("vs_sma20") or 0) > 0}
    trends["SPX"]["long"] = V["readings"].get("vs200")
    ivts = V["readings"].get("ivts")
    band = ivts_band(ivts)
    events = _events()
    rvx = V["readings"].get("rvx_spread")
    front = V["readings"].get("r9")  # VIX9D / VIX
    strat = []
    try:
        bt = a14_stats()["by_trend"]
        hist = f"your A14s entered like this averaged {bt['below']['ret']:.1f}% vs {bt['above']['ret']:.1f}% above it"
    except Exception:
        hist = "entries below the 20-day average have done worse"
    for sym in ("SPX", "RUT"):
        up = trends[sym]["short_up"]
        sz, notes = apply(size, a14_steps(band["band"], up, front)), []
        if band["band"] in ("backwardation", "flat"):
            notes.append(f"VIX/VIX3M {ivts:.3f}: {band['a14']}")
        if band["band"] in ("steep", "normal") and front is not None and front >= FRONT_LINE:
            notes.append(f"VIX9D/VIX {front:.3f} (0.90+): one step down: front-of-curve stress; A14s entered like this did worse in every split since 2011 (model)")
        if not up:
            notes.append(f"{sym} below its 20-day average: " + (f"one step down with the term structure {band['band']}; {hist}"
                         if band["band"] != "normal" else "no step down with a normal term structure: the model's best A14 cell since 2009"))
        if sym == "RUT" and rvx is not None and rvx <= 3:
            sz = step_down(sz)
            notes.append(f"RVX only {rvx:+.1f} over VIX: thin RUT premium, SPX preferred")
        if sym == "RUT" and rvx is not None and rvx >= 8:
            notes.append(f"RVX {rvx:+.1f} over VIX: rich RUT premium")
        if sym == "RUT" and band["band"] == "normal":
            n = _skew_note()
            if n:
                notes.append(n)
        strat.append({"name": f"A14 {sym}", "size": sz, "notes": notes or ["no strategy-specific flags"]})
    for sym in ("SPX", "RUT"):
        sz, notes = apply(size, cal_steps(band["band"], trends[sym]["short_up"])), []
        if band["band"] in ("backwardation", "flat"):
            notes.append(f"VIX/VIX3M {ivts:.3f}: {band['cal']}")
        if not trends[sym]["short_up"]:
            notes.append(f"{sym} below its 20-day average: SPX calendars entered like this lost on average since 2009 (model)")
        if events:
            sz = step_down(sz)
            notes.append("High-impact release within 3 days (" + ", ".join(sorted({e['title'] for e in events})) + "): TimeEdge rule says don't enter into it")
        vv = next((c for c in V["conditions"] if c["id"] == "vvix_calm" and c["active"]), None)
        if vv:
            notes.append("VVIX high with VIX calm: calendars (long vega) fit better than short vega")
        strat.append({"name": f"Calendar {sym}", "size": sz, "notes": notes or ["no strategy-specific flags"]})
    opps = [c["label"] for c in V["conditions"] if c["active"] and c["kind"] == "take"]
    return {"size": size, "why": why, "risk": risk, "base": base, "inputs": inputs, "strategies": strat, "opportunities": opps,
            "ivts": ivts, "ivts_band": band, "trends": trends, "matrix": matrix(front), "front": front, "events": events, "date": V["readings"]["date"],
            "warnings": {"total5": W["total5"], "total6": W["total6"], "stats": W["total_stats"], "all": W["all_totals"]},
            "rotation": R}
