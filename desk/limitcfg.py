"""Your limits, editable from the Rules page: a worst-case cap per strategy, one cap on every strategy together, and the stress limit
on the whole book. All are % of NAV, per account. They start from config.local.json (risk.stress: cap_pct = the A14 cap, limit_pct =
the stress limit) and every change made in the desk is kept here with its date, so the history can be read back.

A limit that gets tighter applies at once. One that gets looser, or is removed, applies from the next US session: a cap that can be
raised in the minute you want to open a trade stops nothing. Information only: nothing here sizes, blocks or places anything."""
import datetime as dt

from . import db, load_config
from .accounts import US_HOLIDAYS
from .recorder import session_date

STRATEGIES = ("A14", "F49")  # strategies with a cap of their own
KEYS = tuple(f"cap:{s}" for s in STRATEGIES) + ("cap:total", "stress", "ids:A14")
NAMES = {"cap:A14": "A14 worst-case cap", "cap:F49": "F49 worst-case cap", "cap:total": "cap on all strategies together", "stress": "stress limit", "ids:A14": "A14 ids per ticker and account"}


def init():
    db.write("CREATE TABLE IF NOT EXISTS limit_changes (id INTEGER PRIMARY KEY AUTOINCREMENT, made TEXT, key TEXT, old REAL, new REAL, effective TEXT)")


def next_session(d):
    d += dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in US_HOLIDAYS:
        d += dt.timedelta(days=1)
    return d


def _base():
    c = load_config().get("risk", {}).get("stress") or {}
    return {"cap:A14": c.get("cap_pct"), "cap:F49": None, "cap:total": None, "stress": c.get("limit_pct"), "ids:A14": None}


def _rows():
    try:
        init()
        return db.query("SELECT * FROM limit_changes ORDER BY id")
    except Exception:
        return []  # a read-only copy: the config values stand


def current(now=None):
    """{values, pending, log, move}: the limits in force this session, changes waiting for the next one, and every change made."""
    today, vals, pending = session_date(now).isoformat(), _base(), []
    rows = _rows()
    for r in rows:
        if r["effective"] <= today:
            vals[r["key"]] = r["new"]
        else:
            pending.append(dict(r))
    wait = {p["key"]: p for p in pending}  # the last one per key is the one that will apply
    return {"values": vals, "pending": list(wait.values()), "log": [dict(r) for r in rows][::-1][:30], "names": NAMES, "strategies": list(STRATEGIES),
            "move": float((load_config().get("risk", {}).get("stress") or {}).get("move") or 5), "today": today}


def on(key, date):
    """One limit as it stood on a US session date (ISO): what a trade entered that day is scored against, whatever was set later."""
    v = _base().get(key)
    for r in _rows():
        if r["key"] == key and r["effective"] <= date:
            v = r["new"]
    return v


def value(key, acct=None, vals=None):
    """One limit for one account: a config value may be {label: number}; a value set in the desk is one number for every account."""
    v = (vals if vals is not None else current()["values"]).get(key)
    return v.get(acct) if isinstance(v, dict) else v


def save(key, new, now=None):
    """Set one limit (None removes it). Tighter: from this session. Looser or removed: from the next session."""
    if key not in KEYS:
        return {"error": f"Unknown limit: {key}."}
    if new is not None:
        try:
            new = float(new)
        except (TypeError, ValueError):
            return {"error": "A limit is a number, in % of NAV."}
        if not 0 < new <= 100:
            return {"error": "A limit is between 0 and 100% of NAV."}
    if key == "ids:A14" and new is not None and not new.is_integer():
        return {"error": "An id cap must be a whole number."}
    init()
    cur = current(now)
    old = cur["values"].get(key)
    if isinstance(old, dict):
        old = max(old.values()) if old else None
    today = session_date(now)
    db.write("DELETE FROM limit_changes WHERE key=? AND effective>?", (key, today.isoformat()))  # a new choice replaces one still waiting
    if new == old:
        return current(now)
    tighter = new is not None and (old is None or new < old)
    eff = today if tighter else next_session(today)
    db.write("INSERT INTO limit_changes (made, key, old, new, effective) VALUES (?,?,?,?,?)",
             (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), key, old, new, eff.isoformat()))
    return current(now)
