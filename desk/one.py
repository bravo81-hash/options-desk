"""ONE's two exports, read one way (the same idea as TWS Matcher's one_reader).

The Summary Report has one row per leg with average prices; the Detail Report has every fill with its own time.
Both carry the same trade rows, so whichever was exported last serves everything that needs the book, and a Detail
Report's fills become the rows a Summary would show. ONE lets you reorder columns, so they are found from each
file's header rows. Only the Detail Report knows what the position was at each moment: desk/positions.py uses it.
"""
import csv
import datetime as dt
import glob
import os
import re

from . import expand, load_config

STATUSES = ("Open", "Closed", "Expired")
# Used when a file has no header rows: ONE's standard column order
TRADE_COLS = ["", "Account", "Status", "Underlying", "Expiration", "TradeType", "TradeId", "TradeName", "OpenDate", "CloseDate",
              "DaysToExpiration", "DaysInTrade", "Margin", "Comms", "PnL", "PnLperc"]
LEG_COLS = ["", "", "Account", "TradeId", "OpenDate", "Transaction", "Qty", "Symbol", "Expiry", "Type", "Description", "Underlying",
            "AvgOpenPrice", "Commission", "CloseDate", "AvgClosePrice", "DIT", "PnL"]
_MARGIN = ("Margin", "MaxAbsRisk", "Max Abs Risk")  # ONE names this column after the report's Margin dropdown


def _newest(patterns):
    files = []
    for p in patterns:
        files += glob.glob(expand(p))
    return max(files, key=os.path.getmtime) if files else None


def report_path():
    """The newest ONE export of either kind."""
    tf = load_config()["trade_files"]
    return _newest(list(tf["one_glob"]) + list(tf.get("one_detail_glob", [])))


def detail_path():
    """The newest Detail Report: the only export with every fill."""
    return _newest(load_config()["trade_files"].get("one_detail_glob", []))


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def when(s):
    """ONE's local (Sydney) timestamp, or None."""
    for f in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s.strip(), f)
        except (ValueError, AttributeError):
            pass
    return None


def legs_from_fills(fills):
    """Fills as the rows a Summary Report would show. ONE's basis is a moving average per contract: adding moves it,
    reducing doesn't. Each closed piece gets its own row (P&L net of its share of both commissions) and each opening
    fill keeps its own time, closed first in, first out."""
    pools, out = {}, []
    for f in sorted(fills, key=lambda f: f["t"]):
        p = pools.setdefault((f["symbol"], f["expiry"]), {"avg": 0.0, "lots": []})
        sign, left = (1 if f["side"] == "Buy" else -1), f["qty"]
        rate = f["comm"] / f["qty"] if f["qty"] else 0.0
        while left > 1e-9 and p["lots"] and p["lots"][0]["sign"] != sign:
            lot = p["lots"][0]
            take = min(left, lot["qty"])
            comm = (lot["rate"] + rate) * take
            out.append({**lot["row"], "qty": take, "open_px": p["avg"], "comm": comm, "close": f["t"], "close_px": f["px"],
                        "dit": (f["t"].date() - lot["row"]["open"].date()).days, "pnl": (f["px"] - p["avg"]) * take * 100 * lot["sign"] - comm})
            lot["qty"] -= take
            left -= take
            if lot["qty"] <= 1e-9:
                p["lots"].pop(0)
        if left > 1e-9:
            held = sum(lot["qty"] for lot in p["lots"])
            p["avg"] = (p["avg"] * held + f["px"] * left) / (held + left)
            row = {"open": f["t"], "side": f["side"], "symbol": f["symbol"], "expiry": f["expiry"], "type": f["type"], "desc": f["desc"],
                   "underlying": f["underlying"], "close": None, "close_px": None, "dit": None, "pnl": None}
            p["lots"].append({"sign": sign, "qty": left, "rate": rate, "row": row})
    for p in pools.values():
        out += [{**lot["row"], "qty": lot["qty"], "open_px": p["avg"], "comm": lot["rate"] * lot["qty"]} for lot in p["lots"]]
    return sorted(out, key=lambda lg: (lg["open"], lg["close"] or dt.datetime.max))


def read(path=None):
    """(trades, path, kind): every trade in a ONE export in one shape, whichever kind it is. Back-tests are left out.
    `legs` are Summary-style rows; `fills` is the fill history, or None for a Summary Report."""
    path = path or report_path()
    if not path:
        return [], None, None
    tc = {n: i for i, n in enumerate(TRADE_COLS) if n}
    lc = {n: i for i, n in enumerate(LEG_COLS) if n}
    detail, trades, cur = False, [], None

    def get(row, cols, *names):
        for n in names:
            if n in cols and cols[n] < len(row):
                return row[cols[n]]
        return ""

    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.reader(fh):
            if "Symbol" in r and "Transaction" in r:
                lc = {n: i for i, n in enumerate(r) if n}
                detail = "Price" in lc and "AvgOpenPrice" not in lc
                continue
            if "TradeName" in r and "TradeId" in r:
                tc = {n: i for i, n in enumerate(r) if n}
                continue
            status = get(r, tc, "Status")
            if r and r[0] == "" and status in STATUSES and get(r, tc, "Account"):
                acct = get(r, tc, "Account")
                cur = None
                if acct.lower().startswith("backtest"):
                    continue
                cur = {"account": acct, "status": status, "underlying": get(r, tc, "Underlying"), "expiration": get(r, tc, "Expiration"),
                       "trade_id": get(r, tc, "TradeId"), "name": get(r, tc, "TradeName"), "opened": get(r, tc, "OpenDate"),
                       "closed": get(r, tc, "CloseDate"), "dte": num(get(r, tc, "DaysToExpiration")), "dit": num(get(r, tc, "DaysInTrade")),
                       "margin": num(get(r, tc, *_MARGIN)), "comms": num(get(r, tc, "Comms")), "pnl": num(get(r, tc, "PnL")),
                       "ret": num(get(r, tc, "PnLperc")), "legs": [], "fills": []}
                trades.append(cur)
            elif cur and len(r) >= 2 and r[0] == "" and r[1] == "" and get(r, lc, "TradeId") == cur["trade_id"] and get(r, lc, "Transaction") in ("Buy", "Sell"):
                row = {"side": get(r, lc, "Transaction"), "qty": num(get(r, lc, "Qty")) or 0.0, "symbol": get(r, lc, "Symbol").strip(),
                       "expiry": get(r, lc, "Expiry").strip(), "type": get(r, lc, "Type"), "desc": get(r, lc, "Description"),
                       "underlying": get(r, lc, "Underlying")}
                if detail:
                    cur["fills"].append({**row, "t": when(get(r, lc, "Date")), "px": num(get(r, lc, "Price")) or 0.0, "comm": num(get(r, lc, "Commission")) or 0.0})
                else:
                    cur["legs"].append({**row, "open": when(get(r, lc, "OpenDate")), "open_px": num(get(r, lc, "AvgOpenPrice")), "comm": num(get(r, lc, "Commission")),
                                        "close": when(get(r, lc, "CloseDate")), "close_px": num(get(r, lc, "AvgClosePrice")), "dit": num(get(r, lc, "DIT")),
                                        "pnl": num(get(r, lc, "PnL"))})
    for t in trades:
        t["fills"] = [f for f in t["fills"] if f["t"]] if detail else None
        if detail:
            t["legs"] = legs_from_fills(t["fills"])
    return trades, path, "detail" if detail else "summary"
