"""Read-only TWS recorder: option-chain snapshots and IB daily history.

Never places, modifies or cancels orders: the connection is opened with readonly=True
and the module only calls market-data and contract-detail requests.
"""
import asyncio
import datetime as dt
import logging
import math
import threading
from zoneinfo import ZoneInfo

from . import db, load_config
from .volmath import bs_delta, implied_vol, interp_by_delta, interp_total_variance

ET = ZoneInfo("America/New_York")
logging.getLogger("ib_async").setLevel(logging.CRITICAL)  # unlisted strikes are expected and skipped
TENORS = [7, 14, 21, 30, 45, 60, 90, 120, 180]
_run_lock = threading.Lock()
status = {"running": False, "last": None, "log": []}


def session_date(now=None):
    """Trading session the data belongs to: weekends and pre-open map to the prior weekday."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    d = now.date()
    if now.weekday() < 5 and (now.hour, now.minute) < (9, 30):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _log(msg):
    line = f"{dt.datetime.now().strftime('%H:%M:%S')}  {msg}"
    status["log"] = (status["log"] + [line])[-80:]


def _connect():
    from ib_async import IB
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    cfg = load_config()["tws"]
    ib = IB()
    ib.connect(cfg["host"], cfg["port"], clientId=cfg["client_id"], readonly=True, timeout=15)
    ib.reqMarketDataType(2)  # live when the market is open, frozen close values otherwise
    return ib


def _index(ib, sym, exchange):
    from ib_async import Index
    c = Index(sym, exchange)
    ib.qualifyContracts(c)
    return c


def _pick_expiries(expirations, today, rec):
    out = []
    for e in sorted(expirations):
        d = dt.datetime.strptime(e, "%Y%m%d").date()
        dte = (d - today).days
        if dte < 1:
            continue
        third_friday = d.weekday() == 4 and 15 <= d.day <= 21
        if dte <= rec["all_expiries_to_dte"] or (dte <= rec["fridays_to_dte"] and d.weekday() == 4) \
                or (dte <= rec["monthlies_to_dte"] and third_friday):
            out.append((e, dte))
    return out


def _nearest(strikes, x):
    return min(strikes, key=lambda k: abs(k - x))


def record_symbol(ib, sym, scfg, rec):
    from ib_async import Option
    und = _index(ib, sym, scfg["exchange"])
    tk = ib.reqMktData(und, "", True, False)
    ib.sleep(2.5)
    spot = tk.marketPrice()
    if not spot or spot != spot:
        spot = tk.close
    if not spot or spot != spot:
        raise RuntimeError(f"{sym}: no underlying price")
    params = [p for p in ib.reqSecDefOptParams(sym, "", "IND", und.conId) if p.exchange == "SMART"]
    weekly = [p for p in params if p.tradingClass == scfg["trading_class"]]
    if not weekly:
        raise RuntimeError(f"{sym}: no {scfg['trading_class']} chain")
    cls_of = {}
    for p in params:  # weekly (PM-settled) class wins; standard monthlies fill the gaps further out
        for e in p.expirations:
            if p.tradingClass == scfg["trading_class"] or e not in cls_of:
                cls_of[e] = p.tradingClass
    strikes = sorted(s for s in weekly[0].strikes if s % scfg["step"] == 0)
    sess = session_date()
    exps = _pick_expiries(cls_of.keys(), sess, rec)
    guess = 0.16
    contracts = []
    wide = [k for k in strikes if k % 25 == 0] or strikes  # far expiries list 25-point strikes only
    for e, dte in exps:
        t = max(dte, 1) / 365.0
        grid = strikes if dte <= 45 else wide
        sd = spot * guess * math.sqrt(t)
        ks = set()
        for k in (0, .2, .4, .6, .8, 1.0, 1.25, 1.5, 1.8, 2.2, 2.7):
            ks.add((_nearest(grid, spot - k * sd), "P"))
        for k in (0, .2, .4, .6, .8, 1.0, 1.3, 1.7):  # wide call side: covers in-the-money put strikes
            ks.add((_nearest(grid, spot + k * sd), "C"))
        atm = _nearest(grid, spot)
        ks |= {(atm, "C"), (atm, "P")}
        for k, r in ks:
            contracts.append(Option(sym, e, k, r, "SMART", tradingClass=cls_of[e]))
    _log(f"{sym}: spot {spot:.2f}, {len(exps)} expiries, {len(contracts)} contracts")
    qualified = []
    for i in range(0, len(contracts), 50):
        qualified += [c for c in ib.qualifyContracts(*contracts[i:i + 50]) if c and c.conId]
    rows = []
    for i in range(0, len(qualified), 45):
        batch = qualified[i:i + 45]
        tks = [ib.reqMktData(c, "", True, False) for c in batch]
        for _ in range(24):
            ib.sleep(0.5)
            if all(t.modelGreeks is not None or (t.bid == t.bid and t.ask == t.ask and t.bid is not None) for t in tks):
                break
        for c, t in zip(batch, tks):
            bid = t.bid if t.bid == t.bid and t.bid is not None and t.bid >= 0 else None
            ask = t.ask if t.ask == t.ask and t.ask is not None and t.ask > 0 else None
            mid = (bid + ask) / 2 if bid is not None and ask is not None else None
            g = t.modelGreeks
            dte = (dt.datetime.strptime(c.lastTradeDateOrContractMonth, "%Y%m%d").date() - sess).days
            rows.append(dict(expiry=c.lastTradeDateOrContractMonth, dte=dte, strike=c.strike, right=c.right,
                             bid=bid, ask=ask, mid=mid, ib_iv=g.impliedVol if g else None,
                             gamma=g.gamma if g else None, vega=g.vega if g else None, theta=g.theta if g else None))
    fit_rows(rows, spot)
    return spot, rows


def fit_rows(rows, spot):
    """Own IV and delta from mids, priced off each expiry's put-call-parity forward.

    Only out-of-the-money quotes with a positive bid get a vol (ITM and zero-bid quotes are
    unreliable on index options); the forward comes from the call/put pair nearest spot.
    """
    by = {}
    for r in rows:
        by.setdefault(r["expiry"], []).append(r)
    for e, q in by.items():
        t = max(q[0]["dte"], 0.5) / 365.0
        pairs = {}
        for r in q:
            if r["mid"] is not None:
                pairs.setdefault(r["strike"], {})[r["right"]] = r["mid"]
        both = [(k, v) for k, v in pairs.items() if "C" in v and "P" in v]
        fwd = spot
        if both:
            k, v = min(both, key=lambda kv: abs(kv[0] - spot))
            fwd = k + v["C"] - v["P"]
        for r in q:
            r["fwd"] = fwd
            otm = (r["right"] == "P" and r["strike"] <= fwd) or (r["right"] == "C" and r["strike"] >= fwd)
            near = abs(r["strike"] - fwd) <= 0.004 * fwd  # both sides count right at the money
            ok_quote = r["mid"] is not None and r["bid"] is not None and r["bid"] > 0
            r["iv"] = implied_vol(r["mid"], fwd, r["strike"], t, r["right"]) if ok_quote and (otm or near) else None
            r["delta"] = bs_delta(fwd, r["strike"], t, r["iv"], r["right"]) if r["iv"] else None


def summarize(rows, spot):
    by = {}
    for r in rows:
        by.setdefault((r["expiry"], r["dte"]), []).append(r)
    out = []
    for (e, dte), q in sorted(by.items(), key=lambda x: x[0][1]):
        t = max(dte, 0.5) / 365.0
        ivs = [r for r in q if r["iv"]]
        if len(ivs) < 3:
            continue
        # ATM: strike-interpolated IV around spot, puts and calls averaged
        fwd = q[0].get("fwd", spot)
        pts = {}
        for r in ivs:  # one vol per strike: OTM side, averaged where both sides qualify
            pts.setdefault(r["strike"], []).append(r["iv"])
        curve = sorted((k, sum(v) / len(v)) for k, v in pts.items())
        below = [p for p in curve if p[0] <= fwd]
        above = [p for p in curve if p[0] >= fwd]
        atm_iv = None
        if below and above:
            (k1, v1), (k2, v2) = below[-1], above[0]
            atm_iv = v1 if k2 == k1 else v1 + (v2 - v1) * (fwd - k1) / (k2 - k1)
        puts = [(r["delta"], r["iv"]) for r in ivs if r["right"] == "P" and r["delta"] is not None]
        calls = [(r["delta"], r["iv"]) for r in ivs if r["right"] == "C" and r["delta"] is not None]
        atm_k = min((r["strike"] for r in q), key=lambda k: abs(k - fwd))
        pm = next((r["mid"] for r in q if r["strike"] == atm_k and r["right"] == "P"), None)
        cm = next((r["mid"] for r in q if r["strike"] == atm_k and r["right"] == "C"), None)
        out.append(dict(expiry=e, dte=dte, t=t, atm_strike=atm_k, atm_iv=atm_iv,
                        p25_iv=interp_by_delta(puts, -0.25), p10_iv=interp_by_delta(puts, -0.10),
                        c25_iv=interp_by_delta(calls, 0.25), atm_put_mid=pm, atm_call_mid=cm))
    return out


def tenorize(summary):
    res = {}
    for ten in TENORS:
        t = ten / 365.0
        rec = {}
        for k in ("atm_iv", "p25_iv", "p10_iv", "c25_iv"):
            rec[k] = interp_total_variance([(s["t"], s[k]) for s in summary], t)
        if summary and (t < summary[0]["t"] * 0.7 or t > summary[-1]["t"] * 1.05):
            continue  # no extrapolation far outside recorded expiries
        res[ten] = rec
    return res


def record_all(note="scheduled"):
    if not _run_lock.acquire(blocking=False):
        return {"error": "a recording is already running"}
    status["running"] = True
    cfg = load_config()
    out = {}
    ib = None
    try:
        ib = _connect()
        _log("connected to TWS (read-only)")
        for sym, scfg in cfg["symbols"].items():
            try:
                spot, rows = record_symbol(ib, sym, scfg, cfg["record"])
                now = dt.datetime.now(dt.timezone.utc)
                date = session_date(now).isoformat()
                # one snapshot per symbol per session: a re-record replaces that day's rows
                old = [r["id"] for r in db.query("SELECT id FROM snaps WHERE symbol=? AND date=?", (sym, date))]
                for oid in old:
                    db.write("DELETE FROM quotes WHERE snap_id=?", (oid,))
                    db.write("DELETE FROM expiry_summary WHERE snap_id=?", (oid,))
                    db.write("DELETE FROM snaps WHERE id=?", (oid,))
                sid = db.write("INSERT INTO snaps (symbol, ts, date, spot, n_quotes, note) VALUES (?,?,?,?,?,?)",
                               (sym, now.isoformat(timespec="seconds"), date, spot, len(rows), note))
                db.write("INSERT INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(sid, r["expiry"], r["dte"], r["strike"], r["right"], r["bid"], r["ask"], r["mid"], r["iv"],
                           r["delta"], r["gamma"], r["vega"], r["theta"], r["ib_iv"], r["fwd"]) for r in rows], many=True)
                summ = summarize(rows, spot)
                db.write("INSERT INTO expiry_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(sid, sym, date, s["expiry"], s["dte"], s["t"], s["atm_strike"], s["atm_iv"], s["p25_iv"],
                           s["p10_iv"], s["c25_iv"], s["atm_put_mid"], s["atm_call_mid"]) for s in summ], many=True)
                ten = tenorize(summ)
                db.write("INSERT OR REPLACE INTO tenor_daily VALUES (?,?,?,?,?,?,?)",
                         [(sym, date, k, v["atm_iv"], v["p25_iv"], v["p10_iv"], v["c25_iv"]) for k, v in ten.items()], many=True)
                out[sym] = {"spot": spot, "quotes": len(rows), "expiries": len(summ), "date": date}
                _log(f"{sym}: saved {len(rows)} quotes, {len(summ)} expiries for {date}")
            except Exception as e:  # one symbol failing must not lose the other
                out[sym] = {"error": str(e)}
                _log(f"{sym}: FAILED {e}")
        fetch_ib_history(ib)
        status["last"] = dt.datetime.now().isoformat(timespec="seconds")
        db.set_meta("last_record", status["last"])
        return out
    except Exception as e:
        _log(f"TWS connection failed: {e}")
        return {"error": f"Could not connect to TWS: {e}"}
    finally:
        if ib is not None:
            ib.disconnect()
        status["running"] = False
        _run_lock.release()


def fetch_ib_history(ib, years=5):
    """SPX/RUT daily closes and IB's 30-day implied vol, so z-scores work from day one."""
    cfg = load_config()
    for sym, scfg in cfg["symbols"].items():
        try:
            und = _index(ib, sym, scfg["exchange"])
            for what, key in (("TRADES", sym), ("OPTION_IMPLIED_VOLATILITY", f"{sym}.IV30")):
                have = db.query("SELECT MAX(date) d, COUNT(*) n FROM index_daily WHERE symbol=?", (key,))[0]
                dur = f"{years} Y" if not have["n"] or have["n"] < 200 else "1 M"
                bars = ib.reqHistoricalData(und, "", dur, "1 day", what, True)
                rows = [(key, b.date.isoformat(), float(b.close)) for b in bars if b.close and b.close > 0]
                db.write("INSERT OR REPLACE INTO index_daily (symbol, date, close) VALUES (?,?,?)", rows, many=True)
                _log(f"{key}: {len(rows)} daily bars")
        except Exception as e:
            _log(f"{sym} history failed: {e}")


def connection_check():
    try:
        ib = _connect()
        ok = ib.isConnected()
        ib.disconnect()
        return {"ok": ok}
    except Exception as e:
        return {"ok": False, "error": str(e)}
