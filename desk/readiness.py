"""Trade readiness: one size call for new premium-selling trades, built from every tested input.

Common currency: the chance SPX fell 5% or more at some point in the next 21 sessions after days like today
(normally ~16%). Each input contributes its own historical estimate; the verdict uses the highest one (the
inputs overlap, so adding them would double count) and names which input set it:
* VIX level band (1990+) and the active VIX conditions (VIX/SPX/RUT/credit, 1990+);
* Market warnings, the five tested ones (2010+);
* sector rotation, offense vs defense (1999+).
Size: under 17% full, 17-23% three-quarter, 23-30% half, 30%+ (or any sit-out condition) stand aside.
Strategy rules then step individual structures down: A14 below the 20-day average (your A14 history),
thin RUT premium, calendars at VIX/VIX3M <= 0.834 (your June losses) or >= 1 (backwardation), and
high-impact US releases (CPI, FOMC, payrolls, PCE, GDP) inside the next two sessions for calendars.
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
        return {"band": "backwardation", "label": "Backwardation", "a14": "wait for it to end (next leg down is common)", "cal": "blocked: front IV above back"}
    if v >= 0.90:
        return {"band": "flat", "label": "Flat — stress building", "a14": "caution: short vega, size down", "cal": "ok"}
    if v > 0.834:
        return {"band": "normal", "label": "Normal contango", "a14": "ok", "cal": "ok"}
    return {"band": "steep", "label": "Steep contango — calm", "a14": "ok: calmest backdrop", "cal": "avoid: your June calendar losses were entered here"}


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
    inputs.append({"name": f"Market warnings {W['total5']} of 5 tested", "reading": ", ".join(c["label"] for c in W["components"] if c["on"]) or "none on",
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
    strat = []
    try:
        bt = a14_stats()["by_trend"]
        hist = f"your A14s entered like this averaged {bt['below']['ret']:.1f}% vs {bt['above']['ret']:.1f}% above it"
    except Exception:
        hist = "entries below the 20-day average have done worse"
    for sym in ("SPX", "RUT"):
        sz, notes = size, []
        if not trends[sym]["short_up"]:
            sz = step_down(sz)
            notes.append(f"{sym} below its 20-day average (short-term trend): {hist}")
        if band["band"] in ("backwardation", "flat"):
            notes.append(f"VIX/VIX3M {ivts:.3f}: {band['a14']}")
        if sym == "RUT" and rvx is not None and rvx <= 3:
            sz = step_down(sz)
            notes.append(f"RVX only {rvx:+.1f} over VIX: thin RUT premium, SPX preferred")
        if sym == "RUT" and rvx is not None and rvx >= 8:
            notes.append(f"RVX {rvx:+.1f} over VIX: rich RUT premium")
        strat.append({"name": f"A14 {sym}", "size": sz, "notes": notes or ["no strategy-specific flags"]})
    for sym in ("SPX", "RUT"):
        sz, notes = size, []
        if band["band"] == "backwardation":
            sz, notes = "Stand aside", [f"VIX/VIX3M {ivts:.3f}: {band['cal']}"]
        elif band["band"] == "steep":
            sz = "Stand aside"
            notes.append(f"VIX/VIX3M {ivts:.3f}: {band['cal']}")
        if events:
            sz = step_down(sz)
            notes.append("High-impact release within 3 days (" + ", ".join(sorted({e['title'] for e in events})) + "): TimeEdge rule says don't enter into it")
        vv = next((c for c in V["conditions"] if c["id"] == "vvix_calm" and c["active"]), None)
        if vv:
            notes.append("VVIX high with VIX calm: calendars (long vega) fit better than short vega")
        strat.append({"name": f"Calendar {sym}", "size": sz, "notes": notes or ["no strategy-specific flags"]})
    opps = [c["label"] for c in V["conditions"] if c["active"] and c["kind"] == "take"]
    return {"size": size, "why": why, "risk": risk, "base": base, "inputs": inputs, "strategies": strat, "opportunities": opps,
            "ivts": ivts, "ivts_band": band, "trends": trends, "events": events, "date": V["readings"]["date"],
            "warnings": {"total5": W["total5"], "total6": W["total6"], "stats": W["total_stats"], "all": W["all_totals"]},
            "rotation": R}
