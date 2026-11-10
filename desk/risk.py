"""Open positions for the risk-graph grid.

Trades and legs come from the newest ONE export of either kind (ONE knows which legs form a trade).
Marks (mid, IV) and underlying prices come from TWS, read-only, on their own client id.
A reconciliation compares ONE's open legs with IBKR positions per mapped account.
Risk curves are computed in the browser from these inputs.
"""
import asyncio
import datetime as dt
import json
import logging
import re
import threading

from . import db, load_config, one
from .market import two_zones
from .recorder import ET
from .trades import CALENDAR_FAMILY, classify, fix_name
from .volmath import bs_price, forward_vol, implied_vol

logging.getLogger("ib_async").setLevel(logging.CRITICAL)
_lock = threading.Lock()
status = {"running": False, "log": [], "last": None}
OCC = re.compile(r"^(?P<root>[A-Z.]+)\s*(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<r>[CP])(?P<k>\d{8})$")
INDEXES = {"SPX": "CBOE", "RUT": "RUSSELL", "NDX": "NASDAQ", "VIX": "CBOE", "XSP": "CBOE"}
AM_ROOTS = {"SPX", "RUT", "NDX"}  # standard monthlies settle at the open


def _log(msg):
    status["log"] = (status["log"] + [f"{dt.datetime.now().strftime('%H:%M:%S')}  {msg}"])[-60:]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _local_dt(s):
    for fmt in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _one_group(acct):
    return re.sub(r"^\d+\.\s*", "", acct).strip()


def parse_occ(sym):
    m = OCC.match(re.sub(r"\s+", "", sym))
    if not m:
        return None
    return {"root": m["root"], "expiry": f"20{m['y']}{m['m']}{m['d']}", "right": m["r"], "strike": int(m["k"]) / 1000.0}


def _ib_symbol(occ, one_expiry):
    """ONE stamps option symbols with expiry + 1 day; rebuild the IBKR/OCC local symbol from
    ONE's Expiry column instead (e.g. 'SPXW  261030P07625000')."""
    d = dt.datetime.strptime(one_expiry.strip(), "%d/%m/%Y")
    return f"{occ['root']:<6}{d:%y%m%d}{occ['right']}{int(round(occ['strike'] * 1000)):08d}"


def load_open_trades(path=None):
    amap = load_config()["risk"]["account_map"]
    rows, path, _ = one.read(path)
    if not path:
        return [], None
    trades = []
    for r in rows:
        if r["status"] != "Open":
            continue
        grp = _one_group(r["account"])
        t = {"id": f"{r['account']}#{r['trade_id']}", "account": r["account"], "group": grp, "ib_account": amap.get(grp),
             "underlying": r["underlying"], "expiration": r["expiration"], "trade_id": r["trade_id"], "name": fix_name(r["name"]),
             "opened": r["opened"], "dte": r["dte"], "dit": r["dit"], "margin": r["margin"], "comms": r["comms"], "one_pnl": r["pnl"],
             "one_pnl_pct": r["ret"], "realized": sum(lg["pnl"] or 0.0 for lg in r["legs"] if lg["close"]), "legs": []}
        for lg in r["legs"]:
            if lg["close"]:
                continue
            occ = parse_occ(lg["symbol"])
            t["legs"].append({"symbol": _ib_symbol(occ, lg["expiry"]) if occ else lg["symbol"], "one_symbol": lg["symbol"], "occ": occ,
                              "qty": (-1 if lg["side"].lower() == "sell" else 1) * lg["qty"], "open_price": lg["open_px"], "commission": lg["comm"] or 0.0,
                              "one_expiry": lg["expiry"], "right": lg["type"][:1].upper(), "desc": lg["desc"], "underlying": lg["underlying"]})
        trades.append(t)
    # merge duplicate open legs of the same contract (ONE lists fills separately)
    for t in trades:
        merged = {}
        for lg in t["legs"]:
            m = merged.get(lg["symbol"])
            if not m:
                merged[lg["symbol"]] = dict(lg)
                continue
            q = m["qty"] + lg["qty"]
            if q and m["open_price"] is not None and lg["open_price"] is not None:
                m["open_price"] = (m["open_price"] * m["qty"] + lg["open_price"] * lg["qty"]) / q
            m["qty"] = q
            m["commission"] += lg["commission"]
        t["legs"] = [lg for lg in merged.values() if lg["qty"]]
    return [t for t in trades if t["legs"]], path


def adjustment_counts():
    """{account#trade_id: adjustments} from the newest ONE Detail Report, and when it was exported."""
    from . import positions
    pos, exported = positions.load()
    return {k: v["adj"] for k, v in pos.items()}, exported


def _entry_spot(underlying, opened):
    """Index close on the US session the trade was entered (ONE local time - 14h)."""
    t = _local_dt(opened or "")
    if not t:
        return None
    rows = db.query("SELECT close FROM index_daily WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
                    (underlying, (t - dt.timedelta(hours=14)).date().isoformat()))
    return rows[0]["close"] if rows else None


# ------------------------------------------------------------------ TWS marks
def _connect():
    from ib_async import IB
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    cfg = load_config()
    ib = IB()
    ib.connect(cfg["tws"]["host"], cfg["tws"]["port"], clientId=cfg["risk"]["client_id"], readonly=True, timeout=15)
    ib.reqMarketDataType(2)
    return ib


def _underlying_contract(sym):
    from ib_async import Index, Stock
    return Index(sym, INDEXES[sym]) if sym in INDEXES else Stock(sym, "SMART", "USD")


def refresh_marks():
    """Fetch mids/IVs for every open leg and the underlyings; store as one JSON blob."""
    if not _lock.acquire(blocking=False):
        return {"error": "A refresh is already running."}
    status["running"] = True
    ib = None
    try:
        from ib_async import Contract
        trades, path = load_open_trades()
        legs = {lg["symbol"]: lg for t in trades for lg in t["legs"]}
        unds = sorted({t["underlying"] for t in trades})
        _log(f"{len(trades)} open trades, {len(legs)} distinct contracts, underlyings {', '.join(unds)}")
        ib = _connect()
        spots, prev = {}, {}
        for u in unds:
            c = _underlying_contract(u)
            ib.qualifyContracts(c)
            tk = ib.reqMktData(c, "", True, False)
            ib.sleep(2)
            px = tk.marketPrice()
            spots[u] = px if px == px and px else (tk.close if tk.close == tk.close else None)
            prev[u] = tk.close if tk.close == tk.close else None
        cons = []
        for sym in legs:
            c = Contract(secType="OPT", localSymbol=sym, exchange="SMART", currency="USD")
            cons.append(c)
        q = []
        for i in range(0, len(cons), 40):
            q += [c for c in ib.qualifyContracts(*cons[i:i + 40]) if c and c.conId]
        marks = {}
        for i in range(0, len(q), 40):
            batch = q[i:i + 40]
            tks = [ib.reqMktData(c, "", True, False) for c in batch]
            for _ in range(20):
                ib.sleep(0.5)
                if all(t.modelGreeks is not None for t in tks):
                    break
            for c, t in zip(batch, tks):
                bid = t.bid if t.bid == t.bid and t.bid is not None and t.bid >= 0 else None
                ask = t.ask if t.ask == t.ask and t.ask is not None and t.ask > 0 else None
                mid = (bid + ask) / 2 if bid is not None and ask is not None else None
                g = t.modelGreeks
                marks[c.localSymbol] = {"bid": bid, "ask": ask, "mid": mid, "iv": g.impliedVol if g else None,
                                        "und": g.undPrice if g else None, "last_trade": c.lastTradeDateOrContractMonth,
                                        "trading_class": c.tradingClass,
                                        "close": t.close if t.close == t.close and t.close and t.close > 0 else None}
        missing = [s for s in legs if s not in marks]
        positions, stocks, raw_pos = [], [], []
        try:
            raw_pos = list(ib.reqPositions())
            for p in raw_pos:
                mult = _f(p.contract.multiplier) or 1.0
                if p.contract.secType == "OPT":
                    positions.append({"account": p.account, "symbol": p.contract.localSymbol, "qty": p.position,
                                      "avg_price": p.avgCost / mult if p.avgCost else None, "con_id": p.contract.conId})
                elif p.contract.secType in ("STK", "ETF") and p.position:
                    stocks.append({"account": p.account, "symbol": p.contract.symbol, "qty": p.position, "avg_price": p.avgCost})
        except Exception as e:
            _log(f"positions failed: {e}")
        acct_data = {}
        try:
            from . import accounts as _accounts
            acct_data = _accounts.collect(ib, raw_pos, marks)
            _log("account P&L: " + ", ".join(f"{a} {(v or {}).get('daily')}" for a, v in acct_data.get("daily", {}).items()))
        except Exception as e:
            _log(f"account P&L failed: {e}")
        account = {"summary": {}, "fills": []}
        try:
            tags = {"NetLiquidation", "TotalCashValue", "BuyingPower", "ExcessLiquidity", "MaintMarginReq",
                    "InitMarginReq", "GrossPositionValue", "AvailableFunds"}
            for av in ib.accountSummary():
                if av.tag in tags and av.account != "All":
                    a = account["summary"].setdefault(av.account, {"currency": av.currency})
                    a[av.tag] = _f(av.value)
            from .accounts import todays_fills
            for f in todays_fills(ib):
                e, c = f.execution, f.contract
                account["fills"].append({"account": e.acctNumber, "time": e.time.isoformat() if e.time else None,
                                         "symbol": c.symbol, "local": c.localSymbol, "sec_type": c.secType,
                                         "side": e.side, "qty": e.shares, "price": e.price, "order_id": e.orderId,
                                         "mult": _f(c.multiplier) or 1.0,
                                         "commission": f.commissionReport.commission if f.commissionReport and f.commissionReport.commission < 1e8 else 0.0})
        except Exception as e:
            _log(f"account data failed: {e}")
        blob = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "spots": spots, "prev_close": prev, "account": account,
                "acct": acct_data, "stocks": stocks,
                "marks": marks, "missing": missing, "positions": positions, "one_file": path}
        db.set_meta("risk_marks", json.dumps(blob))
        status["last"] = blob["ts"]
        _log(f"marked {len(marks)} contracts, {len(missing)} missing, {len(positions)} IBKR option positions")
        try:
            from . import journal
            journal.snapshot_open()  # each open trade's marked P&L for the journal's P&L path
        except Exception as e:
            _log(f"journal snapshot failed: {e}")
        return {"ok": True, "marked": len(marks), "missing": missing}
    except Exception as e:
        _log(f"refresh failed: {e}")
        return {"error": f"Could not refresh from TWS: {e}"}
    finally:
        if ib is not None:
            ib.disconnect()
        status["running"] = False
        _lock.release()


# ------------------------------------------------------------------ payload for the grid
def _last_session_pnl():
    """(date, {trade key: marked P&L}) at the close of the session before this one, from the desk's own daily marks.
    IBKR's close tick is not used: it is often stale on the far-OTM legs, which put the grid's day $11k off NAV."""
    from .recorder import session_date
    sess = session_date().isoformat()
    try:
        rows = db.query("SELECT date, trade_key, pnl FROM trade_pnl WHERE date=(SELECT MAX(date) FROM trade_pnl WHERE date<?)", (sess,))
    except Exception:
        return None, {}
    return (rows[0]["date"], {r["trade_key"]: r["pnl"] for r in rows}) if rows else (None, {})


def _full_marks():
    """{trade key: (P&L, when)}: each trade's latest P&L this session with every leg priced (journal.snapshot_open writes only those,
    and keeps the 16:15 ET close capture). The Trade plan labels from these when live marks are missing a leg, as of that time."""
    from .recorder import session_date
    try:
        rows = db.query("SELECT trade_key, pnl, updated FROM trade_pnl WHERE date=?", (session_date().isoformat(),))
    except Exception:
        return {}
    return {r["trade_key"]: (r["pnl"], r["updated"]) for r in rows}


def _surface_iv(underlying, expiry, strike):
    """IV at a strike from the latest recorded surface (OTM quotes only), same or nearest expiry."""
    snap = db.query("SELECT id FROM snaps WHERE symbol=? ORDER BY date DESC, id DESC LIMIT 1", (underlying,))
    if not snap:
        return None
    rows = db.query("SELECT expiry, strike, iv FROM quotes WHERE snap_id=? AND iv IS NOT NULL", (snap[0]["id"],))
    if not rows:
        return None
    exps = sorted({r["expiry"] for r in rows}, key=lambda e: abs((dt.datetime.strptime(e, "%Y%m%d") - dt.datetime.strptime(expiry, "%Y%m%d")).days))
    e = exps[0]
    if abs((dt.datetime.strptime(e, "%Y%m%d") - dt.datetime.strptime(expiry, "%Y%m%d")).days) > 10:
        return None
    pts = sorted((r["strike"], r["iv"]) for r in rows if r["expiry"] == e)
    if len(pts) < 2:
        return None
    for edge in (pts[0], pts[-1]):  # just outside the recorded strikes: hold the edge vol flat
        if not (pts[0][0] <= strike <= pts[-1][0]) and abs(strike - edge[0]) <= 0.04 * strike:
            if (strike < pts[0][0]) == (edge is pts[0]):
                return edge[1]
    if not (pts[0][0] <= strike <= pts[-1][0]):
        return None
    for (k1, v1), (k2, v2) in zip(pts, pts[1:]):
        if k1 <= strike <= k2:
            return v1 if k2 == k1 else v1 + (v2 - v1) * (strike - k1) / (k2 - k1)
    return None



def reconcile(trades, positions):
    cfg = load_config()["risk"]
    labels = cfg["account_labels"]
    tol = cfg.get("price_tolerance", {"abs": 0.05, "pct": 0.005})
    one, one_cost, one_names = {}, {}, {}
    for t in trades:
        if not t["ib_account"]:
            continue
        for lg in t["legs"]:
            k = (t["ib_account"], re.sub(r"\s+", " ", lg["symbol"]))
            one[k] = one.get(k, 0) + lg["qty"]
            if lg["open_price"] is not None:
                one_cost[k] = one_cost.get(k, 0) + lg["qty"] * lg["open_price"]
            one_names.setdefault(k, []).append(t["name"])
    ib, ib_px = {}, {}
    for p in positions:
        k = (p["account"], re.sub(r"\s+", " ", p["symbol"]))
        ib[k] = ib.get(k, 0) + p["qty"]
        if p.get("avg_price") is not None:
            ib_px[k] = p["avg_price"]
    accounts = sorted({a for a, _ in one} | {a for a, _ in ib if a in labels})
    today = _todays_fills()
    out = []
    for a in accounts:
        diffs, drift, basis = [], [], []
        for k in sorted({k for k in one if k[0] == a} | {k for k in ib if k[0] == a}):
            o, b = one.get(k, 0), ib.get(k, 0)
            if abs(o - b) > 1e-9:
                diffs.append({"symbol": k[1], "one": o, "ibkr": b, "trades": one_names.get(k, [])})
            elif o and k in one_cost:
                op = one_cost[k] / o
                f = today.get(k)
                # A position built entirely from today's fills is checked against those fills: a difference
                # there is a real recording error. For older positions IBKR's average cost is FIFO (closed lots
                # relieved first in, first out) while ONE carries a moving average, so on any leg scaled into
                # and partly closed the two must differ. Lifetime P&L is the same either way (TWS Matcher's
                # rule, verified against the ONE trade log) -- informational only.
                if f and abs(f["qty"] - o) < 1e-9:
                    bp = f["cost"] / f["qty"]
                    if abs(op - bp) > max(tol["abs"], tol["pct"] * abs(bp)):
                        drift.append({"symbol": k[1], "qty": o, "one_price": round(op, 4), "ibkr_price": round(bp, 4),
                                      "dollars": round((bp - op) * o * 100, 2), "trades": one_names.get(k, [])})
                elif k in ib_px:
                    bp = ib_px[k]
                    if abs(op - bp) > max(tol["abs"], tol["pct"] * abs(bp)):
                        basis.append({"symbol": k[1], "qty": o, "one_price": round(op, 4), "ibkr_price": round(bp, 4),
                                      "trades": one_names.get(k, [])})
        out.append({"account": a, "label": labels.get(a, a), "diffs": diffs, "drift": drift, "basis": basis,
                    "matched": sum(1 for k in one if k[0] == a and abs(one[k] - ib.get(k, 0)) < 1e-9)})
    return out


def _todays_fills():
    """{(account, local symbol): {qty, cost}} for option fills in the current US session (signed: buys +)."""
    try:
        from .accounts import session_date
        rows = db.query("SELECT * FROM executions WHERE sec_type='OPT'")
    except Exception:
        return {}
    sdate = session_date().isoformat()
    out = {}
    for r in rows:
        if not r["time_utc"] or session_date(dt.datetime.fromisoformat(r["time_utc"])).isoformat() != sdate:
            continue
        q = abs(r["qty"]) if r["side"] == "BOT" else -abs(r["qty"])
        k = (r["account"], re.sub(r"\s+", " ", r["local_symbol"] or ""))
        o = out.setdefault(k, {"qty": 0.0, "cost": 0.0})
        o["qty"] += q
        o["cost"] += q * r["price"]
    return out


def one_freshness(path):
    """How old the ONE export is, and whether IBKR has filled anything since: then ONE can't match IBKR."""
    import os
    if not path or not os.path.exists(path):
        return {"stale": True, "age_h": None, "fills_since": 0}
    mt = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - mt).total_seconds() / 3600
    try:
        n = db.query("SELECT COUNT(*) n FROM executions WHERE time_utc > ?", (mt.isoformat(),))[0]["n"]
    except Exception:
        n = 0
    return {"stale": bool(n) or age > 26, "age_h": round(age, 1), "fills_since": n, "exported": mt.isoformat(timespec="minutes")}


def calendar_checks(t, rel, rv20):
    """Each short leg against the nearest later long on the same side: IV at those strikes, forward vol vs RV20
    and the releases the front expiry runs past. Information only: nothing in the plan or size call reads it."""
    from .market import releases_past
    today, out = dt.date.today(), {}
    for s in t["legs"]:
        later = [l for l in t["legs"] if l["qty"] > 0 and l["right"] == s["right"] and l["expiry_iso"] > s["expiry_iso"]]
        if s["qty"] >= 0 or not later:
            continue
        b = min(later, key=lambda l: (abs((l["strike"] or 0) - (s["strike"] or 0)), l["expiry_iso"]))
        fv, bv = (s["mark"] or {}).get("iv"), (b["mark"] or {}).get("iv")
        fd, bd = [(dt.date.fromisoformat(l["expiry_iso"][:10]) - today).days for l in (s, b)]
        fwd = forward_vol(fv, max(fd, 0.5) / 365, bv, bd / 365) if fv and bv else None
        out[(s["strike"], s["right"], s["expiry_iso"])] = {
            "strike": s["strike"], "back_strike": b["strike"], "right": s["right"], "front": s["expiry_iso"][:10], "back": b["expiry_iso"][:10],
            "fdte": fd, "bdte": bd, "front_iv": fv and round(fv * 100, 2), "back_iv": bv and round(bv * 100, 2),
            "spread": round((bv - fv) * 100, 2) if fv and bv else None, "fwd_vol": fwd and round(fwd * 100, 2),
            "fwd_vs_rv": round(fwd * 100 - rv20, 2) if fwd and rv20 else None, **releases_past(rel, s["expiry_iso"][:10])}
    return {"rv20": rv20 and round(rv20, 2), "pairs": sorted(out.values(), key=lambda p: (p["front"], p["strike"]))}


# ------------------------------------------------------------------ gap what-if (same pricing as value() in web/risk.js)
GAPS, VOL_SHIFTS = (-10, -7, -5, -3, -1.5, 1.5, 3, 5, 7, 10), (-3, 0, 3, 6)
COLS = ("joint",) + VOL_SHIFTS  # "joint": IVs move with the index, JOINT points per 1%
JOINT = (1.5, 1.0)  # IV points per 1% move: up this much on a fall, down this much on a rise (the review's joint shock)
MODES = ("strike", "moneyness")  # each strike keeps its IV / the smile slides with the index (recorded SPX/RUT surface)
MODE = "moneyness"  # the default view and the stress check. Recorded surfaces 9 Oct-6 Nov (85-102% of spot, 25-80 DTE): on the 5 falls of
# 1%+ sliding + joint overstated the fixed-strike IV rise by 0.3-0.8 pts, sticky strike + joint by 1.2-3.9 (5 Nov: actual +2.6, 3.2, 6.5);
# on the 4 rises of 1%+ sliding gave the smaller IV drop, the harsher side for a short-vega book.
RUT_BETA = 1.2  # the Risk grid's default


def next_open(now=None):
    """The next 09:30 ET on a trading day: the moment an overnight gap is priced at."""
    from .accounts import US_HOLIDAYS
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    d = now.date()
    while True:
        t = dt.datetime.combine(d, dt.time(9, 30), tzinfo=ET)
        if t > now and d.weekday() < 5 and d.isoformat() not in US_HOLIDAYS:
            return t
        d += dt.timedelta(days=1)


def _legs(t):
    """[(qty, strike, right, vol, expiry)] for a trade with a spot; a leg without a usable IV takes its expiry's average, then 20%."""
    by_exp = {}
    for lg in t["legs"]:
        iv = (lg.get("mark") or {}).get("iv")
        if iv and 0.01 < iv < 3:
            by_exp.setdefault(lg["expiry_iso"], []).append(iv)
    out = []
    for lg in t["legs"]:
        iv = (lg.get("mark") or {}).get("iv")
        alt = by_exp.get(lg["expiry_iso"])
        vol = iv if iv and 0.01 < iv < 3 else (sum(alt) / len(alt) if alt else 0.2)
        out.append((lg["qty"], lg["strike"], lg["right"], vol, dt.datetime.fromisoformat(lg["expiry_iso"])))
    return out


def _value(legs, spot, at, dv=0.0):
    yr = 365 * 86400.0
    return sum(q * 100 * bs_price(spot, k, max(0.0, (x - at).total_seconds() / yr), max(0.01, v + dv), r) for q, k, r, v, x in legs)


def _change(t, legs, x, dv, at, now, moved=None):
    """P&L change from now: spot moved by x, vols by dv, on `at` (a trade expiring sooner is frozen at its first expiry).
    `moved` is the legs with the smile slid to the new spot (sticky moneyness); without it each strike keeps its IV."""
    return _value(moved or legs, t["spot"] * (1 + x), min(at, min(lg[4] for lg in legs)), dv) - _value(legs, t["spot"], now)


def joint_dv(x):
    """IV shift (vol units) that goes with an index move x (a fraction): up JOINT[0] points per 1% on a fall, down JOINT[1] on a rise."""
    return JOINT[0] * -x if x < 0 else -JOINT[1] * x


def _smiles(syms):
    """{sym: {expiry: (strikes, ivs)}} from the latest recorded surface: puts below spot, calls above, one IV per strike."""
    import numpy as np
    out = {}
    for u in syms:
        snap = db.query("SELECT id FROM snaps WHERE symbol=? ORDER BY date DESC, id DESC LIMIT 1", (u,))
        if not snap:
            continue
        pts = {}
        for r in db.query("SELECT expiry, strike, iv FROM quotes WHERE snap_id=? AND iv IS NOT NULL AND iv > 0", (snap[0]["id"],)):
            pts.setdefault(r["expiry"], {}).setdefault(r["strike"], []).append(r["iv"])
        out[u] = {e: (np.array(sorted(p)), np.array([sum(p[k]) / len(p[k]) for k in sorted(p)])) for e, p in pts.items() if len(p) >= 3}
    return out


def _slid(t, legs, x, smiles):
    """The legs with the smile slid to spot × (1 + x): each strike takes the recorded IV at the same distance from spot
    (strike / (1 + x) today), as a change on its own IV. Legs with no recorded smile within 10 days keep their IV."""
    import numpy as np
    sm = smiles.get(t["underlying"]) or {}
    if not sm or not x:
        return legs
    out = []
    for q, k, r, v, xp in legs:
        e = min(sm, key=lambda e: abs((dt.datetime.strptime(e, "%Y%m%d").date() - xp.date()).days))
        if abs((dt.datetime.strptime(e, "%Y%m%d").date() - xp.date()).days) > 10:
            out.append((q, k, r, v, xp))
            continue
        ks, ivs = sm[e]
        out.append((q, k, r, max(0.01, v + float(np.interp(k / (1 + x), ks, ivs) - np.interp(k, ks, ivs))), xp))
    return out


def gap_grid(trades, labels, futures=None, now=None, beta=RUT_BETA, smiles=None):
    """Book at the next open for each gap and IV shift, in total and per account, with each strike keeping its IV ("strike") and with
    the smile sliding with the index ("moneyness"). Rows are SPX gaps with RUT at beta × that; the `Futures` row uses each index's own
    overnight move (None when there's no quote). Column "joint" moves IVs with the index (joint_dv); the others shift every leg's IV."""
    now = now or dt.datetime.now(dt.timezone.utc)
    at = next_open(now)
    book = [(t, labels.get(t["ib_account"]) or t["group"], _legs(t)) for t in trades if t.get("spot") and t["legs"]]
    fut = (futures or {}).get("chg") or {}
    if smiles is None:
        smiles = _smiles(sorted({t["underlying"] for t, _, _ in book} & {"SPX", "RUT"}))

    R = []  # falls, then where futures are now, then rises
    for g in GAPS:
        if g > 0 and fut and not any(r["live"] for r in R):
            R.append({"label": "Futures now", "gap": None, "live": True})
        R.append({"label": f"{g:+.1f}%", "gap": g, "live": False})

    def move(t, r):
        if r["live"]:
            return fut.get(t["underlying"], fut.get("SPX", 0.0)) / 100
        return r["gap"] / 100 * (beta if t["underlying"] == "RUT" else 1)

    def cells(tt, mode):
        res = []
        for r in R:
            row = [0.0] * len(COLS)
            for t, _, lg in tt:
                x = move(t, r)
                moved = _slid(t, lg, x, smiles) if mode == "moneyness" else None
                for j, c in enumerate(COLS):
                    row[j] += _change(t, lg, x, joint_dv(x) if c == "joint" else c / 100, at, now, moved)
            res.append(row)
        return res
    names = sorted({a for _, a, _ in book})
    grids = {m: {"total": cells(book, m), "accounts": [{"label": a, "cells": cells([b for b in book if b[1] == a], m)} for a in names]} for m in MODES}
    slid = sorted({t["underlying"] for t, _, _ in book if smiles.get(t["underlying"])})
    return {"at": at.isoformat(), "rows": [r["label"] for r in R], "gaps": [r["gap"] for r in R], "vols": list(COLS), "joint": list(JOINT), "beta": beta,
            "futures": fut or None, "futures_ts": (futures or {}).get("ts"), "slid": slid, "mode": MODE, **grids[MODE], "modes": grids}


JUMPS = (1.5, 3, 4, 5, 7, 10)  # one-session SPX moves counted, %


def jump_freq(vix=None, since="1990-01-02"):
    """How often SPX has moved at least this much in one session, close to close, since 1990, each way: on all days, on days that began
    with the VIX at or below `vix` (the prior close), and what a normal curve at that VIX would expect. Closes, not overnight gaps."""
    from statistics import NormalDist
    from .history import series
    px = [(r["date"], r["c"]) for r in db.query("SELECT date, c FROM bars_daily WHERE symbol='^GSPC' AND date>=? AND c>0 ORDER BY date", (since,))]
    if len(px) < 500:
        return None
    vx = series("VIX", since).to_dict()
    days = [(d, c / p - 1, vx.get(pd)) for (pd, p), (d, c) in zip(px, px[1:])]
    years = len(days) / 252
    calm = [x for x in days if vix and x[2] is not None and x[2] <= vix]
    sd = vix / 100 / 252 ** 0.5 if vix else None
    rows = []
    for t in JUMPS:
        side = {}
        for k, hit in (("down", lambda r: r <= -t / 100), ("up", lambda r: r >= t / 100)):  # noqa: E731
            all_ = [d for d, r, _ in days if hit(r)]
            low = [d for d, r, _ in calm if hit(r)]
            side[k] = {"n": len(all_), "per_yr": round(len(all_) / years, 2), "last": all_[-1] if all_ else None,
                       "calm_n": len(low) if vix else None, "calm_per_yr": round(len(low) / (len(calm) / 252), 2) if calm else None,
                       "normal_per_yr": 252 * NormalDist().cdf(-t / 100 / sd) if sd else None}
        rows.append({"pct": t, **side})
    return {"since": px[0][0], "to": px[-1][0], "years": round(years, 1), "vix": vix, "calm_days": len(calm), "rows": rows}


def limits(trades, labels, book, gaps, cfg=None):
    """Each account's open book against the A14 rule page (ids per ticker, worst case an id) and against the stress limit: the loss on a
    day the index moves `move` % either way with IVs moving with it (the Gap what-if's joint column in its default MODE), as % of
    NAV. Both limits are personal (config.local.json risk.stress: limit_pct for the stress day, cap_pct for all A14 worst cases added up; one
    number or {label: number}); unset, the figure is shown, not alerted. "over" marks an account past either: no new id fits until it is back under.
    Information only: nothing here closes, blocks or sizes anything."""
    from . import a14rules
    cfg = (load_config()["risk"].get("stress") or {}) if cfg is None else cfg
    move, lim, capw = float(cfg.get("move") or 5), cfg.get("limit_pct"), cfg.get("cap_pct")
    navs = {m["label"]: m["nav"] / m["rate"] for m in (book or {}).get("margin") or [] if m.get("nav") and m.get("rate")}
    rule = a14rules.book([{**t, "acct": labels.get(t["ib_account"]) or t["group"]} for t in trades], navs)
    gi = {g: i for i, g in enumerate(gaps.get("gaps") or []) if g is not None}
    j = (gaps.get("vols") or []).index("joint") if "joint" in (gaps.get("vols") or []) else None
    strike = {x["label"]: x["cells"] for x in ((gaps.get("modes") or {}).get("strike") or {}).get("accounts") or []}
    out = []
    for acc in gaps.get("accounts") or []:
        a, nav = acc["label"], navs.get(acc["label"])
        cell = lambda g, c=acc["cells"]: c[gi[g]][j] if g in gi and j is not None else None  # noqa: E731
        worst = lambda c: -min(v for v in (cell(-move, c), cell(move, c), 0.0) if v is not None)  # noqa: E731
        down, up = cell(-move), cell(move)
        pct = round(100 * worst(acc["cells"]) / nav, 1) if nav else None
        hard = round(100 * worst(strike[a]) / nav, 1) if nav and a in strike and gaps.get("mode") != "strike" else None  # each strike keeping its IV
        cap = lim.get(a) if isinstance(lim, dict) else lim
        r = rule.get(a) or {}
        alerts = list(r.get("alerts") or [])
        if cap is not None and pct is not None and pct > cap:
            alerts.append(f"a {move:g}% day with IVs moving with it would cost {pct:.1f}% of NAV, over your {cap:g}% limit")
        tot, wp = (capw.get(a) if isinstance(capw, dict) else capw), r.get("worst_pct")
        if tot is not None and r and (wp is None or wp > tot):  # None with ids open: an id has no ceiling
            alerts.append(f"all A14 worst cases add to {wp:.1f}% of NAV, over your {tot:g}% cap" if wp is not None else f"an A14 id has no ceiling: over your {tot:g}% cap")
        over = bool((cap is not None and pct is not None and pct > cap) or (tot is not None and r and (wp is None or wp > tot)))
        out.append({"label": a, "nav_usd": round(nav) if nav else None, "a14": r or None, "stress": {"move": move, "down": down, "up": up, "pct": pct, "limit": cap,
                    "ten": [cell(-10.0), cell(10.0)], "mode": gaps.get("mode") or "strike", "strike_pct": hard}, "cap": tot, "over": over, "alerts": alerts})
    return out


def overnight_risk(trades, vix, now=None):
    """Book gamma and the ±2σ overnight P&L: a one-day move from the VIX, repriced at the next open with IVs unchanged."""
    now = now or dt.datetime.now(dt.timezone.utc)
    at = next_open(now)
    book = [(t, _legs(t)) for t in trades if t.get("spot") and t["legs"]]
    if not book or not vix:
        return None
    sd = vix / 100 / 365 ** 0.5
    gamma = 0.0  # $ the book loses (short gamma) or makes to a 1% move, beyond its delta: ½Γ(1% of spot)²
    for t, lg in book:
        s, h = t["spot"], t["spot"] * 0.001
        gamma += 0.5 * (_value(lg, s + h, now) - 2 * _value(lg, s, now) + _value(lg, s - h, now)) / (h * h) * (0.01 * s) ** 2
    out = lambda k: sum(_change(t, lg, k * sd * (RUT_BETA if t["underlying"] == "RUT" else 1), 0.0, at, now) for t, lg in book)  # noqa: E731
    return {"gamma_1pct": gamma, "sd_pct": 100 * sd, "down2": out(-2), "up2": out(2), "at": at.isoformat(), "vix": vix}


def hedge_reference(spot=None):
    """A reference price for a short-dated SPX put spread, 2% and 4% under spot, from the last recorded surface: the first
    expiry 3+ days out. Asks on the long, bids on the short. A price to look at, with no size and no recommendation."""
    snap = db.query("SELECT id, spot, ts FROM snaps WHERE symbol='SPX' ORDER BY date DESC, id DESC LIMIT 1")
    if not snap:
        return None
    s = spot or snap[0]["spot"]
    rows = db.query("SELECT expiry, dte, strike, bid, ask, mid FROM quotes WHERE snap_id=? AND right='P' AND dte>=3 AND dte<=21 ORDER BY dte, strike", (snap[0]["id"],))
    if not rows or not s:
        return None
    exp = rows[0]["expiry"]
    q = [r for r in rows if r["expiry"] == exp and r["bid"] is not None and r["ask"] is not None and r["ask"] > 0]
    if len(q) < 2:
        return None
    near = lambda x: min(q, key=lambda r: abs(r["strike"] - x))  # noqa: E731
    lng, sht = near(s * 0.98), near(s * 0.96)
    if lng["strike"] <= sht["strike"]:
        return None
    return {"expiry": exp, "dte": round(lng["dte"]), "long": lng["strike"], "short": sht["strike"], "cost": lng["ask"] - sht["bid"], "mid": (lng["mid"] or 0) - (sht["mid"] or 0), "ts": snap[0]["ts"]}


def _book(m, spots, labels):
    """Inputs for the book what-if: vol indexes, and margin per account from the last TWS read, keyed by label."""
    from .history import series
    start = (dt.date.today() - dt.timedelta(days=14)).isoformat()
    last = lambda sym: next((float(v) for v in series(sym, start).iloc[::-1]), None)
    rate = (m.get("acct") or {}).get("usd_rate") or {}
    margin = [{"label": labels[a], "nav": v.get("NetLiquidation"), "excess": v.get("ExcessLiquidity"), "available": v.get("AvailableFunds"),
               "maint": v.get("MaintMarginReq"), "currency": v.get("currency"), "rate": rate.get(a)}
              for a, v in ((m.get("account") or {}).get("summary") or {}).items() if a in labels]
    return {"vix": last("VIX"), "rvx": last("RVX"), "spx": spots.get("SPX") or last("SPX"), "margin": sorted(margin, key=lambda x: x["label"])}


def payload():
    trades, path = load_open_trades()
    raw = db.get_meta("risk_marks")
    m = json.loads(raw) if raw else {"marks": {}, "spots": {}, "positions": [], "ts": None, "missing": []}
    marks, spots = m["marks"], m["spots"]
    for t in trades:
        t["spot"] = spots.get(t["underlying"])
        for lg in t["legs"]:
            mk = marks.get(lg["symbol"])
            lg["mark"] = mk
            occ = lg["occ"] or {}
            # expiry moment: AM-settled standard monthlies at the open, everything else at the close
            exp = dt.datetime.strptime(lg["one_expiry"], "%d/%m/%Y")
            am = occ.get("root") in AM_ROOTS
            lg["expiry_iso"] = exp.strftime("%Y-%m-%d") + ("T09:30:00-04:00" if am else "T16:00:00-04:00")
            lg["strike"] = occ.get("strike")
            if mk:
                mk["iv_src"] = "TWS" if mk.get("iv") else None
                itm = t["spot"] and lg["strike"] and ((lg["right"] == "P" and lg["strike"] > t["spot"]) or (lg["right"] == "C" and lg["strike"] < t["spot"]))
                # TWS model IVs on in-the-money index options are unreliable: use the recorded OTM surface
                sv = _surface_iv(t["underlying"], exp.strftime("%Y%m%d"), lg["strike"]) if itm and t["underlying"] in ("SPX", "RUT") else None
                if sv:
                    mk["iv"], mk["iv_src"] = sv, "surface"
                elif mk.get("iv") is None and mk.get("mid") and t["spot"] and lg["strike"]:
                    tt = max((exp - dt.datetime.now()).days, 0.5) / 365
                    mk["iv"] = implied_vol(mk["mid"], t["spot"], lg["strike"], tt, lg["right"])
                    mk["iv_src"] = "from mid" if mk["iv"] else None
    recon = reconcile(trades, m.get("positions", [])) if m.get("positions") else []
    adj, adj_ts = adjustment_counts()
    last_date, last_pnl = _last_session_pnl()
    full = _full_marks()
    for t in trades:
        t["full_pnl"], t["full_at"] = full.get(t["id"], (None, None))
        t["prev_spot"] = m.get("prev_close", {}).get(t["underlying"])
        t["strategy"] = classify(t["group"], t["name"])
        t["entry_spot"] = _entry_spot(t["underlying"], t["opened"])
        t["adjustments"] = adj.get(t["id"])
        try:
            t["opened_iso"] = _local_dt(t["opened"]).isoformat()
        except Exception:
            t["opened_iso"] = None
        t["last_pnl"] = last_pnl.get(t["id"])
        t["new_since_close"] = t["last_pnl"] is None and bool(last_date) and (t["opened_iso"] or "")[:10] > last_date
    cal = [t for t in trades if t["strategy"] in CALENDAR_FAMILY]
    if cal:
        from .analytics import realized
        from .market import releases
        rel = releases()
        for t in cal:
            t["calendar"] = calendar_checks(t, rel, realized(t["underlying"]))
    labels = load_config()["risk"]["account_labels"]
    book = _book(m, spots, labels)
    from . import a14rules, heads
    gaps = gap_grid(trades, labels, heads.gaps_now())
    lims = limits(trades, labels, book, gaps)
    from . import process
    process.snap_day(lims)  # which accounts were over your limits this session, for the automatic log
    return {"trades": trades, "one_file": path, "one_fresh": one_freshness(path), "marks_ts": m.get("ts"), "spots": spots, "stocks": m.get("stocks", []),
            "missing": m.get("missing", []), "recon": recon, "status": status, "detail_exported": adj_ts, "a14rule": a14rules.rule(),
            "labels": labels, "book": book, "gaps": gaps, "limits": lims, "jumps": jump_freq(book["vix"]),
            "overnight": overnight_risk(trades, book["vix"]), "hedge": hedge_reference(book["spx"])}


def recon_view():
    """Reconciliation page data: per-account recon, stock holdings, and recent fills matched to ONE trades."""
    from . import accounts
    pl = payload()
    trades = pl["trades"]
    labels = pl["labels"]
    diff_keys = {(r["account"], d["symbol"]) for r in pl["recon"] for d in r["diffs"]}
    by_contract, by_und_exp = {}, {}
    for t in trades:
        for lg in t["legs"]:
            by_contract.setdefault((t["ib_account"], re.sub(r"\s+", " ", lg["symbol"])), []).append(t["name"])
            by_und_exp.setdefault((t["ib_account"], t["underlying"], lg["one_expiry"]), []).append(t["name"])
    fills = []
    for f in accounts.fills(days=7):
        sym = re.sub(r"\s+", " ", f["local_symbol"] or "")
        names = by_contract.get((f["account"], sym), [])
        if not names and f["expiry"]:
            try:
                exp = dt.datetime.strptime(f["expiry"], "%Y%m%d")
                if f["trading_class"] in AM_ROOTS and exp.weekday() == 3:
                    exp += dt.timedelta(days=1)  # IBKR last-trade Thursday -> Friday expiration
                names = by_und_exp.get((f["account"], f["symbol"], exp.strftime("%d/%m/%Y")), [])
            except ValueError:
                pass
        status = "not in ONE" if (f["account"], sym) in diff_keys else ("in ONE" if names else "closed / not open in ONE")
        fills.append({**f, "label": labels.get(f["account"], f["account"]), "one_trades": sorted(set(names)), "status": status, "zones": two_zones(f["time_utc"]) if f["time_utc"] else None})
    return {"recon": pl["recon"], "stocks": pl["stocks"], "fills": fills, "labels": labels,
            "marks_ts": pl["marks_ts"], "one_file": pl["one_file"], "one_fresh": pl["one_fresh"]}
