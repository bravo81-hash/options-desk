"""Open positions for the risk-graph grid.

Trades and legs come from the newest ONE Summary Report (ONE knows which legs form a trade).
Marks (mid, IV) and underlying prices come from TWS, read-only, on their own client id.
A reconciliation compares ONE's open legs with IBKR positions per mapped account.
Risk curves are computed in the browser from these inputs.
"""
import asyncio
import csv
import datetime as dt
import json
import logging
import re
import threading

from . import db, load_config
from .trades import _newest, classify
from .volmath import implied_vol

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
    cfg = load_config()
    path = path or _newest(cfg["trade_files"]["one_glob"])
    if not path:
        return [], None
    amap = cfg["risk"]["account_map"]
    trades, cur = [], None
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.reader(fh):
            if len(r) > 15 and r[0] == "" and r[2] in ("Open", "Closed", "Expired") and r[1]:
                cur = None
                if r[2] != "Open" or r[1].lower().startswith("backtest"):
                    continue
                grp = _one_group(r[1])
                cur = {"id": f"{r[1]}#{r[6]}", "account": r[1], "group": grp, "ib_account": amap.get(grp),
                       "underlying": r[3], "expiration": r[4], "trade_id": r[6], "name": r[7],
                       "opened": r[8], "dte": _f(r[10]), "dit": _f(r[11]), "margin": _f(r[12]),
                       "comms": _f(r[13]), "one_pnl": _f(r[14]), "one_pnl_pct": _f(r[15]),
                       "realized": 0.0, "legs": []}
                trades.append(cur)
            elif cur and len(r) >= 14 and r[0] == "" and r[1] == "" and r[2] == cur["account"] and r[3] == cur["trade_id"]:
                qty = _f(r[6]) or 0
                sign = -1 if r[5].strip().lower() == "sell" else 1
                closed = len(r) > 14 and r[14].strip() != ""
                if closed:
                    cur["realized"] += _f(r[-1]) or 0.0
                    continue
                occ = parse_occ(r[7])
                ib_sym = _ib_symbol(occ, r[8]) if occ else r[7].strip()
                cur["legs"].append({"symbol": ib_sym, "one_symbol": r[7].strip(), "occ": occ, "qty": sign * qty, "open_price": _f(r[12]),
                                    "commission": _f(r[13]) or 0.0, "one_expiry": r[8], "right": r[9][:1].upper(),
                                    "desc": r[10], "underlying": r[11]})
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


_adj_cache = {}


def adjustment_counts():
    """{account#trade_id: adjustments} from the newest ONE Detail Report (every fill, timestamped): fills within
    15 minutes are one event; the first event is the entry, every later one an adjustment. None if no report."""
    import os
    path = _newest(load_config()["trade_files"].get("one_detail_glob", []))
    if not path:
        return {}, None
    key = (path, os.path.getmtime(path))
    if key in _adj_cache:
        return _adj_cache[key]
    times, cur = {}, None
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.reader(fh):
            if len(r) > 15 and r[0] == "" and r[2] in ("Open", "Closed", "Expired") and r[1]:
                cur = f"{r[1]}#{r[6]}" if r[2] == "Open" else None
                if cur:
                    times[cur] = []
            elif cur and len(r) > 13 and r[0] == "" and r[1] == "" and r[5] in ("Buy", "Sell"):
                t = _local_dt(r[4])
                if t:
                    times[cur].append(t)
    out = {}
    for k, ts in times.items():
        ev, last = 0, None
        for t in sorted(ts):
            if last is None or (t - last).total_seconds() >= 900:
                ev += 1
            last = t
        out[k] = max(ev - 1, 0)
    exported = dt.datetime.fromtimestamp(key[1]).isoformat(timespec="minutes")
    _adj_cache.clear()
    _adj_cache[key] = (out, exported)
    return out, exported


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
            for f in ib.reqExecutions():
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
    for t in trades:
        t["prev_spot"] = m.get("prev_close", {}).get(t["underlying"])
        t["strategy"] = classify(t["group"], t["name"])
        t["entry_spot"] = _entry_spot(t["underlying"], t["opened"])
        t["adjustments"] = adj.get(t["id"])
        try:
            t["opened_iso"] = _local_dt(t["opened"]).isoformat()
        except Exception:
            t["opened_iso"] = None
    return {"trades": trades, "one_file": path, "one_fresh": one_freshness(path), "marks_ts": m.get("ts"), "spots": spots, "stocks": m.get("stocks", []),
            "missing": m.get("missing", []), "recon": recon, "status": status, "detail_exported": adj_ts,
            "labels": load_config()["risk"]["account_labels"]}


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
        fills.append({**f, "label": labels.get(f["account"], f["account"]), "one_trades": sorted(set(names)), "status": status})
    return {"recon": pl["recon"], "stocks": pl["stocks"], "fills": fills, "labels": labels,
            "marks_ts": pl["marks_ts"], "one_file": pl["one_file"], "one_fresh": pl["one_fresh"]}
