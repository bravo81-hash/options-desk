"""Market conditions matrix: one row per signal from the Market, Term structure, Skew & IV, Expected moves and
Seasonality tabs, with today's reading and what entries in the same bucket made since 2009 for each structure
(model backtest, desk/backtest.py, after costs). Evidence only: the size call stays with the readiness bar, and
the last column says whether and how each signal feeds it.
"""
from . import backtest, readiness

STRUCTS = ["A14 SPX", "A14 RUT", "Calendar SPX", "Calendar RUT"]
MIN_N = 30   # fewer entries than this in a bucket: shown, but not called either way
EDGE = 1.0   # a bucket within 1 point of the structure's overall average counts as neutral
PER_INDEX = {"trend", "vrp_b"}  # readings that differ between SPX and RUT
IN_SIZE = {
    "vix_band": "yes: VIX level band sets the market size (drop odds)",
    "spx200": "at the extreme: SPX below its 200-day is a VIX condition (caution)",
    "trend": "yes: A14 one step down outside a normal term structure; calendars one step down",
    "ivts_band": "yes: A14 step down when flat, stand aside in backwardation; calendars stand aside at 0.90+",
    "front": "yes: A14 one step down at 0.90+ in a steep or normal term structure; 1.00+ is also a VIX condition (caution)",
    "ivpct": "no",
    "skew_b": "no: note on RUT A14s in a normal term structure",
    "vvix_b": "at the extreme: VVIX 110+ with VIX under 18 is a VIX condition (caution)",
    "rvxs": "yes: RUT A14 one step down under 3",
    "vrp_b": "at the extremes: under 0 is a caution condition, 8+ an opportunity",
    "season": "no",
}
FMT = {"vix": "VIX {:.1f}", "spx200_pct": "{:+.1f}% vs 200-day", "front_r": "{:.3f}", "vix_pct": "{:.0f}th percentile",
       "skew": "SKEW {:.0f}", "vvix": "VVIX {:.0f}", "rvx_spread": "{:+.1f} pts", "vrp": "{:+.1f} pts", "season_up": "{:.0f}% of years up"}
FIELD = {k: f for k, (_, _, f, _, _) in backtest.COND.items()}


def _effect(cell, base):
    if not cell:
        return {"effect": "none"}
    d = cell["avg"] - base["avg"]
    eff = "thin" if cell["n"] < MIN_N else "helps" if d >= EDGE else "hurts" if d <= -EDGE else "neutral"
    return {"effect": eff, "avg": cell["avg"], "win": cell["win"], "n": cell["n"], "base": base["avg"], "diff": round(d, 2)}


def _reading(k, T):
    f = FIELD.get(k)
    def one(u):
        c = T[u]
        if k == "trend":
            return f"{u} {c['trend']}"
        if k == "ivts_band":
            return f"{c['ivts']:.3f} ({c['ivts_band']})"
        v = c["raw"].get(f)
        return "–" if v is None else FMT[f].format(v)
    return " · ".join(f"{u} {one(u)}" if k == "vrp_b" else one(u) for u in ("SPX", "RUT")) if k in PER_INDEX else one("SPX")


def now():
    R = backtest.cached() or backtest.results()
    if not R or not R.get("conds"):
        return {"running": True, "error": (R or {}).get("error")}
    T = backtest.conditions_now()
    rd = readiness.now()
    rows = []
    for k, d in R["cond_defs"].items():
        cells = {}
        for s in STRUCTS:
            u = s.split()[1]
            b = T[u].get(k)
            groups = R["conds"][s].get(k, {})
            if k == "trend":  # the trend's effect depends on the term structure: use today's band, as the size rule does
                groups = R["matrix"][s]["cells"].get(T[u]["ivts_band"], {})
            dist = [{"b": x, "avg": groups[x]["avg"], "n": groups[x]["n"], "sel": x == b} for x in d["buckets"] if groups.get(x)]
            cells[s] = {"bucket": b, "dist": dist, **_effect(groups.get(b), R["conds"][s]["all"])}
        if k == "rvxs":  # the RUT premium only matters for RUT structures
            for s in ("A14 SPX", "Calendar SPX"):
                cells[s] = {"effect": "n/a"}
        label = d["label"] + (f" (with VIX/VIX3M {T['SPX']['ivts_band']})" if k == "trend" else "")
        rows.append({"key": k, "tab": d["tab"], "label": label, "reading": _reading(k, T), "buckets": d["buckets"],
                     "in_size": IN_SIZE.get(k, "no"), "cells": cells})
    # tested on drop odds, not on the structures: the market-size inputs from the Market tab
    odds = [{"name": i["name"], "reading": i["reading"], "dd5": i["dd5"], "n": i["n"], "since": i["since"]}
            for i in rd["inputs"] if i["kind"] in ("warnings", "rotation", "level") or i["kind"] in ("caution", "sitout", "take")]
    season = None
    try:
        from .season import compute
        S = compute("SPX")
        season = {"cycle": S.get("cycle_now"), "fwd21": next((f for f in S.get("forward", []) if f["h"] == 21), None)}
    except Exception:
        pass
    return {"date": T["date"], "rows": rows, "odds": odds, "base_dd5": rd["base"], "size": rd["size"], "why": rd["why"],
            "strategies": {s["name"]: s for s in rd["strategies"]}, "events": rd["events"], "season": season,
            "rules": {"min_n": MIN_N, "edge": EDGE},
            "basis": {"A14": "45 DTE, your median shape, revised exits; % of max loss",
                      "Calendar": "15/22 DTE ATM put calendar, target 5% stop −15%; % of the debit"}}
