"""Options Desk: local browser app next to TWS (read-only).

    python app.py            -> http://127.0.0.1:8810

A background thread refreshes CBOE history every 8 hours and records the SPX/RUT
option surface once per US session at config.record.time_et (weekdays).
"""
import datetime as dt
import math
import os
import sys
import threading
import time
import webbrowser

# pythonw (background start) has no console: send output to data/desk.log instead
if sys.stdout is None or sys.stderr is None:
    _data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(_data, exist_ok=True)
    _log_file = open(os.path.join(_data, "desk.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log_file
    sys.stderr = sys.stderr or _log_file

from flask import Flask, jsonify, request, send_from_directory

from desk import ROOT, a14, accounts, journal, pick, readiness, season, vixcond, analytics, db, expected, history, load_config, market, recorder, risk
from desk.recorder import ET, session_date

app = Flask(__name__, static_folder=str(ROOT / "web"), static_url_path="")
CFG = load_config()


def _clean(o):
    """NaN/inf -> None so the JSON is valid."""
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def ok(data):
    return jsonify(_clean(data))


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/term")
def api_term():
    return ok(analytics.term_structure())


@app.get("/api/calendar")
def api_calendar():
    a = request.args
    return ok(analytics.calendar_scan(a.get("symbol", "SPX"), int(a.get("fmin", 3)), int(a.get("fmax", 45)),
                                      int(a.get("gmin", 5)), int(a.get("gmax", 60))))


@app.get("/api/pair/curve")
def api_pair_curve():
    a = request.args
    return ok(analytics.calendar_curve(a.get("symbol", "SPX"), a["front"], a["back"], _f(a.get("strike"))))


@app.get("/api/pair")
def api_pair():
    a = request.args
    return ok(analytics.pair_detail(a.get("symbol", "SPX"), a["front"], a["back"]))


@app.get("/api/skew")
def api_skew():
    return ok(analytics.skew_iv(request.args.get("symbol", "SPX"), int(request.args.get("tenor", 30))))


@app.get("/api/evidence")
def api_evidence():
    return ok(analytics.evidence())


@app.get("/api/status")
def api_status():
    nxt = next_record_time()
    return ok({"recorder": recorder.status, "inventory": analytics.inventory(),
               "next_record": nxt.isoformat() if nxt else None, "record_time_et": CFG["record"]["time_et"],
               "cboe_refreshed": db.get_meta("cboe_refreshed"), "last_record": db.get_meta("last_record")})


@app.post("/api/record")
def api_record():
    if recorder.status["running"]:
        return ok({"started": False, "message": "A recording is already running."})
    threading.Thread(target=recorder.record_all, kwargs={"note": "manual"}, daemon=True).start()
    return ok({"started": True})


@app.post("/api/refresh-history")
def api_refresh_history():
    try:
        return ok({"cboe": history.refresh_cboe(force=True)})
    except Exception as e:
        return ok({"error": f"CBOE download failed: {e}"})


@app.get("/api/risk")
def api_risk():
    return ok(risk.payload())


@app.post("/api/risk/refresh")
def api_risk_refresh():
    if risk.status["running"]:
        return ok({"started": False, "message": "A refresh is already running."})
    threading.Thread(target=risk.refresh_marks, daemon=True).start()
    return ok({"started": True})


@app.get("/api/risk/status")
def api_risk_status():
    return ok(risk.status)


# ------------------------------------------------------------------ Market tab (ex Market Desk)
@app.get("/market")
def market_page():
    return send_from_directory(app.static_folder, "market.html")


@app.get("/api/md/ohlcv")
def api_md_ohlcv():
    a = request.args
    try:
        return ok(market.ohlcv(a["symbol"], a.get("interval", "1D"), int(a.get("count", 300)), adj=a.get("adj") == "1"))
    except Exception as e:
        return ok({"success": False, "error": str(e)})


@app.get("/api/md/calendar")
def api_md_calendar():
    return ok(market.calendar(request.args.get("date_from"), request.args.get("date_to")))


@app.get("/api/md/account")
def api_md_account():
    import json as _json
    raw = db.get_meta("risk_marks")
    blob = _json.loads(raw) if raw else {}
    labels = CFG["risk"]["account_labels"]
    acct = blob.get("account") or {"summary": {}, "fills": []}
    pos = {}
    for p in blob.get("positions", []):
        pos[p["account"]] = pos.get(p["account"], 0) + 1
    return ok({"ts": blob.get("ts"), "labels": labels, "summary": acct["summary"], "fills": acct["fills"], "positions": pos})


@app.post("/api/md/refresh")
def api_md_refresh():
    threading.Thread(target=market.refresh_all, kwargs={"force": True}, daemon=True).start()
    return ok({"started": True})


@app.get("/api/md/status")
def api_md_status():
    from desk import ibdata
    return ok({**market.status, "breadth_refreshed": db.get_meta("breadth_refreshed"), "members": db.get_meta("breadth_members"),
               "ibkr_indexes": db.get_meta("ibdata_last")})


# ------------------------------------------------------------------ expected moves
@app.get("/api/em")
def api_em():
    return ok(expected.payload())


@app.post("/api/em/refresh")
def api_em_refresh():
    return ok({"started": expected.refresh_async()})


# ------------------------------------------------------------------ A14 scanner
def _f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


@app.get("/api/a14/scan")
def api_a14_scan():
    a = request.args
    syms = tuple(s for s in a.get("sym", "SPX,RUT").split(",") if s in a14.GRID)
    vol = a.get("vol", "rv20")
    ex = _f(a.get("exit"))
    res = a14.scan(symbols=syms, dte_min=_f(a.get("dte_min"), 14), dte_max=_f(a.get("dte_max"), 45),
                   exit_days=int(ex) if ex else None, vol_basis=vol, vol_custom=_f(a.get("vol_custom")),
                   min_credit=_f(a.get("min_credit")), up_lo=_f(a.get("up_lo"), -1.5), up_hi=_f(a.get("up_hi"), 1.0))
    return ok({**res, "running": a14.status["running"], "log": a14.status["log"]})


@app.post("/api/a14/refresh")
def api_a14_refresh():
    return ok({"started": a14.refresh_async()})


@app.get("/api/a14/status")
def api_a14_status():
    return ok({"running": a14.status["running"], "log": a14.status["log"]})


@app.get("/api/a14/curve")
def api_a14_curve():
    a = request.args
    return ok(a14.curve(a["sym"], a["expiry"], float(a["u"]), float(a["s"]), float(a["l"]), int(_f(a.get("exit"))) if _f(a.get("exit")) else None))


_READY = {"t": None, "v": None, "lock": threading.Lock()}


@app.get("/api/journal")
def api_journal():
    out = journal.closed()
    try:
        out["speed"] = a14.stats()["speed"]
    except Exception:
        out["speed"] = None
    return ok(out)


@app.post("/api/journal/note")
def api_journal_note():
    b = request.get_json(force=True) or {}
    return ok(journal.save_note(b.get("key", ""), b.get("note", "")))


@app.get("/api/readiness")
def api_readiness():
    """Cached 5 minutes: it pulls VIX conditions, warnings and history stats together (~10 s cold)."""
    try:
        with _READY["lock"]:
            if _READY["v"] is None or (time.time() - _READY["t"]) > 300 or request.args.get("fresh"):
                _READY["v"], _READY["t"] = readiness.now(), time.time()
            return ok(_READY["v"])
    except Exception as e:
        return ok({"error": f"Readiness unavailable: {e}"})


@app.get("/api/freshness")
def api_freshness():
    """Date of every data source vs the latest completed US session, so stale panels are obvious."""
    import json as _j
    from desk.accounts import US_HOLIDAYS
    now = dt.datetime.now(dt.timezone.utc).astimezone(ET)
    sess = session_date(now)
    if sess == now.date() and (now.hour, now.minute) < (16, 0):  # session still running: the last close is the day before
        sess = sess - dt.timedelta(days=1)
    while sess.weekday() >= 5 or sess.isoformat() in US_HOLIDAYS:
        sess -= dt.timedelta(days=1)
    def d_of(ts):
        if not ts:
            return None
        t = dt.datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return session_date(t).isoformat()  # the session a capture belongs to
    def meta_ts(k):
        raw = db.get_meta(k)
        return _j.loads(raw).get("ts") if raw else None
    q = lambda sql, *a: (db.query(sql, a) or [{}])[0].get("d")
    pl = risk.payload() if db.get_meta("risk_marks") else {}
    fr = (pl.get("one_fresh") or {}) if pl else {}
    src = [
        ("Index prices", q("SELECT MAX(date) d FROM index_daily WHERE symbol='SPX'"), "SPX/RUT/VIX family daily closes (IBKR, CBOE fallback)"),
        ("ETF prices", q("SELECT MAX(date) d FROM bars_daily WHERE symbol='SPY'"), "Market tab ETFs and sectors (yfinance)"),
        ("Surface", q("SELECT MAX(date) d FROM snaps"), "daily SPX/RUT option recording: Calendar scanner, Skew, gates"),
        ("Chain", d_of(meta_ts("a14_chain")), "A14 scanner and Today's pick option chain"),
        ("Expected moves", d_of(meta_ts("em_cache")), "Expected moves tab"),
        ("Marks", d_of(meta_ts("risk_marks")), "Risk grid marks, positions, NAV"),
    ]
    out = [{"name": n, "date": d, "stale": (d or "") < sess.isoformat(), "what": w} for n, d, w in src]
    out.append({"name": "ONE export", "date": fr.get("exported", "")[:10] if fr.get("exported") else None, "stale": bool(fr.get("stale")),
                "what": f"ONE Summary Report, {fr.get('age_h')}h old" + (f", {fr.get('fills_since')} fills since" if fr.get("fills_since") else "")})
    return ok({"last_close": sess.isoformat(), "sources": out})


@app.get("/api/vixcond")
def api_vixcond():
    try:
        return ok(vixcond.now())
    except Exception as e:
        return ok({"error": f"VIX conditions unavailable: {e}"})


@app.get("/api/season")
def api_season():
    a = request.args
    sym = a.get("sym", "SPX")
    if sym not in season.INDICES:
        return ok({"error": "unknown index"})
    return ok(season.compute(sym, int(_f(a.get("years"), 20)), a.get("cycle", "all")))


@app.get("/api/pick")
def api_pick():
    a = request.args
    return ok(pick.today(exit_days=int(_f(a.get("exit"), 14)), vol_basis=a.get("vol", "rv20")))


@app.get("/api/a14/stats")
def api_a14_stats():
    return ok(a14.stats())


@app.get("/api/a14/history")
def api_a14_history():
    return ok(a14.history())


# ------------------------------------------------------------------ P&L and reconciliation (ex TWS Matcher)
@app.get("/api/pnl/weekly")
def api_pnl_weekly():
    return ok(accounts.weekly(int(request.args.get("weeks", 26))))


@app.get("/api/pnl/today")
def api_pnl_today():
    import json as _json
    raw = db.get_meta("risk_marks")
    blob = _json.loads(raw) if raw else {}
    return ok({"ts": blob.get("ts"), "labels": CFG["risk"]["account_labels"], **(blob.get("acct") or {})})


@app.get("/api/recon")
def api_recon():
    return ok(risk.recon_view())


@app.get("/api/one-import/<account>.csv")
def api_one_import(account):
    from flask import Response
    date = request.args.get("date")
    body = accounts.one_import_csv(account, date)
    label = CFG["risk"]["account_labels"].get(account, account)
    name = f"ONEImport_{label}_{date or dt.date.today().isoformat()}.csv"
    return Response(body, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/tws")
def api_tws():
    return ok(recorder.connection_check())


# ------------------------------------------------------------------ scheduler
def next_record_time(now=None):
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    hh, mm = map(int, CFG["record"]["time_et"].split(":"))
    cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now >= cand:
        cand += dt.timedelta(days=1)
    while cand.weekday() >= 5:
        cand += dt.timedelta(days=1)
    return cand


def _attempt_ok(key, minutes=15):
    """Throttle retries (e.g. TWS not running): at most one attempt per `minutes` for each job."""
    last = db.get_meta(f"attempt:{key}")
    if last and dt.datetime.fromisoformat(last) > dt.datetime.now() - dt.timedelta(minutes=minutes):
        return False
    db.set_meta(f"attempt:{key}", dt.datetime.now().isoformat(timespec="seconds"))
    return True


def session_jobs(now):
    """Recording at 15:40 ET and the final capture at 16:15 ET for the latest US session.

    The close falls at about 6:40-7:15 am in Sydney, so the laptop is often asleep then. If a session's jobs
    were missed they now catch up as soon as the app is running with TWS, any time before the next open,
    using TWS's closing (frozen) quotes, and are marked as after-hours captures.
    """
    from desk.accounts import US_HOLIDAYS
    sess = session_date(now)  # today once open; the previous weekday before the open and at weekends
    if sess.isoformat() in US_HOLIDAYS:
        return
    hh, mm = map(int, CFG["record"]["time_et"].split(":"))
    due = dt.datetime.combine(sess, dt.time(hh, mm), tzinfo=ET)
    final_due = dt.datetime.combine(sess, dt.time(16, 15), tzinfo=ET)
    late = sess < now.date()  # the session is over and we are past its day: an after-hours catch-up
    due_utc = due.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    recorded = db.query("SELECT 1 FROM snaps WHERE date=? AND ts>=? LIMIT 1", (sess.isoformat(), due_utc))
    if not recorded and (now >= due or late) and not recorder.status["running"] and _attempt_ok(f"record:{sess}"):
        recorder.record_all(note="after-hours catch-up" if late or now > due + dt.timedelta(hours=2, minutes=20) else "scheduled")
        risk.refresh_marks()  # keep the risk grid's marks current too
        expected.fetch()      # expected moves and the A14 scanner chain at the same time of day
        a14.fetch_chain()
    # option chains older than the last close (laptop asleep through the recording): refresh them as soon as
    # TWS is up, live in market hours, closing quotes otherwise; at most once an hour
    import json as _j
    last_close = sess if (late or now >= final_due) else sess - dt.timedelta(days=1)
    for meta_key, job in (("a14_chain", a14.fetch_chain), ("em_cache", expected.fetch)):
        raw = db.get_meta(meta_key)
        ts = _j.loads(raw).get("ts") if raw else None
        cap = session_date(dt.datetime.fromisoformat(ts)) if ts else None
        if (cap is None or cap < last_close) and _attempt_ok(f"stale:{meta_key}", 60):
            job()
    key = f"acct_final:{sess}"
    if not db.get_meta(key) and (now >= final_due or late) and not risk.status["running"] and _attempt_ok(f"final:{sess}"):
        res = risk.refresh_marks()  # final NAV and fills for the session
        if res.get("ok"):
            db.set_meta(key, dt.datetime.now().isoformat(timespec="seconds"))


def scheduler():
    while True:
        try:
            market.refresh_all()  # yfinance bars + computed breadth; no-ops while fresh
        except Exception as e:
            recorder._log(f"market refresh failed: {e}")
        try:
            history.refresh_cboe()
        except Exception as e:
            recorder._log(f"CBOE refresh failed: {e}")
        now = dt.datetime.now(dt.timezone.utc).astimezone(ET)
        try:
            session_jobs(now)
        except Exception as e:
            recorder._log(f"session jobs failed: {e}")
        time.sleep(60)


def _single_instance():
    """Windows lets several servers bind the same port (SO_REUSEADDR), and each would run the scheduler with
    the same TWS client ids. A named mutex keeps it to one copy; a second start just opens the page."""
    if os.name != "nt":
        return True
    import ctypes
    global _MUTEX
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _MUTEX = k32.CreateMutexW(None, False, r"Local\OptionsDeskApp")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if not _single_instance():
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://127.0.0.1:{CFG['port']}/")
        sys.exit(0)
    db.init()
    accounts.init()
    try:
        accounts.import_tws_matcher_history()  # one-off seed of daily NAV / P&L history
    except Exception as e:
        print("NAV history import skipped:", e)
    threading.Thread(target=scheduler, daemon=True).start()
    url = f"http://127.0.0.1:{CFG['port']}/"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=CFG["port"], debug=False, threaded=True)
