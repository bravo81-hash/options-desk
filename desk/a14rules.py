"""The A14 rule page, approved 2026-11-02. One place for what the trade plan, the next-id panel, the scanner and the Journal read.

One structure, sized by what the stop can lose: at Full size an id loses STOP_NAV % of NAV at the card's stop, which makes its worst
case 7.5% of NAV. Both accounts trade the same lots, worked out on the smaller NAV, so neither goes over; the readiness bar scales it
and nothing else does. A new id goes on each Friday per ticker at the Friday expiry nearest ENTRY_DTE, unless CAP ids are open. Risk is
never added to an id: new risk is a new id. Adjustments wait for a window day; targets and stops are watched every day. An id is out
by the card's time stop. The tent shifts TILT_SD with the index more than TILT_LINE % from its 20-day average.

The target is 1% of NAV a week per account, judged on a TARGET_WEEKS average because a single week is mostly noise.
"""
import datetime as dt
import json

import numpy as np

FROM = "2026-11-02"  # nothing before this is scored on these rules
STOP_NAV = 1.5  # % of NAV lost at the card's stop, at Full size
ENTRY_DTE, DTE_LO, DTE_HI = 49, 42, 56
TIME_BEFORE = 2  # the card's time stop for ids entered before FROM
CAP = 4  # open ids per ticker and account
WINDOWS = (0, 2, 4)  # adjustments: Monday, Wednesday, Friday, US dates
ENTRY_DAY = 4  # Friday
TILT_SD, TILT_LINE = 0.2, 1.0
WEEK_TARGET, TARGET_WEEKS = 1.0, 13
STEP_SIZE = {"Full size": 1.0, "Three-quarter size": 0.75, "Half size": 0.5, "Quarter size": 0.25, "Stand aside": 0.0}


def rule():
    """The rule page as data, for the pages that print it."""
    from .positions import CARDS
    stop = CARDS["A14"]["stop"]
    return {"from": FROM, "stop_nav": STOP_NAV, "stop": stop, "worst_nav": round(100 * STOP_NAV / stop, 2), "entry_dte": ENTRY_DTE, "dte_lo": DTE_LO, "dte_hi": DTE_HI, "time_dte": CARDS["A14"]["time"],
            "cap": CAP, "windows": list(WINDOWS), "entry_day": ENTRY_DAY, "tilt_sd": TILT_SD, "tilt_line": TILT_LINE, "week_target": WEEK_TARGET, "target_weeks": TARGET_WEEKS}


def tilt(vs20):
    """Shift of the tent in sd units: up with the index over 1% above its 20-day average, down over 1% below, else centred."""
    return 0.0 if vs20 is None or abs(vs20) <= TILT_LINE else TILT_SD if vs20 > 0 else -TILT_SD


def expiry_for(smiles):
    """The Friday expiry nearest ENTRY_DTE inside the entry window; the sooner one on a tie, so an id never starts long."""
    fri = {e: s for e, s in smiles.items() if DTE_LO <= s["dte"] <= DTE_HI and dt.datetime.strptime(e, "%Y%m%d").weekday() == 4}
    return min(fri, key=lambda e: (abs(fri[e]["dte"] - ENTRY_DTE), fri[e]["dte"]), default=None)


def strikes(S, sd, geom, shift, avail):
    """The desk's shape (backtest.GEOM, in model sd units) on the strikes listed, keeping the lower wing at least as wide as the upper."""
    up0, Uw, Lw = geom
    ks = sorted(avail)
    near = lambda x: min(ks, key=lambda k: abs(k - x))  # noqa: E731
    upper = S * (1 + (up0 + shift) * sd)
    short = upper * (1 - Uw * sd)
    u, s, l = near(upper), near(short), near(short - S * Lw * sd)
    while s - l < u - s and ks.index(l) > 0:
        l = ks[ks.index(l) - 1]
    return float(u), float(s), float(l)


def lots(risk, nav, size):
    """Lots of a given worst case (US$ a lot) that fit the rule on this NAV at this readiness size."""
    from .positions import CARDS
    return int(nav * STOP_NAV / CARDS["A14"]["stop"] * STEP_SIZE.get(size, 0.0) / risk) if risk > 0 else 0


def next_id(sym, blob, D, nav):
    """What the rule opens today on this ticker, priced off the fetched chain. None without a chain or a Friday in the window."""
    from . import a14, backtest
    sb = blob.get("symbols", {}).get(sym)
    if not sb:
        return None
    sms = a14._smiles(sb)
    e = expiry_for(sms)
    if not e:
        return None
    sm, tr = sms[e], a14.trend(sym) or {}
    shift = tilt(tr.get("vs_sma20"))
    K = strikes(sb["spot"], backtest.sd_now(D, sym, sm["dte"]), backtest.GEOM[sym], shift, sm["strikes"])
    C, F, T = np.array(K), sm["F"], sm["T"]
    ivs = a14._iv_at(sm, C)
    wts = np.array([1, -2, 1])
    val = lambda t, bump=0.0: float((a14.put_price(F, C, t, ivs + bump) * wts).sum())  # noqa: E731
    v0 = val(T)
    credit = -v0
    U, L = K[0] - K[1], K[1] - K[2]
    risk = max(L - U - credit, -credit, 0.05) * 100
    return {"sym": sym, "expiry": e, "dte": sm["dte"], "upper": K[0], "short": K[1], "lower": K[2], "U": U, "L": L, "credit": round(credit, 2),
            "risk": round(risk), "theta": round((val(max(T - 1 / 365, 1e-6)) - v0) * 100, 2), "vega": round((val(T, 0.01) - v0) * 100, 2),
            "tilt": shift, "vs20": tr.get("vs_sma20"), "lots": {k: lots(risk, nav, k) for k in STEP_SIZE} if nav else {}}


def target(weekly, labels):
    """{label: {now, weeks, series}}: each traded account's weekly % of NAV and its rolling TARGET_WEEKS average, finished weeks only."""
    names = {a["id"]: a["label"] for a in weekly.get("accounts", [])}
    done = [w for w in sorted(weekly.get("weeks", []), key=lambda w: w["week"]) if not any("week to date" in n for n in w.get("notes") or [])]
    out = {}
    for ac, name in names.items():
        if name not in labels:
            continue
        rows = [(w["week"], w["acct"][ac]["pct"]) for w in done if (w["acct"].get(ac) or {}).get("pct") is not None]
        vals = [v for _, v in rows]
        series = [{"d": rows[i][0], "v": round(sum(vals[i + 1 - TARGET_WEEKS:i + 1]) / TARGET_WEEKS, 3)} for i in range(TARGET_WEEKS - 1, len(rows))]
        recent = vals[-TARGET_WEEKS:]
        out[name] = {"now": series[-1]["v"] if series else None, "n": len(recent), "hit": sum(v >= WEEK_TARGET for v in recent), "worst": round(min(recent), 2) if recent else None,
                     "weeks": [{"d": d, "v": round(v, 2)} for d, v in rows], "series": series}
    return out


def score_fields(rows, pos):
    """On each A14 position, what its fills alone can't say: how many ids it joined, and its adjustments outside the windows."""
    mine = [r for r in rows if r["strategy"] == "A14"]
    for r in mine:
        r["ladder_n"] = sum(1 for x in mine if x["acct"] == r["acct"] and x["ticker"] == r["ticker"] and x["entry"] <= r["entry"] and (x["close"] is None or x["close"] > r["entry"]))
        ev = []
        for k in r["keys"]:
            p = pos.get(k)
            if p:
                ev += p["events"][1:-1] if p["flat"] else p["events"][1:]
        r["off_window"] = sum(1 for e in ev if (e - dt.timedelta(hours=14)).weekday() not in WINDOWS)


def checks(r, entered):
    """The rule page as Journal checks, each [id, passed, live]. Older ids are scored only in hindsight."""
    live, out = entered >= FROM, []
    if r.get("plan_pct") is not None:
        out.append(["a14size", r["plan_pct"] <= STOP_NAV, live])
    if r.get("lots0") is not None:
        out.append(["a14add", r["lots_peak"] <= r["lots0"], live])
    if r.get("dte0") is not None:
        out.append(["a14dte", DTE_LO <= r["dte0"] <= DTE_HI, live])
    out.append(["a14day", dt.date.fromisoformat(entered).weekday() == ENTRY_DAY, live])
    if r.get("ladder_n") is not None:
        out.append(["a14cap", r["ladder_n"] <= CAP, live])
    if r.get("off_window") is not None:
        out.append(["a14window", r["off_window"] == 0, live])
    return out


def state():
    """Everything the Actions and P&L views show: the rule, the accounts it sizes on, the next id per ticker, the 13-week target."""
    from . import accounts, backtest, db, journal
    from .positions import CARDS
    J = journal.closed()
    traded = {r["acct"] for r in J["book"]}
    navs = {a: v for a, v in J["nav_now"].items() if a in {r["acct"] for r in J["book"] if r["strategy"] == "A14"}}
    nav = min(navs.values()) if navs else None
    stop = CARDS["A14"]["stop"]
    raw = db.get_meta("a14_chain")
    blob = json.loads(raw) if raw else {}
    D = backtest.data()
    return {"rule": rule(), "navs": navs, "nav": nav, "worst": round(nav * STOP_NAV / stop) if nav else None, "stop_usd": round(nav * STOP_NAV / 100) if nav else None,
            "chain_ts": blob.get("ts"), "next": {u: next_id(u, blob, D, nav) for u in ("SPX", "RUT")}, "target": target(accounts.weekly(60), traded)}
