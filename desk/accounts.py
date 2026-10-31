"""Account P&L, executions and ONE-import files (folded in from TWS Matcher).

* account_daily: one row per US session and account: NAV and IBKR's own daily P&L (reqPnL).
  Seeded once from TWS Matcher's nav_history.json, then recorded by this app. IBKR's official NAV replaces a day
  once its Flex statement is out (flex.py).
* executions: every fill TWS returns, de-duplicated by IBKR execution id, kept indefinitely.
* pnl_today: IBKR daily P&L per contract (reqPnLSingle), aggregated by ticker.
* ONE import CSV per account in the IBKR Flex format ONE reads (same format TWS Matcher wrote).

Read-only: market-data, P&L and execution requests only.
"""
import csv
import datetime as dt
import io
import json
import os
from zoneinfo import ZoneInfo

from . import db, load_config

ET = ZoneInfo("America/New_York")
LOCAL_TZ = ZoneInfo("Australia/Sydney")
NAV_HISTORY = os.path.expanduser("~/Downloads/TWS Matcher/nav_history.json")


def init():
    db.write("""CREATE TABLE IF NOT EXISTS account_daily (date TEXT, account TEXT, nav REAL, daily_pnl REAL,
                currency TEXT, source TEXT, updated TEXT, PRIMARY KEY (date, account))""")
    db.write("""CREATE TABLE IF NOT EXISTS executions (exec_id TEXT PRIMARY KEY, account TEXT, time_utc TEXT,
                local_symbol TEXT, sec_type TEXT, symbol TEXT, trading_class TEXT, expiry TEXT, strike REAL,
                right TEXT, side TEXT, qty REAL, price REAL, mult REAL, commission REAL, order_id INTEGER, perm_id INTEGER)""")
    db.write("CREATE TABLE IF NOT EXISTS flex_flows (id TEXT PRIMARY KEY, date TEXT, account TEXT, amount REAL, kind TEXT)")


def _num(x):
    try:
        v = float(x)
        return v if v == v and abs(v) < 1e300 else None
    except (TypeError, ValueError):
        return None


def import_tws_matcher_history(path=NAV_HISTORY):
    """One-off seed from TWS Matcher. Older entries without a per-account split use the NAV change."""
    init()
    if db.get_meta("nav_import_done") == "2" or not os.path.exists(path):
        return 0
    rows = json.load(open(path, encoding="utf-8"))
    rows.sort(key=lambda r: r["date"])
    # TWS Matcher stamps the US calendar date of the capture; a weekend capture still holds Friday's
    # session, so map it to Friday and keep it only when Friday has no capture of its own.
    # A weekend capture is the later reading, taken after IBKR's final marks, so it replaces Friday's.
    byd = {}
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        if d.weekday() >= 5:
            r = dict(r, date=(d - dt.timedelta(days=d.weekday() - 4)).isoformat())
        byd[r["date"]] = r
    rows = [byd[k] for k in sorted(byd)]
    out, prev = [], {}
    for r in rows:
        accts = r.get("accounts", {})
        split = r.get("daily_pnl_by_account") or {}
        for a, nav in accts.items():
            pnl = split.get(a)
            src = "TWS Matcher (IBKR daily P&L)"
            if pnl is None and a in prev:
                pnl, src = nav - prev[a], "TWS Matcher (NAV change)"
            out.append((r["date"], a, nav, pnl, r.get("currency", "AUD"), src, r["date"]))
            prev[a] = nav
    db.write("DELETE FROM account_daily WHERE source LIKE 'TWS Matcher%'")
    db.write("INSERT OR IGNORE INTO account_daily VALUES (?,?,?,?,?,?,?)", out, many=True)
    db.set_meta("nav_import_done", "2")
    return len(out)


def session_date(now=None):
    from .recorder import session_date as sd
    return sd(now)


def collect(ib, positions_raw, marks=None):
    """Called while connected (from risk.refresh_marks). Returns a dict stored with the marks."""
    init()
    cfg = load_config()["risk"]
    accounts = sorted({p.account for p in positions_raw} | set(cfg["account_labels"]))
    accounts = [a for a in accounts if not a.startswith("F")]  # skip the FA master aggregate
    # account values (NAV) in base currency
    nav, cur, usd_rate = {}, {}, {}
    for v in ib.accountValues():
        if v.tag == "ExchangeRate" and v.currency == "USD" and _num(v.value):
            usd_rate[v.account] = _num(v.value)  # base currency per USD
        if v.tag == "NetLiquidation" and v.account in accounts and v.currency not in ("", "BASE") and not getattr(v, "modelCode", ""):
            nav[v.account] = _num(v.value)
            cur[v.account] = v.currency
    if not usd_rate:
        try:
            from ib_async import Forex
            fx = Forex("AUDUSD")
            ib.qualifyContracts(fx)
            tk = ib.reqMktData(fx, "", True, False)
            for _ in range(15):
                ib.sleep(0.3)
                if _num(tk.bid) and _num(tk.ask):
                    break
            mid = (tk.bid + tk.ask) / 2 if _num(tk.bid) and _num(tk.ask) else _num(tk.close)
            if mid:
                usd_rate = {a: 1.0 / mid for a in accounts if (cur.get(a) or "AUD") == "AUD"}
        except Exception:
            pass
    # broker daily P&L per account
    subs = {a: ib.reqPnL(a) for a in accounts}
    ib.sleep(3)
    daily = {}
    for a, p in subs.items():
        daily[a] = {"daily": _num(p.dailyPnL), "unrealized": _num(p.unrealizedPnL), "realized": _num(p.realizedPnL)}
        ib.cancelPnL(a)
    # executions -> journal
    fills = todays_fills(ib)
    rows = []
    for f in fills:
        e, c = f.execution, f.contract
        cr = f.commissionReport
        comm = cr.commission if cr and cr.commission and cr.commission < 1e8 else None  # 0.0 = no report yet
        rows.append((e.execId, e.acctNumber, e.time.astimezone(dt.timezone.utc).isoformat() if e.time else None,
                     c.localSymbol, c.secType, c.symbol, c.tradingClass, c.lastTradeDateOrContractMonth,
                     _num(c.strike), c.right, e.side, _num(e.shares), _num(e.price), _num(c.multiplier) or 1.0,
                     comm, e.orderId, e.permId))
    if rows:
        db.write("""INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(exec_id) DO UPDATE SET commission=COALESCE(excluded.commission, executions.commission)""", rows, many=True)
    # per-contract market value (reqPnLSingle.value), so the day's P&L by ticker can be marked to market:
    # value now - value at the last session's close + cash from today's fills. IBKR's own per-contract
    # daily P&L is kept for reference only (outside the session it reports nonsense, e.g. +$22k on a Sunday).
    sdate = session_date().isoformat()
    con = {}
    for p in positions_raw:
        if p.account in accounts and p.position:
            con[(p.account, p.contract.conId)] = {"symbol": p.contract.symbol, "sec_type": p.contract.secType, "open": True,
                                                  "local": p.contract.localSymbol, "qty": p.position,
                                                  "mult": _num(p.contract.multiplier) or 1.0, "cur": p.contract.currency, "contract": p.contract}
    cash, fill_qty = {}, {}
    for f in fills:
        k = (f.execution.acctNumber, f.contract.conId)
        if k[0] not in accounts or not f.execution.time or f.contract.secType == "BAG":  # a combo's own row repeats its legs
            continue
        if session_date(f.execution.time).isoformat() != sdate:
            continue
        if k not in con:
            con[k] = {"symbol": f.contract.symbol, "sec_type": f.contract.secType, "open": False, "local": f.contract.localSymbol,
                      "cur": f.contract.currency}
        mult = _num(f.contract.multiplier) or 1.0
        sign = -1.0 if f.execution.side == "BOT" else 1.0
        cr = f.commissionReport
        comm = cr.commission if cr and cr.commission is not None and cr.commission < 1e8 else 0.0
        cash[k] = cash.get(k, 0.0) + sign * f.execution.shares * f.execution.price * mult - comm
        fill_qty[k] = fill_qty.get(k, 0.0) - sign * f.execution.shares
    values, ib_daily = {}, {}
    keys = list(con)
    for i in range(0, len(keys), 60):
        batch = keys[i:i + 60]
        ps = {k: ib.reqPnLSingle(k[0], "", k[1]) for k in batch}
        for _ in range(30):  # wait until every contract has a value (up to ~9 s); a partial capture skews the day
            ib.sleep(0.3)
            if all(_num(p.value) is not None for k, p in ps.items() if con[k]["open"]):
                break
        for k, p in ps.items():
            values[k] = _num(p.value) if con[k]["open"] else 0.0
            # own valuation from the TWS marks (qty x mid x multiplier) where available: complete and consistent;
            # IBKR's per-contract value is patchy outside market hours
            mk = (marks or {}).get(con[k]["local"]) if con[k]["open"] else None
            if mk and mk.get("mid") is not None:
                values[k] = con[k]["qty"] * mk["mid"] * con[k]["mult"]
            ib_daily[k] = _num(p.dailyPnL)
            ib.cancelPnLSingle(k[0], "", k[1])
    now_s = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    db.write("""CREATE TABLE IF NOT EXISTS contract_values (date TEXT, account TEXT, con_id INTEGER, local_symbol TEXT,
                symbol TEXT, value REAL, updated TEXT, PRIMARY KEY (date, account, con_id))""")
    from .recorder import close_capture
    db.write("DELETE FROM contract_values WHERE date=? AND updated<?", (sdate, close_capture(sdate)))
    db.write("INSERT OR IGNORE INTO contract_values VALUES (?,?,?,?,?,?,?)",
             [(sdate, k[0], k[1], con[k]["local"], con[k]["symbol"], v, now_s) for k, v in values.items() if v is not None and con[k]["open"]], many=True)
    prev_date = db.query("SELECT MAX(date) d FROM contract_values WHERE date<?", (sdate,))[0]["d"]
    prev = {(r["account"], r["con_id"]): r for r in db.query("SELECT * FROM contract_values WHERE date=?", (prev_date,))} if prev_date else {}
    for k, r in prev.items():  # held at the last close, gone now without a fill today (expired / assigned)
        if k not in con and k[0] in accounts:
            con[k] = {"symbol": r["symbol"], "sec_type": "", "open": False, "local": r["local_symbol"]}
            values[k] = 0.0
    by_ticker = {}
    for k, info in con.items():
        t = by_ticker.setdefault(k[0], {}).setdefault(info["symbol"], {"daily": 0.0 if prev_date else None, "ibkr": 0.0, "contracts": 0,
                                                                          "missing": 0, "open": 0, "closed": 0})
        t["contracts"] += 1
        t["open" if info["open"] else "closed"] += 1
        t["ibkr"] += ib_daily.get(k) or 0.0
        v = values.get(k)
        opened_today = k in fill_qty and abs(fill_qty[k] - (info.get("qty") or 0)) < 1e-9
        if v is None or (prev_date is not None and k not in prev and not opened_today):
            # no value now, or not valued at the last close and not opened entirely today:
            # comparing against nothing would book its whole value as profit
            t["missing"] += 1
        elif prev_date is not None:
            before = prev[k]["value"] if k in prev else 0.0
            rate = (usd_rate.get(k[0]) or next(iter(usd_rate.values()), None) or 1.0) if (info.get("cur") or "USD") == "USD" else 1.0
            t["daily"] += (v - before + cash.get(k, 0.0)) * rate
    # contract values and fill cash are in USD; NAV is in the account's base currency (AUD): convert
    # (conversion is applied per contract above, by its own currency)
    # today's row in the daily table. Only written during or after a US session (weekday, from 9:30 ET):
    # IBKR's daily P&L resets overnight, so a weekend or pre-open reading must not overwrite a finished day.
    # Re-written on every refresh that day; the 16:15 ET capture is the final one.
    et_now = dt.datetime.now(ET)
    in_session_day = et_now.weekday() < 5 and (et_now.hour, et_now.minute) >= (9, 30)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if in_session_day:
        db.write("INSERT OR REPLACE INTO account_daily VALUES (?,?,?,?,?,?,?)",
                 [(sdate, a, nav.get(a), daily.get(a, {}).get("daily"), cur.get(a), "Options Desk", now)
                  for a in accounts if nav.get(a) is not None], many=True)
    else:
        # overnight/weekend: nothing trades, but IBKR keeps settling the closing marks, so refresh that
        # session's NAV (never its IBKR daily figure, which resets overnight)
        db.write("UPDATE account_daily SET nav=?, updated=? WHERE date=? AND account=? AND source<>'IBKR Flex'",
                 [(nav[a], now, sdate, a) for a in accounts if nav.get(a) is not None], many=True)
        if sdate not in US_HOLIDAYS:  # session missed entirely (laptop asleep): record its closing NAV now
            db.write("INSERT OR IGNORE INTO account_daily VALUES (?,?,?,?,?,?,?)",
                     [(sdate, a, nav[a], None, cur.get(a), "Options Desk (after-hours)", now) for a in accounts if nav.get(a) is not None], many=True)
    prior = last_close_nav(sdate)
    change = {a: nav[a] - prior[a]["nav"] for a in accounts if nav.get(a) is not None and a in prior and prior[a]["nav"]}
    return {"nav": nav, "currency": cur, "daily": daily, "by_ticker": by_ticker, "session": sdate,
            "nav_change": change, "prior": prior, "marks_since": prev_date, "usd_rate": usd_rate}


# ------------------------------------------------------------------ weekly grid
US_HOLIDAYS = {  # NYSE full-day closures
    "2025-11-27", "2025-12-25", "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}

def _cash_flows():
    """Deposits/withdrawals in base currency. The TWS API does not report them: they come from IBKR Flex wherever a
    statement covers the date, otherwise from config (risk.cash_flows: [{date, account, amount}])."""
    from . import flex
    lo, hi = flex.covered()
    out = {}
    for f in load_config()["risk"].get("cash_flows", []):
        if not lo <= f["date"] <= hi:
            k = (f["date"], f["account"])
            out[k] = out.get(k, 0.0) + float(f["amount"])
    for r in db.query("SELECT date, account, amount FROM flex_flows"):
        k = (r["date"], r["account"])
        out[k] = out.get(k, 0.0) + r["amount"]
    return out


def _on_nav_days(flows, byday):
    """A flow on a day with no NAV reading lands on the account's next reading, or it would count as profit."""
    out, days = {}, sorted(byday)
    for (d, a), v in flows.items():
        nxt = next((x for x in days if x >= d and a in byday[x]), None)
        if nxt:
            out[(nxt, a)] = out.get((nxt, a), 0.0) + v
    return out


def weekly(weeks=53):
    """P&L = change in net liquidation value between recorded sessions (less any configured deposits).

    IBKR's own daily P&L (reqPnL) is kept for reference only: summed over days it overstated this book's
    growth roughly threefold (it values each day against the previous day's official option closes, which are
    often stale for the far-OTM SPX/RUT puts in the BWBs). NAV is what the account is actually worth.
    """
    init()
    rows = db.query("SELECT * FROM account_daily ORDER BY date")
    labels = load_config()["risk"]["account_labels"]
    accts = sorted({r["account"] for r in rows}, key=lambda a: labels.get(a, a))
    byday = {}
    for r in rows:
        byday.setdefault(r["date"], {})[r["account"]] = r
    flows = _on_nav_days(_cash_flows(), byday)
    days = sorted(byday)
    wk = {}
    prev = {}  # account -> (date, nav) of the last recorded session
    for d in days:
        dd = dt.date.fromisoformat(d)
        monday = (dd - dt.timedelta(days=dd.weekday())).isoformat()
        w = wk.setdefault(monday, {"week": monday, "days": [], "acct": {}})
        w["days"].append(d)
        for a in accts:
            r = byday[d].get(a)
            if not r or r["nav"] is None:
                continue
            p = prev.get(a)
            flow = flows.get((d, a), 0.0)
            pnl = r["nav"] - p[1] - flow if p else None
            c = w["acct"].setdefault(a, {"pnl": 0.0, "start_nav": p[1] if p else None, "end_nav": None, "daily": [],
                                         "ibkr": 0.0, "flows": 0.0})
            if pnl is not None:
                c["pnl"] += pnl
            c["ibkr"] += r["daily_pnl"] or 0.0
            c["flows"] += flow
            c["end_nav"] = r["nav"]
            # a gap (session not captured) folds into the next captured day
            gap = p and (dd - dt.date.fromisoformat(p[0])).days > (3 if dd.weekday() == 0 else 1)
            c["daily"].append({"date": d, "pnl": pnl, "nav": r["nav"], "ibkr": r["daily_pnl"], "since": p[0] if gap else None,
                               "flow": flow or None})
            prev[a] = (d, r["nav"])
    out = []
    first = days[0] if days else None
    today_et = dt.datetime.now(ET).date()
    for monday in sorted(wk, reverse=True)[:weeks]:
        w = wk[monday]
        for c in w["acct"].values():
            if all(d["pnl"] is None for d in c["daily"]):
                c["pnl"] = None  # only a first capture for this account: no earlier NAV to compare with
            base = c["start_nav"] or next((d["nav"] - d["pnl"] for d in c["daily"] if d["pnl"] is not None), None)
            c["pct"] = 100 * c["pnl"] / base if base and c["pnl"] is not None else None
        # explain the coverage: trading days only (US holidays excluded), the current week to date,
        # days before history starts, and days not captured (their P&L lands in the next captured day)
        mon = dt.date.fromisoformat(monday)
        sessions = [mon + dt.timedelta(days=i) for i in range(5)]
        trading = [d for d in sessions if d.isoformat() not in US_HOLIDAYS]
        got = set(w["days"])
        missing = [d for d in trading if d.isoformat() not in got and d.isoformat() >= (first or "") and d <= today_et]
        before = [d for d in trading if first and d.isoformat() < first]
        notes = []
        if mon + dt.timedelta(days=4) >= today_et:
            notes.append(f"week to date ({len(got)} of {len(trading)} sessions)")
        if before:
            notes.append(f"history starts {dt.date.fromisoformat(first):%a %d %b}")
        for d in missing:
            nxt = next((x for x in days if x > d.isoformat()), None)
            if nxt:
                where = "next week" if dt.date.fromisoformat(nxt) - dt.timedelta(days=dt.date.fromisoformat(nxt).weekday()) != mon else "the same week"
                notes.append(f"{d:%a %d %b} not captured: its P&L is in {dt.date.fromisoformat(nxt):%a %d %b} ({where})")
        hol = [d for d in sessions if d.isoformat() in US_HOLIDAYS]
        if hol:
            notes.append("market holiday " + ", ".join(f"{d:%a %d %b}" for d in hol))
        w["trading_days"] = len(trading)
        w["notes"] = notes
        w["complete"] = not missing and not before and mon + dt.timedelta(days=4) < today_et
        out.append(w)
    nav_series = {a: [{"d": d, "v": byday[d][a]["nav"]} for d in days if a in byday[d] and byday[d][a]["nav"]] for a in accts}
    from . import flex
    return {"accounts": [{"id": a, "label": labels.get(a, a)} for a in accts], "weeks": out, "nav": nav_series,
            "first": days[0] if days else None, "last": days[-1] if days else None, "basis": "nav", "flex": flex.info()}


def todays_fills(ib):
    """Today's fills with their commissions. reqExecutions returns new Fill objects that never see the commission
    reports: ib_async puts those on the fills it stores, which ib.fills() returns."""
    ib.reqExecutions()
    ib.sleep(1)  # the reports arrive just after the executions
    return ib.fills()


def last_close_nav(before):
    """NAV per account at the last recorded session before `before` (ISO date)."""
    init()
    out = {}
    for r in db.query("""SELECT account, nav, date FROM account_daily a WHERE date = (SELECT MAX(date) FROM account_daily b
                         WHERE b.account = a.account AND b.date < ?)""", (before,)):
        out[r["account"]] = {"nav": r["nav"], "date": r["date"]}
    return out


# ------------------------------------------------------------------ ONE import file
def one_import_rows(account, date_local=None):
    """IBKR Flex-format rows ONE imports, for one account's option fills on a local (Sydney) date."""
    init()
    rows = db.query("SELECT * FROM executions WHERE account=? AND sec_type='OPT' ORDER BY time_utc", (account,))
    target = date_local or dt.datetime.now(LOCAL_TZ).date().isoformat()
    out = []
    for r in rows:
        if not r["time_utc"]:
            continue
        t = dt.datetime.fromisoformat(r["time_utc"]).astimezone(LOCAL_TZ)
        if t.date().isoformat() != target:
            continue
        signed = abs(r["qty"]) if r["side"] == "BOT" else -abs(r["qty"])
        comm = r["commission"] or 0.0  # a charge is positive here, negative in a real Flex file, which is what ONE reads
        net = -(signed * r["price"] * (r["mult"] or 100)) - comm
        root, rest = r["local_symbol"][:6].strip(), r["local_symbol"][6:].strip()
        osi = f"{root:<6}{rest}"  # IBKR local symbol is the OSI symbol with the real expiration
        out.append([t.strftime("%Y%m%d,%H%M%S"), "BUY" if signed > 0 else "SELL", "OPT", osi, f"{signed:g}",
                    f"{r['price']:g}", "" if r["commission"] is None else f"{-comm or 0:g}", r["symbol"], f"{net:g}"])
    return out


def one_import_csv(account, date_local=None):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["DateTime", "Buy/Sell", "AssetClass", "Symbol", "Quantity", "TradePrice", "IBCommission", "UnderlyingSymbol", "NetCash"])
    w.writerows(one_import_rows(account, date_local))
    return buf.getvalue()


def fills(days=7):
    init()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    # one row per fill: leave out each combo's own row and the FA master's copy of the sub-account fills
    return db.query("SELECT * FROM executions WHERE time_utc>=? AND sec_type<>'BAG' AND account NOT LIKE 'F%' ORDER BY time_utc DESC", (since,))
