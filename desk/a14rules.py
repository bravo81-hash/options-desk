"""The A14 rule page, approved 2026-11-02. One place for what the trade plan, the next-id panel, the scanner and the Journal read.

One structure, sized by what the stop can lose: at Full size an id loses STOP_NAV % of NAV at the card's stop, which makes its worst
case 7.5% of NAV. Both accounts trade the same lots, worked out on the smaller NAV, so neither goes over; the readiness bar scales it
and nothing else does. One new id a week per ticker at the Friday expiry nearest ENTRY_DTE, unless CAP ids are open: on the Friday, or
earlier in the week when the readiness bar reads one of MID_SIZES for that ticker and every account is inside its limits (from
MID_FROM; before that, Fridays only). Risk is never added to an id: new risk is a new id. Adjustments wait for the id's delta to
leave ±DELTA_BAND a lot (from DELTA_FROM; before that, for a window day); targets and stops are watched every day. An id is out
by the card's time stop. The tent shifts TILT_SD with the index more than TILT_LINE % from its 20-day average.

The target is 1% of NAV a week per account, judged on a TARGET_WEEKS average because a single week is mostly noise.
"""
import datetime as dt
import json

import numpy as np

from .accounts import ET, US_HOLIDAYS

FROM = "2026-11-02"  # nothing before this is scored on these rules
TARGET = 7.0  # % of margin: the Trade plan's close, whatever the entry DTE
STOP_NAV = 1.5  # % of NAV lost at the card's stop, at Full size
ENTRY_DTE, DTE_LO, DTE_HI = 49, 42, 56
TIME_BEFORE = 2  # the card's time stop for ids entered before FROM
CAP = 4  # open ids per ticker and account
WINDOWS = (0, 2, 4)  # adjustments before DELTA_FROM: Monday, Wednesday, Friday, US dates
DELTA_BAND, DELTA_FROM = 3.0, "2026-11-12"  # adjust only with the id's delta beyond ± this a lot; replaces the window days (user, 11 Nov 2026)
ENTRY_DAY = 4  # Friday
MID_SIZES, MID_FROM = ("Full size", "Three-quarter size"), "2026-11-12"  # a midweek entry needs one of these on the readiness bar (user, 11 Nov 2026)
TILT_SD, TILT_LINE = 0.2, 1.0
WEEK_TARGET, TARGET_WEEKS = 1.0, 13
STEP_SIZE = {"Full size": 1.0, "Three-quarter size": 0.75, "Half size": 0.5, "Quarter size": 0.25, "Stand aside": 0.0}


def id_cap():
    """Count per ticker/account, separate from the worst-case NAV percentage."""
    from . import limitcfg
    v = limitcfg.value("ids:A14")
    return CAP if v is None else int(v)


def rule():
    """The rule page as data, for the pages that print it."""
    from .positions import CARDS
    stop = CARDS["A14"]["stop"]
    return {"from": FROM, "target": TARGET, "stop_nav": STOP_NAV, "stop": stop, "worst_nav": round(100 * STOP_NAV / stop, 2), "entry_dte": ENTRY_DTE, "dte_lo": DTE_LO, "dte_hi": DTE_HI, "time_dte": CARDS["A14"]["time"],
            "cap": id_cap(), "delta_band": DELTA_BAND, "delta_from": DELTA_FROM, "mid_sizes": list(MID_SIZES), "mid_from": MID_FROM, "entry_day": ENTRY_DAY, "tilt_sd": TILT_SD, "tilt_line": TILT_LINE, "week_target": WEEK_TARGET, "target_weeks": TARGET_WEEKS}


def tilt(vs20):
    """Shift of the tent in sd units: up with the index over 1% above its 20-day average, down over 1% below, else centred."""
    return 0.0 if vs20 is None or abs(vs20) <= TILT_LINE else TILT_SD if vs20 > 0 else -TILT_SD


def _shut(d):
    return d.isoformat() in US_HOLIDAYS


def weekly(d):
    """A week's own expiry: the Friday, or the Thursday when that Friday is a market holiday (Christmas week, Good Friday)."""
    return d.weekday() == 4 or (d.weekday() == 3 and _shut(d + dt.timedelta(days=1)))


def entry_day(d):
    """The rule's entry day in d's week: the Friday, or the Thursday when the market is shut on the Friday."""
    return weekly(d) and not _shut(d)


def entry_next(d):
    """The next entry day on or after d."""
    while not entry_day(d):
        d += dt.timedelta(days=1)
    return d


def session(d):
    """A US trading day."""
    return d.weekday() < 5 and not _shut(d)


def week_of(d):
    """The Monday of d's week: the rule opens one id per ticker in each."""
    return d - dt.timedelta(days=d.weekday())


def entry_ok(d, size, opened_this_week, over_limits=False):
    """(allowed, kind, why) for a new id on a ticker on US date d: the week's Friday entry, or a midweek one that replaces it."""
    if over_limits:
        return False, None, "an account is over your limits"
    if not session(d):
        return False, None, "the market is shut"
    if opened_this_week:
        return False, None, "this week's id is already on"
    if STEP_SIZE.get(size, 0.0) <= 0:
        return False, None, "the readiness bar says stand aside"
    if entry_day(d):
        return True, "friday", "the week's entry day"
    if d.isoformat() >= MID_FROM and size in MID_SIZES:
        return True, "midweek", f"{size.lower()} on the readiness bar: it replaces this week's Friday entry"
    return False, None, f"midweek needs full or three-quarter size; the bar reads {size.lower()}"


def expiry_for(smiles):
    """The weekly expiry nearest ENTRY_DTE inside the entry window; the sooner one on a tie, so an id never starts long."""
    fri = {e: s for e, s in smiles.items() if DTE_LO <= s["dte"] <= DTE_HI and weekly(dt.datetime.strptime(e, "%Y%m%d").date())}
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
    """{label: {now, weeks, series, prov}}: each traded account's weekly % of NAV and its rolling TARGET_WEEKS average on finished
    weeks; `prov` is the week to date and the average it would make if the week ended now, shown apart and marked provisional."""
    names = {a["id"]: a["label"] for a in weekly.get("accounts", [])}
    to_date = lambda w: next((n for n in w.get("notes") or [] if "week to date" in n), None)  # noqa: E731
    weeks = sorted(weekly.get("weeks", []), key=lambda w: w["week"])
    done = [w for w in weeks if not to_date(w)]
    cur = next((w for w in reversed(weeks) if to_date(w)), None)
    out = {}
    for ac, name in names.items():
        if name not in labels:
            continue
        rows = [(w["week"], w["acct"][ac]["pct"]) for w in done if (w["acct"].get(ac) or {}).get("pct") is not None]
        vals = [v for _, v in rows]
        series = [{"d": rows[i][0], "v": round(sum(vals[i + 1 - TARGET_WEEKS:i + 1]) / TARGET_WEEKS, 3)} for i in range(TARGET_WEEKS - 1, len(rows))]
        recent = vals[-TARGET_WEEKS:]
        p = (cur["acct"].get(ac) or {}).get("pct") if cur else None
        prov = None
        if p is not None:
            k = TARGET_WEEKS - 1
            prov = {"d": cur["week"], "v": round(p, 2), "note": to_date(cur), "now": round((sum(vals[-k:]) + p) / TARGET_WEEKS, 3) if len(vals) >= k else None}
        out[name] = {"now": series[-1]["v"] if series else None, "n": len(recent), "hit": sum(v >= WEEK_TARGET for v in recent), "worst": round(min(recent), 2) if recent else None,
                     "weeks": [{"d": d, "v": round(v, 2)} for d, v in rows], "series": series, "prov": prov}
    return out


def id_worst(t):
    """An open trade's lowest total P&L, US$: every open leg at intrinsic value at any index level, plus what it has already
    realised (ONE's P&L). None when a leg has no open price; -inf when more calls are short than long (no ceiling)."""
    from .positions import uncapped, worst
    if any(lg.get("open_price") is None or lg.get("strike") is None for lg in t["legs"]):
        return None
    pos = {}
    for lg in t["legs"]:
        k = (lg["expiry_iso"][:10], lg["strike"], lg["right"])
        pos[k] = pos.get(k, 0.0) + lg["qty"]
    if uncapped(pos):
        return float("-inf")
    return worst(pos, (t.get("one_pnl") or 0.0) - sum(lg["qty"] * 100 * lg["open_price"] for lg in t["legs"]))


def _entered_us(t):
    """The US session date a trade was opened (ONE's times are this computer's local time)."""
    try:
        return dt.datetime.fromisoformat(t["opened_iso"]).astimezone(ET).date().isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def book(rows, navs):
    """The open A14 book against the rule page, per account: ids per ticker against CAP, and each id's worst case (id_worst) against
    the rule's 7.5% of that account's NAV. rows: open trades with "acct" (label) and "strategy"; navs: {label: NAV in US$}.
    Information only: nothing here closes, blocks or sizes anything."""
    from .positions import CARDS
    lim = 100 * STOP_NAV / CARDS["A14"]["stop"]
    cap = id_cap()
    out = {}
    for t in rows:
        if t.get("strategy") != "A14":
            continue
        a = out.setdefault(t["acct"], {"ids": {}, "cap": cap, "lim": lim, "over": [], "worst_usd": 0.0, "unpriced": 0, "largest": None})
        a["ids"][t["underlying"]] = a["ids"].get(t["underlying"], 0) + 1
        w, nav = id_worst(t), navs.get(t["acct"])
        if w is None:
            a["unpriced"] += 1
            continue
        loss = -min(w, 0.0)
        a["worst_usd"] += loss
        if nav:
            pct = 100 * loss / nav
            a["largest"] = max(a["largest"] or 0.0, pct)
            if pct > lim:
                ent = _entered_us(t)
                a["over"].append({"id": t["id"], "name": t["name"], "pct": None if pct == float("inf") else round(pct, 1), "before": bool(ent) and ent < FROM})
    for name, a in out.items():
        nav = navs.get(name)
        a["worst_pct"] = None if not nav or a["worst_usd"] == float("inf") else round(100 * a["worst_usd"] / nav, 1)
        a["largest"] = None if a["largest"] is None or a["largest"] == float("inf") else round(a["largest"], 1)
        a["worst_usd"] = None if a["worst_usd"] == float("inf") else round(a["worst_usd"])
        a["alerts"] = [f"{n} {u} ids open: the rule's cap is {cap}" for u, n in sorted(a["ids"].items()) if n > cap] + [_over_txt(o, lim) for o in a["over"]]
    return out


def worst_by(rows, navs):
    """{account: {strategy or "total": {n, usd, pct, open_ended, unpriced}}}: every open trade at its worst case (id_worst), added up
    per strategy and across all of them, for the caps in desk/limitcfg.py. A trade with no ceiling is counted in open_ended, not in usd."""
    out = {}
    for t in rows:
        w = id_worst(t)
        for key in (t.get("strategy") or "Other", "total"):
            a = out.setdefault(t["acct"], {}).setdefault(key, {"n": 0, "usd": 0.0, "open_ended": 0, "unpriced": 0})
            a["n"] += 1
            if w is None:
                a["unpriced"] += 1
            elif w == float("-inf"):
                a["open_ended"] += 1
            else:
                a["usd"] += -min(w, 0.0)
    for name, d in out.items():
        for a in d.values():
            a["pct"] = round(100 * a["usd"] / navs[name], 1) if navs.get(name) else None
            a["usd"] = round(a["usd"])
    return out


def _over_txt(o, lim):
    size = "has no ceiling" if o["pct"] is None else f"is {o['pct']:.1f}% of NAV"
    return f"{o['name']}: worst case {size}, over the rule's {lim:g}%" + (" (opened before the 2 Nov rules)" if o["before"] else "")


def score_fields(rows, pos):
    """On each A14 position, what its fills alone can't say: how many ids it joined, and its adjustments outside the windows."""
    from . import process
    mine = [r for r in rows if r["strategy"] == "A14"]
    for r in mine:
        r["size_then"] = process.size_on(r["entry_us"], f"A14 {r['ticker']}") if r.get("entry_us") else None
        r["ladder_n"] = sum(1 for x in mine if x["acct"] == r["acct"] and x["ticker"] == r["ticker"] and x["entry"] <= r["entry"] and (x["close"] is None or x["close"] > r["entry"]))
        ev = []
        for k in r["keys"]:
            p = pos.get(k)
            if p:
                ev += p["events"][1:-1] if p["flat"] else p["events"][1:]
        us = lambda e: e - dt.timedelta(hours=14)  # noqa: E731
        r["off_window"] = sum(1 for e in ev if us(e).date().isoformat() < DELTA_FROM and us(e).weekday() not in WINDOWS)  # the delta rule can't be read from fills
        wk = week_of(dt.date.fromisoformat(r["entry_us"])) if r.get("entry_us") else None
        r["week_n"] = None if wk is None else sum(1 for x in mine if x["acct"] == r["acct"] and x["ticker"] == r["ticker"] and x.get("entry_us") and x["entry"] <= r["entry"]
                                                  and week_of(dt.date.fromisoformat(x["entry_us"])) == wk)


def checks(r, entered):
    """The rule page as Journal checks, each [id, passed, live]. Older ids are scored only in hindsight."""
    live, out = entered >= FROM, []
    if r.get("plan_pct") is not None:
        out.append(["a14size", r["plan_pct"] <= STOP_NAV, live])
    if r.get("lots0") is not None:
        out.append(["a14add", r["lots_peak"] <= r["lots0"], live])
    if r.get("dte0") is not None:
        out.append(["a14dte", DTE_LO <= r["dte0"] <= DTE_HI, live])
    d = dt.date.fromisoformat(entered)
    if entry_day(d) or entered < MID_FROM:
        out.append(["a14day", entry_day(d), live])
    elif r.get("size_then") is not None:  # midweek: the bar's size for the ticker that session, kept by desk/process.py
        out.append(["a14day", r["size_then"] in MID_SIZES, live])
    if r.get("week_n") is not None:
        out.append(["a14week", r["week_n"] <= 1, entered >= MID_FROM])
    if r.get("ladder_n") is not None:
        out.append(["a14cap", r["ladder_n"] <= CAP, live])
    if r.get("off_window") is not None:
        out.append(["a14window", r["off_window"] == 0, live and entered < DELTA_FROM])  # after it the delta band gates, which fills can't show
    return out


def week_opened(rows, today):
    """Include closed ids too: exiting early does not permit a second entry that week."""
    start = week_of(today).isoformat()
    return {u: sorted({r["entry_us"] for r in rows if r.get("strategy") == "A14" and r.get("ticker") == u
                       and start <= (r.get("entry_us") or "") <= today.isoformat()}) for u in ("SPX", "RUT")}


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
    today = dt.datetime.now(ET).date()
    return {"rule": rule(), "entry_next": entry_next(today).isoformat(), "today": today.isoformat(), "session": session(today), "entry_day": entry_day(today), "week_start": week_of(today).isoformat(), "week_opened": week_opened(J["book"], today), "navs": navs, "nav": nav, "worst": round(nav * STOP_NAV / stop) if nav else None, "stop_usd": round(nav * STOP_NAV / 100) if nav else None,
            "chain_ts": blob.get("ts"), "next": {u: next_id(u, blob, D, nav) for u in ("SPX", "RUT")}, "target": target(accounts.weekly(60), traded)}
