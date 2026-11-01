"""Whole positions: what was at risk and when, replayed from the fills in ONE's Detail Report.

A position is one ONE trade id with every fill under it. Fills under 15 minutes apart are one event; the first event is
the entry and every later one an adjustment, except a last event that leaves the position flat.

1R is the worst case of the entry fills and stays frozen there. R is the trade's whole P&L, adjustments and commissions
included, over that same number, so adding risk later can't shrink a loss the way ONE's % does: ONE's margin follows the
largest size the trade reached. Peak risk and risk-days show the size it actually carried.
"""
import bisect
import datetime as dt
import os
import re
import statistics

from . import a14rules, db, load_config, one

GAP = 900  # seconds: fills closer than this are one ticket
OCC = re.compile(r"(\d{6})([CP])(\d{8})$")
# The Trade plan cards in web/risk.js (a test keeps these equal): stop % of ONE margin, time stop in DTE, adjustments allowed.
# Other, IF, M200, Earnings and Batman have no card; Flyagonal has no stop.
CARDS = {"A14": {"stop": 20, "time": 7, "adjust": "gated"}, "Allantis": {"stop": 10, "time": 2, "adjust": "gated"},
         "HV7": {"stop": 10, "time": 2, "adjust": "never"}, "TimeEdge": {"stop": 15, "time": 1, "adjust": "one"},
         "Triple Cal": {"stop": 15, "time": 1, "adjust": "one"}, "TimeZone": {"stop": 5, "time": 7, "adjust": "one"},
         "Flyagonal": {"stop": None, "time": None, "adjust": "one"}}
CARD_FROM, GATE_FROM, CAP_FROM = "2026-10-24", "2026-10-25", "2026-11-01"  # when the cards, the entry gates and the cap began
_cache = {}


def worst(pos, cash):
    """Lowest total if every open leg is worth only its intrinsic value, at any underlying price. One formula for one
    expiry or many: a calendar's worst case is its debit, a fly's is width less credit. pos: {(expiry, strike, right): signed qty}."""
    live = [(k, q) for k, q in pos.items() if abs(q) > 1e-9]
    if not live:
        return cash
    ks = sorted({k[1] for k, _ in live})
    return min(sum(q * (max(0.0, s - k[1]) if k[2] == "C" else max(0.0, k[1] - s)) * 100 for k, q in live) + cash for s in [0.0] + ks + [ks[-1] * 2])


def uncapped(pos):
    """True when more calls are short than long: the loss has no ceiling, and worst() only stops at twice the top strike."""
    return sum(q for k, q in pos.items() if k[2] == "C") < -1e-9


def replay(fills, end=None):
    """What a trade's fills add up to. `end` is when it closed, or now for an open trade (for risk-days)."""
    fills = [f for f in sorted(fills, key=lambda f: f["t"]) if OCC.search(f["symbol"].replace(" ", ""))]
    if not fills:
        return None
    events, last = [], None
    for f in fills:
        if last is None or (f["t"] - last).total_seconds() >= GAP:
            events.append([])
        events[-1].append(f)
        last = f["t"]
    pos, cash, steps, capped = {}, 0.0, [], True
    for ev in events:
        for f in ev:
            m = OCC.search(f["symbol"].replace(" ", ""))
            k, q = (f["expiry"], int(m.group(3)) / 1000, m.group(2)), f["qty"] if f["side"] == "Buy" else -f["qty"]
            pos[k] = pos.get(k, 0.0) + q
            cash -= q * f["px"] * 100
        if not steps:
            capped = not uncapped(pos)
        steps.append({"t": ev[0]["t"], "risk": -worst(pos, cash), "lots": sum(abs(q) for q in pos.values()), "flat": not any(abs(q) > 1e-9 for q in pos.values())})
    ts = [s["t"] for s in steps]
    spans = [(b - a).total_seconds() / 86400 for a, b in zip(ts, ts[1:] + [end or ts[-1]])]
    return {"entry": ts[0], "risk0": steps[0]["risk"], "peak": max(s["risk"] for s in steps), "lots0": steps[0]["lots"], "lots_peak": max(s["lots"] for s in steps),
            "adj": max(len(steps) - 1 - (1 if steps[-1]["flat"] else 0), 0), "flat": steps[-1]["flat"], "capped": capped,
            "risk_days": sum(max(s["risk"], 0.0) * d for s, d in zip(steps, spans)), "events": ts}


def load():
    """({account#trade_id: replay}, when the Detail Report was exported). Empty if there isn't one."""
    path = one.detail_path()
    if not path:
        return {}, None
    key = (path, os.path.getmtime(path))
    if key in _cache:
        return _cache[key]
    now, out = dt.datetime.now(), {}
    for t in one.read(path)[0]:
        r = replay(t["fills"] or [], one.when(t["closed"]) or now)
        if r:
            out[f"{t['account']}#{t['trade_id']}"] = r
    _cache.clear()
    _cache[key] = (out, dt.datetime.fromtimestamp(key[1]).isoformat(timespec="minutes"))
    return _cache[key]


# ------------------------------------------------------------------ capital at entry
def init():
    db.write("CREATE TABLE IF NOT EXISTS fx_daily (pair TEXT, date TEXT, close REAL, PRIMARY KEY (pair, date))")


def refresh_fx():
    """AUD/USD closes: NAV is in AUD, trades are in USD. Skipped once yesterday's close is stored."""
    from . import market
    init()
    have = db.query("SELECT MAX(date) d FROM fx_daily WHERE pair='AUDUSD'")[0]["d"]
    if have and have >= (dt.date.today() - dt.timedelta(days=1)).isoformat():
        return 0
    import yfinance as yf
    with market.YF_LOCK:
        h = yf.download("AUDUSD=X", start=have or "2025-06-01", progress=False, auto_adjust=False)
    if h is None or not len(h):
        return 0
    s = h["Close"].squeeze().dropna()
    rows = [("AUDUSD", i.date().isoformat(), float(v)) for i, v in s.items()]
    if rows:
        db.write("INSERT OR REPLACE INTO fx_daily VALUES (?,?,?)", rows, many=True)
    return len(rows)


def nav_lookup():
    """f(ib_account, iso day) -> NAV in USD at the last close on or before that day, or None if either side is missing."""
    init()
    fx = db.query("SELECT date, close FROM fx_daily WHERE pair='AUDUSD' ORDER BY date")
    days, rates = [r["date"] for r in fx], [r["close"] for r in fx]
    navs = {}
    for r in db.query("SELECT date, account, nav FROM account_daily WHERE nav IS NOT NULL ORDER BY date"):
        n = navs.setdefault(r["account"], ([], []))
        n[0].append(r["date"])
        n[1].append(r["nav"])

    def f(acct, day):
        a = navs.get(acct)
        if not a or not rates or not day:
            return None
        i, j = bisect.bisect_right(a[0], day) - 1, max(bisect.bisect_right(days, day) - 1, 0)
        return a[1][i] * rates[j] if i >= 0 else None
    return f


# ------------------------------------------------------------------ decisions, rolls, behaviour, rules
def decision_id(ticker, strategy, expiry, entry_us):
    """Twins (the same trade in MGN and SMSF) share this: one decision, however many accounts it was placed in."""
    return f"{ticker}|{strategy}|{expiry}|{entry_us}"


def resolve_twins(rows):
    """Twins carry one strategy: the one every side's name agrees on, else the only one named. '14.SMSF' in a name is
    an A14 that only says so on its MGN side. Trades in the same account are never each other's twin."""
    groups = {}
    for r in rows:
        groups.setdefault((r["ticker"], r["expiry_iso"], r["entry_us"]), []).append(r)
    for v in groups.values():
        named = [r["labels"] for r in v if r["labels"]]
        if len({r["acct"] for r in v}) < 2 or not named:
            continue
        both = [x for x in named[0] if all(x in n for n in named)]
        if both or len({n[0] for n in named}) == 1:
            for r in v:
                r["strategy"] = (both or named[0])[0]
    return rows


def link_rolls(rows, minutes=60):
    """A loser closed and reopened under a new trade id is one idea: same account group, ticker and strategy, a new entry
    within `minutes` of the close, on the same or a later expiry. Sets `roll_of` on the new trade, so the loss isn't hidden by the id."""
    closed = [r for r in rows if r["close"] and (r["pnl"] or 0) < 0]
    for r in rows:
        c = [p for p in closed if p is not r and p["group"] == r["group"] and p["ticker"] == r["ticker"] and p["strategy"] == r["strategy"]
             and 0 <= (r["entry"] - p["close"]).total_seconds() <= minutes * 60 and (r["expiry_iso"] or "") >= (p["expiry_iso"] or "")]
        r["roll_of"] = max(c, key=lambda p: p["close"])["key"] if c else None
    return rows


def chains(rows):
    """Rolled trades joined into one position: the first trade's 1R, the whole chain's P&L, the last trade's close."""
    by = {r["key"]: r for r in rows}
    groups = {}
    for r in rows:
        root = r
        while root.get("roll_of") in by:
            root = by[root["roll_of"]]
        groups.setdefault(root["key"], []).append(r)
    out = []
    for key, v in groups.items():
        head, tail = by[key], max(v, key=lambda r: r["entry"])
        done = all(r["close"] for r in v)
        pnl = sum(r["pnl"] or 0 for r in v)
        out.append({**head, "keys": [r["key"] for r in v], "pnl": pnl if done else None, "close": tail["close"] if done else None, "open": not done,
                    "exit_us": tail["exit_us"] if done else None, "dte_exit": tail["dte_exit"] if done else None, "expiry_iso": tail["expiry_iso"],
                    "ret": tail["ret"], "peak": max(r["peak"] for r in v), "adj": sum(r["adj"] for r in v) + len(v) - 1, "risk_days": sum(r["risk_days"] for r in v),
                    "r": pnl / head["risk0"] if done else None, "lots_peak": max(r["lots_peak"] for r in v), "rolls": len(v) - 1})
    return out


def fold(rows):
    """One row per decision, oldest entry first: twins averaged for R, added up for dollars."""
    groups = {}
    for r in rows:
        groups.setdefault(r["decision"], []).append(r)
    out = []
    for d, v in groups.items():
        done = all(x["close"] for x in v)
        out.append({"decision": d, "keys": [k for x in v for k in x["keys"]], "strategy": v[0]["strategy"], "ticker": v[0]["ticker"], "entry": min(x["entry"] for x in v),
                    "close": max(x["close"] for x in v) if done else None, "pnl": sum(x["pnl"] or 0 for x in v) if done else None, "risk0": sum(x["risk0"] for x in v),
                    "r": statistics.mean(x["r"] for x in v) if done else None, "roll": any(x.get("rolls") for x in v), "n": len(v)})
    return sorted(out, key=lambda x: x["entry"])


def behaviour(decisions, cfg):
    """Each decision's state on entry. streak: straight winning closes before it. size_x: its 1R against the median of the same
    strategy's last eight, once three exist. revenge: entered within the window of a loss of at least `revenge_loss_r`, and either
    bigger than usual or in the same ticker; a roll is management, not revenge. after_loss: place in the five entries after a loss."""
    done = sorted([d for d in decisions if d["close"]], key=lambda d: d["close"])
    trail, out = {}, {}
    for x in decisions:
        before = [d for d in done if d["close"] < x["entry"]]
        streak = 0
        for d in reversed(before):
            if d["pnl"] <= 0:
                break
            streak += 1
        hist = trail.setdefault(x["strategy"], [])
        size = x["risk0"] / statistics.median(hist[-8:]) if len(hist) >= 3 else None
        hist.append(x["risk0"])
        window = [d for d in before if (x["entry"] - d["close"]).total_seconds() <= cfg["revenge_minutes"] * 60 and d["r"] is not None and d["r"] <= -cfg["revenge_loss_r"]]
        revenge = bool(window) and not x["roll"] and ((size or 0) >= cfg["revenge_size"] or any(d["ticker"] == x["ticker"] for d in window))
        loss = next((d for d in reversed(before) if d["pnl"] <= 0), None)
        run = sum(1 for d in decisions if d["entry"] > loss["close"] and d["entry"] <= x["entry"]) if loss else None
        out[x["decision"]] = {"streak": streak, "hot": streak >= cfg["streak_n"], "size_x": size, "revenge": revenge, "after_loss": run if run and run <= 5 else None}
    return out


def streak_now(decisions):
    """Straight winning closes up to today, for the warning before the next entry."""
    n = 0
    for d in sorted([d for d in decisions if d["close"]], key=lambda d: d["close"], reverse=True):
        if d["pnl"] <= 0:
            break
        n += 1
    return n


def extreme_flags(decisions, plans, multiple):
    """({decision: why it needs a post-mortem}, average loss in R): a loss over `multiple` × the average, or past what was planned at entry."""
    losses = [abs(d["r"]) for d in decisions if d["r"] is not None and d["r"] < 0]
    avg = statistics.mean(losses) if losses else None
    out = {}
    for d in decisions:
        if d["r"] is None or d["r"] >= 0:
            continue
        why = []
        if avg and abs(d["r"]) > multiple * avg:
            why.append("size")
        plan = plans.get(d["decision"])
        if plan and d["pnl"] < -plan:
            why.append("stop")
        if why:
            out[d["decision"]] = why
    return out, avg


def link_tickets(decisions, tickets, days=3):
    """{decision: {ticket, before_fill}}: each pre-commit goes to the nearest entry in its ticker and strategy. The desk only sees a
    trade after it fills, so the stamp says whether the pre-commit really came first."""
    out = {}
    for t in sorted(tickets, key=lambda t: t["created"]):
        made = dt.datetime.fromisoformat(t["created"])
        gap = lambda d: abs((d["entry"] - made).total_seconds())  # noqa: E731
        near = [d for d in decisions if d["decision"] not in out and d["ticker"] == t["ticker"] and d["strategy"] == t["strategy"] and gap(d) <= days * 86400]
        if near:
            d = min(near, key=gap)
            out[d["decision"]] = {"ticket": t["id"], "before_fill": made < d["entry"]}
    return out


def plan_scores(log, pos, exits):
    """What Trade plan said at the time against what the fills then did. exits: {key: US exit session}. Each Exit or Close call counts
    once per trade, from the first session it was shown; each adjustment is held against the last plan logged before it, if that is
    within three days. A plan logged after the fill says nothing about the decision: it already includes the adjustment."""
    by, calls, against, allowed = {}, [], 0, 0
    for r in sorted(log, key=lambda r: r["date"]):
        by.setdefault(r["trade_key"], []).append(r)
    for key, rows in by.items():
        first = next((r for r in rows if r["act"] in ("exit", "close")), None)
        if first:
            calls.append({"key": key, "act": first["act"], "label": first["label"], "from": first["date"], "done": exits.get(key)})
        p = pos.get(key)
        for e in (p["events"][1:-1] if p and p["flat"] else p["events"][1:] if p else []):
            day = (e - dt.timedelta(hours=14)).date()
            said = [r for r in rows if r.get("updated") and dt.datetime.fromisoformat(r["updated"]) <= e]
            if said and (day - dt.date.fromisoformat(said[-1]["date"])).days <= 3:
                if said[-1]["adj"] == "no":
                    against += 1
                else:
                    allowed += 1
    return {"calls": calls, "adj_against": against, "adj_allowed": allowed, "sessions": len({r["date"] for r in log})}


def rule_checks(r, cap_pct):
    """The rules a position can be scored on from its fills alone, each [id, passed, live]. live: the rule existed at that moment,
    so a trade is never marked down by a rule written after it. A card's stop is read as the card reads it: ONE's %."""
    card, out = CARDS.get(r["strategy"]) or {}, []
    done, entered = r["exit_us"] or "", r["entry_us"]
    if card.get("stop") and r["close"]:
        out.append(["stop", (r["ret"] or 0) >= -card["stop"], done >= CARD_FROM])
    if card.get("time") and r["close"] and r["dte_exit"] is not None:
        limit = a14rules.TIME_BEFORE if r["strategy"] == "A14" and entered < a14rules.FROM else card["time"]
        out.append(["time", r["dte_exit"] >= limit, done >= CARD_FROM])
    if card.get("adjust") in ("one", "never"):
        out.append(["adjust", r["adj"] <= (1 if card["adjust"] == "one" else 0), entered >= CARD_FROM])
    if r["strategy"] in ("TimeEdge", "TimeZone", "Triple Cal") and r["ivts"] is not None and r["vs20"] is not None:
        out.append(["gate", r["ivts"] < 0.90 and r["vs20"] > 0, entered >= GATE_FROM])
    if r["strategy"] == "A14" and r["ivts"] is not None:
        out.append(["aside", r["ivts"] < 1, entered >= GATE_FROM])
    if r["strategy"] == "A14":
        out += a14rules.checks(r, entered)
    if r["plan_pct"] is not None:
        out.append(["cap", r["plan_pct"] <= cap_pct, entered >= CAP_FROM])
    return out
