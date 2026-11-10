"""Process over P&L (the user's 10 Nov 2026 decision): a daily read of the week ahead scored later, what the book limits said each
day, an automatic log of whether each new position followed the rules, and a scoreboard of drawdown and rules followed.
Information only: nothing here sizes, blocks or places anything."""
import datetime as dt
import json

from . import db, load_config
from .recorder import session_date

FROM = "2026-11-11"  # limits are scored against entries from here
CALLS = ("quiet", "normal", "rough")
AHEAD, QUIET, ROUGH = 5, -0.5, -2.0  # SPX's worst close over the next 5 sessions against the call day's close, %
# since 1990 the week after any day was quiet 48% of the time, normal 32%, rough 20%
WHY = {"aside": "entered with VIX/VIX3M in backwardation", "a14size": "loss at the stop above the rule's share of NAV", "a14add": "size added after entry",
       "a14dte": "entered outside the DTE window", "a14day": "not entered on a Friday", "a14cap": "more ids on the ticker than the cap",
       "a14window": "adjusted on a non-window day", "cap": "risk above the Journal's cap", "stop": "held past the hard stop", "time": "held past the time stop",
       "adjust": "more adjustments than the card allows", "gate": "calendar entered outside its gates", "limits": "the account was over your limits at entry"}


def init():
    db.write("CREATE TABLE IF NOT EXISTS market_calls (date TEXT PRIMARY KEY, mine TEXT, app TEXT, risk REAL, made TEXT)")
    db.write("CREATE TABLE IF NOT EXISTS process_day (date TEXT PRIMARY KEY, over TEXT, updated TEXT)")


def _stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ the daily read
def outcome(worst):
    return "rough" if worst <= ROUGH else "quiet" if worst > QUIET else "normal"


def app_call(risk):
    """The desk's own read, from the readiness bar's odds of a 5% drop: under 17% quiet, 23% or more rough."""
    return None if risk is None else "rough" if risk >= 23 else "quiet" if risk < 17 else "normal"


def save_call(mine=None, risk=None, now=None):
    """Today's read (US session date). Yours can change until the session is over; the desk's is written beside it from the same moment."""
    init()
    if mine is not None and mine not in CALLS:
        return {"error": f"A call is one of: {', '.join(CALLS)}."}
    d = session_date(now).isoformat()
    row = (db.query("SELECT * FROM market_calls WHERE date=?", (d,)) or [{}])[0]
    mine, app = mine or row.get("mine"), app_call(risk) or row.get("app")
    if not mine and not app:
        return calls(now)
    db.write("INSERT OR REPLACE INTO market_calls VALUES (?,?,?,?,?)", (d, mine, app, risk if risk is not None else row.get("risk"), _stamp()))
    return calls(now)


def _closes():
    return [(r["date"], r["c"]) for r in db.query("SELECT date, c FROM bars_daily WHERE symbol='^GSPC' AND c>0 AND date>='1990-01-01' ORDER BY date")]


def calls(now=None):
    """Every call with what the week then did, and the score: yours, the desk's, and always saying 'quiet' (the commonest week)."""
    init()
    px = _closes()
    at = {d: i for i, (d, _) in enumerate(px)}
    rows, score = [], {"n": 0, "mine": 0, "mine_n": 0, "app": 0, "app_n": 0, "quiet": 0}
    for r in db.query("SELECT * FROM market_calls ORDER BY date"):
        i, out, worst, seen = at.get(r["date"]), None, None, 0
        if i is not None:
            nxt = [c for _, c in px[i + 1:i + 1 + AHEAD]]
            seen = len(nxt)
            worst = round(100 * (min(nxt) / px[i][1] - 1), 2) if nxt else None
            if seen == AHEAD or (worst is not None and worst <= ROUGH):  # a rough week is known as soon as it happens
                out = outcome(worst)
        if out:
            score["n"] += 1
            score["quiet"] += out == "quiet"
            for k in ("mine", "app"):
                if r[k]:
                    score[k + "_n"] += 1
                    score[k] += r[k] == out
        rows.append({"date": r["date"], "mine": r["mine"], "app": r["app"], "worst": worst, "seen": seen, "outcome": out})
    today = session_date(now).isoformat()
    cur = next((r for r in rows if r["date"] == today), None) or {}
    w = [100 * (min(c for _, c in px[i + 1:i + 1 + AHEAD]) / px[i][1] - 1) for i in range(len(px) - AHEAD)]
    base = {k: round(100 * sum(1 for x in w if outcome(x) == k) / len(w)) for k in CALLS} if w else None
    return {"today": today, "mine": cur.get("mine"), "app": cur.get("app"), "rows": rows[::-1], "score": score, "base": base,
            "defs": {"ahead": AHEAD, "quiet": QUIET, "rough": ROUGH}}


# ------------------------------------------------------------------ what the limits said, day by day
def snap_day(limits, now=None):
    """Which accounts were over the user's cap or stress limit this session (desk/risk.py limits), kept so a later entry can be read against it."""
    try:
        init()
        db.write("INSERT OR REPLACE INTO process_day VALUES (?,?,?)", (session_date(now).isoformat(), json.dumps(sorted(a["label"] for a in limits or [] if a.get("over"))), _stamp()))
    except Exception:
        pass  # a read-only copy or a locked file: the Risk grid still loads


def over_on(date):
    r = db.query("SELECT over FROM process_day WHERE date=?", (date,))
    return set(json.loads(r[0]["over"])) if r else None


# ------------------------------------------------------------------ the automatic log: each new position against the rules
def log(since=None):
    """One line per decision (twins in two accounts together): as planned, or how it differed. Built from the Journal's own checks on
    the fills, counting only rules that existed at the time, plus the book limits from FROM. Nothing is typed."""
    from . import journal
    init()
    J = journal.closed()
    notes = {r["trade_key"]: r["note"] for r in db.query("SELECT trade_key, note FROM journal_notes")}
    start = since or min(J.get("rules_from", {}).values() or [FROM])
    by = {}
    for r in J.get("book", []):
        if (r["exit_us"] or r["entry_us"]) < start and not r["open"]:
            continue
        failed = [c[0] for c in r.get("checks") or [] if c[2] and not c[1]]
        live = sum(1 for c in r.get("checks") or [] if c[2])
        if r["entry_us"] >= FROM:
            over = over_on(r["entry_us"])
            if over is not None:
                live += 1
                if r["acct"] in over:
                    failed.append("limits")
        d = by.setdefault(r["decision"], {"decision": r["decision"], "name": r["name"], "ticker": r["ticker"], "strategy": r["strategy"], "entry": r["entry_us"],
                                          "exit": r["exit_us"], "open": r["open"], "accts": [], "key": r["key"], "failed": [], "checks": 0})
        d["accts"].append(r["acct"])
        d["open"] = d["open"] or r["open"]
        d["checks"] = max(d["checks"], live)
        d["failed"] += [f for f in failed if f not in d["failed"]]
        d["note"] = d.get("note") or notes.get(r["key"])
    rows = sorted((d for d in by.values() if d["checks"]), key=lambda d: max(d["entry"], d["exit"] or ""), reverse=True)
    for d in rows:
        d["planned"] = not d["failed"]
        d["why"] = [WHY.get(f, f) for f in d["failed"]]
    n = len(rows)
    return {"rows": rows, "n": n, "planned": sum(d["planned"] for d in rows), "since": start}


# ------------------------------------------------------------------ the scoreboard: drawdown and rules followed, no P&L targets
def drawdown():
    """Each account's fall from its own peak, on weekly NAV change with deposits and withdrawals taken out (accounts.weekly)."""
    from . import accounts
    W = accounts.weekly(260)
    out = {}
    for a in W.get("accounts", []):
        idx, peak, series, worst = 100.0, 100.0, [], 0.0
        for w in reversed(W["weeks"]):
            p = (w["acct"].get(a["id"]) or {}).get("pct")
            if p is None:
                continue
            idx *= 1 + p / 100
            peak = max(peak, idx)
            dd = 100 * (idx / peak - 1)
            worst = min(worst, dd)
            series.append({"d": w["week"], "v": round(dd, 2)})
        if series:
            out[a["label"]] = {"now": series[-1]["v"], "worst": round(worst, 2), "series": series, "weeks": len(series)}
    return out


def payload(risk=None):
    """Everything the Now screen and the Process scoreboard read. risk: the readiness bar's odds, if it has been read."""
    c = save_call(None, risk) if risk is not None else calls()
    try:
        lg = log()
    except Exception as e:
        lg = {"error": f"Log unavailable: {e}", "rows": [], "n": 0, "planned": 0}
    try:
        dd = drawdown()
    except Exception as e:
        dd = {"error": str(e)}
    lim = (load_config().get("risk", {}).get("stress") or {})
    return {"calls": c, "log": lg, "drawdown": dd, "limits": {"cap_pct": lim.get("cap_pct"), "limit_pct": lim.get("limit_pct")}, "from": FROM}
