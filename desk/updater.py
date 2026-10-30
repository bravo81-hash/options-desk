"""One update for the whole desk: every data source refreshed in turn, from the header's Update button or on a timer.

Staggered on purpose: one job at a time, TWS first, each on its own client id and disconnected before the next
starts, so the desk never has two TWS connections pulling at once (IBKR caps simultaneous market-data lines and
paces historical requests). Then the web sources, which keep their own freshness rules (yfinance, breadth, CBOE,
the economic calendar), so a click never re-downloads what cannot have changed.

Outside US market hours the option chains and the surface recording are skipped once they were captured after
the close: quotes are frozen, and re-recording would only overwrite the closing snapshot with stale prices.
"""
import datetime as dt
import json
import socket
import threading
import time

from . import a14, db, expected, history, ibdata, load_config, market, recorder, risk
from .recorder import ET, session_date

LOCK = threading.Lock()   # the scheduler's session jobs take it too, so they never overlap an update
status = {"running": False, "source": None, "step": None, "started": None, "finished": None, "steps": []}

STEPS = [  # key, label, what it feeds
    ("marks", "Positions, marks, NAV and fills", "TWS · Actions, Risk grid, P&L"),
    ("indexes", "Index bars: SPX, RUT, VIX family", "TWS · readiness, Term structure, VIX conditions"),
    ("chain", "A14 option chain", "TWS · A14 scanner, Today's pick, Actions ideas"),
    ("em", "Expected-move chain", "TWS · Expected moves"),
    ("surface", "Option surface recording", "TWS · Calendar scanner, Skew & IV, gates"),
    ("etfs", "ETF bars and breadth", "yfinance · Market tab"),
    ("cboe", "CBOE vol indices", "CBOE · Term structure, backtest"),
    ("calendar", "Economic calendar", "Forex Factory · events, Coming up"),
]


def _cfg():
    c = load_config().get("auto_update", {})
    return {"open_min": c.get("open_min", 15), "closed_min": c.get("closed_min", 60), "surface_min": c.get("surface_min", 60),
            "enabled": c.get("enabled", True)}


def us_open(now=None):
    from .accounts import US_HOLIDAYS
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    return now.weekday() < 5 and now.date().isoformat() not in US_HOLIDAYS and dt.time(9, 30) <= now.time() < dt.time(16, 15)


def _last_close(now):
    """The most recent 16:00 ET close that has happened."""
    from .accounts import US_HOLIDAYS
    d = now.astimezone(ET).date()
    if now.astimezone(ET).time() < dt.time(16, 0):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in US_HOLIDAYS:
        d -= dt.timedelta(days=1)
    return dt.datetime.combine(d, dt.time(16, 0), tzinfo=ET)


def _ts(raw):
    if not raw:
        return None
    t = dt.datetime.fromisoformat(raw)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _meta_ts(key):
    raw = db.get_meta(key)
    return _ts(json.loads(raw).get("ts")) if raw else None


def _surface_ts():
    r = db.query("SELECT MAX(ts) t FROM snaps")
    return _ts(r[0]["t"]) if r and r[0]["t"] else None


def _skip_reason(key, now, auto):
    """Why a step needn't run now, or None."""
    is_open = us_open(now)
    close = _last_close(now)
    if key in ("chain", "em", "surface"):
        ts = {"chain": lambda: _meta_ts("a14_chain"), "em": lambda: _meta_ts("em_cache"), "surface": _surface_ts}[key]()
        if not is_open and ts and ts >= close:
            return "captured after the close; quotes are frozen until the open"
        if key == "surface" and is_open and ts and now - ts < dt.timedelta(minutes=_cfg()["surface_min"] if auto else 15):
            return f"recorded {int((now - ts).total_seconds() // 60)} min ago"
    return None


def tws_up():
    """TWS is listening on its API port (a plain socket check: no client id used)."""
    c = load_config()["tws"]
    try:
        socket.create_connection((c["host"], c["port"]), timeout=2).close()
        return True
    except OSError:
        return False


def _run_step(key, force):
    if key == "marks":
        return risk.refresh_marks()
    if key == "indexes":
        n = ibdata.refresh(force=True)
        return {"error": "TWS not reachable"} if n is None else {"ok": True, "detail": f"{n} symbols"}
    if key == "chain":
        return a14.fetch_chain()
    if key == "em":
        return expected.fetch()
    if key == "surface":
        return recorder.record_all(note="update")
    if key == "etfs":
        market.fetch_yf(market.MARKET_SYMBOLS, max_age_h=0.25 if force else 6)
        market.refresh_breadth()
        return {"ok": True}
    if key == "cboe":
        r = history.refresh_cboe()
        return {"ok": True, "detail": "already current" if r.get("skipped") else "downloaded"}
    if key == "calendar":
        market.calendar()
        return {"ok": True}


def run(source="manual"):
    """Run every step in order. Returns False if an update is already running."""
    if not LOCK.acquire(blocking=False):
        return False
    auto = source == "auto"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        status.update(running=True, source=source, started=now.isoformat(timespec="seconds"), finished=None,
                      steps=[{"key": k, "label": lab, "feeds": f, "state": "waiting"} for k, lab, f in STEPS])
        tws_down = not tws_up()
        if tws_down:
            ibdata.drop_unfinished()
        for s in status["steps"]:
            status["step"] = s["key"]
            why = _skip_reason(s["key"], dt.datetime.now(dt.timezone.utc), auto)
            if why or (tws_down and s["feeds"].startswith("TWS")):
                s.update(state="skipped", detail=why or "TWS is not running: start TWS and update again")
                continue
            s["state"] = "running"
            t0 = time.time()
            try:
                r = _run_step(s["key"], force=not auto) or {}
            except Exception as e:
                r = {"error": str(e)}
            s["secs"] = round(time.time() - t0, 1)
            if r.get("error"):
                s.update(state="failed", detail=str(r["error"])[:160])
                if s["feeds"].startswith("TWS") and not tws_up():
                    tws_down = True  # TWS went away mid-update: don't wait out a timeout on every TWS step
            else:
                s.update(state="done", detail=r.get("detail") or "")
        return True
    finally:
        status.update(running=False, step=None, finished=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        try:
            db.set_meta("update_last", json.dumps({"finished": status["finished"], "source": source, "steps": status["steps"]}))
        except Exception:
            pass
        LOCK.release()


def run_async(source="manual"):
    if LOCK.locked():
        return False
    threading.Thread(target=run, kwargs={"source": source}, daemon=True).start()
    return True


def next_auto(now=None):
    """When the next automatic update is due (any finished update, clicked or automatic, resets the clock)."""
    c = _cfg()
    if not c["enabled"]:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    every = dt.timedelta(minutes=c["open_min"] if us_open(now) else c["closed_min"])
    last = _ts(status["finished"]) or _ts((json.loads(db.get_meta("update_last") or "{}")).get("finished"))
    return (last + every) if last else now


def auto(now=None):
    """Called by the scheduler every minute: start a full update when one is due."""
    now = now or dt.datetime.now(dt.timezone.utc)
    nxt = next_auto(now)
    if nxt and now >= nxt and not LOCK.locked():
        run("auto")


def payload():
    nxt = next_auto()
    return {**_payload(), "next_auto": nxt.isoformat(timespec="seconds") if nxt else None}


def _payload():
    if not status["steps"]:
        raw = db.get_meta("update_last")
        if raw:
            last = json.loads(raw)
            return {**status, "finished": last.get("finished"), "source": last.get("source"), "steps": last.get("steps", []),
                    "open": us_open(), "every": _cfg()}
    return {**status, "open": us_open(), "every": _cfg()}
