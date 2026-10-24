"""Trade journal: every closed trade in the newest ONE Summary Report, with its legs, how it got there,
the market around it, and a one-line learning note (auto-suggested, editable).

P&L fluctuation (exact data only):
* price path: the underlying's daily closes through the trade against its strikes, with adjustment dates —
  for every trade; worst / best move in % of the entry price;
* marked path: the trade's full mark-to-market P&L recorded by this app at each session close
  (trade_pnl table). Only exists for trades that were open while the desk was recording (from Oct 2026);
  when present it gives the true worst (MAE) and best (MFE) points.
"""
import csv
import datetime as dt
import re

import numpy as np

from . import db, load_config
from .history import series
from .trades import _newest, classify

SYD = dt.timezone(dt.timedelta(hours=10))  # ONE times are Sydney local; -14h gives the US session date (AEDT)


def init():
    db.write("""CREATE TABLE IF NOT EXISTS trade_pnl (date TEXT, trade_key TEXT, name TEXT, account TEXT, underlying TEXT,
                pnl REAL, margin REAL, updated TEXT, PRIMARY KEY (date, trade_key))""")
    db.write("CREATE TABLE IF NOT EXISTS journal_notes (trade_key TEXT PRIMARY KEY, note TEXT, updated TEXT)")


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _dt(s):
    for f in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s.strip(), f)
        except (ValueError, AttributeError):
            pass
    return None


def _us(t):
    """ONE local (Sydney) timestamp -> US session date (ISO)."""
    return (t - dt.timedelta(hours=14)).date().isoformat() if t else None


def parse(path=None):
    path = path or _newest(load_config()["trade_files"]["one_glob"])
    if not path:
        return [], None
    trades, cur = [], None
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.reader(fh):
            if len(r) > 15 and r[0] == "" and r[2] in ("Open", "Closed", "Expired") and r[1] and r[1] != "Account":
                if r[1].lower().startswith("backtest"):
                    cur = None
                    continue
                cur = {"key": f"{r[1]}#{r[6]}", "group": r[1], "status": r[2], "underlying": r[3], "expiry": r[4], "trade_id": r[6],
                       "name": r[7], "open": _dt(r[8]), "close": _dt(r[9]), "dte": _num(r[10]), "dit": _num(r[11]), "margin": _num(r[12]),
                       "comms": _num(r[13]), "pnl": _num(r[14]), "ret": _num(r[15]), "legs": [], "strategy": classify(r[1], r[7])}
                trades.append(cur)
            elif cur is not None and len(r) > 17 and r[0] == "" and r[1] == "" and r[3] == cur["trade_id"] and r[5] in ("Buy", "Sell"):
                sym = r[7]
                m = re.search(r"(\d{6})([CP])(\d{8})$", sym.replace(" ", ""))
                cur["legs"].append({"open": _dt(r[4]), "side": r[5], "qty": _num(r[6]) or 0, "symbol": sym.strip(), "expiry": r[8],
                                    "right": m.group(2) if m else r[9][:1], "strike": int(m.group(3)) / 1000 if m else None,
                                    "open_px": _num(r[12]), "comm": _num(r[13]), "close": _dt(r[14]), "close_px": _num(r[15]),
                                    "dit": _num(r[16]), "pnl": _num(r[17])})
    return trades, path


def _context(t):
    """Market at entry and the underlying's path through the trade."""
    d0, d1 = _us(t["open"]), _us(t["close"])
    out = {"entry": d0, "exit": d1}
    vix, v3 = series("VIX"), series("VIX3M")
    a = lambda s, d: float(s[s.index <= d].iloc[-1]) if d and len(s[s.index <= d]) else None  # noqa: E731
    out["vix"] = a(vix, d0)
    v3m = a(v3, d0)
    out["ivts"] = out["vix"] / v3m if out["vix"] and v3m else None
    und = t["underlying"] if t["underlying"] in ("SPX", "RUT", "NDX") else None
    if und and d0:
        s = series(und)
        pre = s[s.index <= d0]
        if len(pre) >= 20:
            out["vs_sma20"] = 100 * (float(pre.iloc[-1]) / float(pre.iloc[-20:].mean()) - 1)
        seg = s[(s.index >= d0) & (s.index <= (d1 or s.index[-1]))]
        if len(seg):
            base = float(seg.iloc[0])
            out["path"] = [{"d": k, "v": float(v)} for k, v in seg.items()]
            out["move"] = 100 * (float(seg.iloc[-1]) / base - 1)
            out["maxdn"] = 100 * (float(seg.min()) / base - 1)
            out["maxup"] = 100 * (float(seg.max()) / base - 1)
    return out


def _realised_path(t):
    """Cumulative realised P&L at each leg close, in time order (commissions are inside the leg P&L)."""
    ev = sorted([lg for lg in t["legs"] if lg["close"] and lg["pnl"] is not None], key=lambda lg: lg["close"])
    pts, run = [{"t": t["open"].isoformat() if t["open"] else None, "v": 0.0, "what": "open"}], 0.0
    for lg in ev:
        run += lg["pnl"]
        pts.append({"t": lg["close"].isoformat(), "v": round(run, 2), "what": f"{lg['side']} {lg['qty']:g} {lg['strike'] or ''}{lg['right']}"})
    # merge legs closed in the same minute (one adjustment ticket)
    merged = []
    for p in pts:
        if merged and p["t"] and merged[-1]["t"] and p["t"][:16] == merged[-1]["t"][:16]:
            merged[-1] = {**p, "what": merged[-1]["what"] + ", " + p["what"] if merged[-1]["what"] != "open" else p["what"]}
        else:
            merged.append(p)
    return merged


def _marked_path(key):
    rows = db.query("SELECT date, pnl FROM trade_pnl WHERE trade_key=? ORDER BY date", (key,))
    return [{"d": r["date"], "v": r["pnl"]} for r in rows if r["pnl"] is not None]


def _adjustments(t):
    if not t["open"]:
        return 0
    stamps = {lg["open"].strftime("%Y%m%d%H%M") for lg in t["legs"] if lg["open"] and (lg["open"] - t["open"]).total_seconds() > 600}
    stamps |= {lg["close"].strftime("%Y%m%d%H%M") for lg in t["legs"] if lg["close"] and t["close"] and (t["close"] - lg["close"]).total_seconds() > 600}
    return len(stamps)


def suggest_note(t, ctx, adj, swing):
    """One plain-English line from the data: the outcome and what most likely drove it."""
    ret, dit, pnl = t["ret"] or 0, max(t["dit"] or 1, 1), t["pnl"] or 0
    win = pnl > 0
    bits = []
    if win and dit <= 5 and ret >= 4:
        bits.append(f"fast win: {ret:.1f}% in {int(dit)} days")
    elif win and ret / dit < 0.15:
        bits.append(f"slow capital: {ret / dit:.2f}%/day over {int(dit)} days")
    elif win:
        bits.append(f"won {ret:.1f}% in {int(dit)} days")
    else:
        bits.append(f"lost {abs(ret):.1f}% in {int(dit)} days")
    if adj >= 8:
        bits.append(f"{adj} adjustments — management-heavy")
    elif adj == 0 and win:
        bits.append("no adjustments needed")
    md = ctx.get("maxdn")
    if md is not None and md <= -3:
        bits.append(f"{'survived' if win else 'hit by'} a {abs(md):.1f}% drop in {t['underlying']}")
    if t["strategy"] in ("TimeEdge", "TimeZone", "Triple Cal") and ctx.get("ivts") and ctx["ivts"] >= 0.90:
        bits.append(f"entered at VIX/VIX3M {ctx['ivts']:.2f} (0.90+: calendars lost on average there since 2009)")
    if t["strategy"] == "A14" and ctx.get("vs_sma20") is not None and ctx["vs_sma20"] < 0:
        bits.append("entered below the 20-day average (weaker A14 setup)")
    if swing and swing.get("mae") is not None and win and swing["mae"] < -0.5 * abs(pnl):
        bits.append(f"was {swing['mae']:,.0f} down at worst before recovering")
    s = "; ".join(bits[:3])
    return s[0].upper() + s[1:] + "."


def closed():
    init()
    trades, path = parse()
    notes = {r["trade_key"]: r["note"] for r in db.query("SELECT * FROM journal_notes")}
    out = []
    for t in trades:
        if t["status"] not in ("Closed", "Expired"):
            continue
        ctx = _context(t)
        rp = _realised_path(t)
        mp = _marked_path(t["key"])
        vals = [p["v"] for p in rp]
        swing = {"realised_min": min(vals) if vals else None, "realised_max": max(vals) if vals else None,
                 "mae": min([p["v"] for p in mp] + [0]) if mp else None, "mfe": max([p["v"] for p in mp] + [0]) if mp else None,
                 "marked_days": len(mp)}
        adj = _adjustments(t)
        auto = suggest_note(t, ctx, adj, swing)
        adj_dates = sorted({_us(lg["open"]) for lg in t["legs"] if lg["open"] and t["open"] and (lg["open"] - t["open"]).total_seconds() > 600}
                           | {_us(lg["close"]) for lg in t["legs"] if lg["close"] and t["close"] and (t["close"] - lg["close"]).total_seconds() > 600})
        out.append({"key": t["key"], "trade_id": t["trade_id"], "group": t["group"], "name": t["name"], "ticker": t["underlying"],
                    "strategy": t["strategy"], "expiry": t["expiry"], "open": t["open"].isoformat() if t["open"] else None,
                    "close": t["close"].isoformat() if t["close"] else None, "entry_us": ctx.get("entry"), "exit_us": ctx.get("exit"),
                    "dit": t["dit"], "dte": t["dte"], "margin": t["margin"], "comms": t["comms"], "pnl": t["pnl"], "ret": t["ret"],
                    "adjustments": adj, "adj_dates": adj_dates, "legs_n": len(t["legs"]), "swing": swing, "realised_path": rp, "marked_path": mp,
                    "ctx": {k: v for k, v in ctx.items() if k != "path"}, "path": ctx.get("path"),
                    "strikes": sorted({lg["strike"] for lg in t["legs"] if lg["strike"]}),
                    "entry_strikes": sorted({lg["strike"] for lg in t["legs"] if lg["strike"] and lg["open"] and t["open"]
                                             and (lg["open"] - t["open"]).total_seconds() <= 600}),
                    "legs": [{**lg, "open": lg["open"].isoformat() if lg["open"] else None, "close": lg["close"].isoformat() if lg["close"] else None}
                             for lg in t["legs"]],
                    "note": notes.get(t["key"]) or auto, "note_auto": auto, "note_edited": t["key"] in notes})
    out.sort(key=lambda x: x["close"] or "", reverse=True)
    return {"trades": out, "file": path}


def save_note(key, note):
    init()
    note = (note or "").strip()
    if note:
        db.write("INSERT OR REPLACE INTO journal_notes VALUES (?,?,?)", (key, note[:300], dt.datetime.now().isoformat(timespec="seconds")))
    else:
        db.write("DELETE FROM journal_notes WHERE trade_key=?", (key,))
    return {"ok": True}


def snapshot_open():
    """Record every open trade's marked P&L for the current session (called after each TWS refresh)."""
    from .recorder import session_date
    from .risk import payload
    init()
    pl = payload()
    if not pl.get("marks_ts"):
        return 0
    sess = session_date().isoformat()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = []
    for t in pl["trades"]:
        legs = t["legs"]
        if not legs or any(not (lg.get("mark") or {}).get("mid") is not None for lg in legs):
            continue  # only fully marked trades: a missing leg would distort the path
        unreal = sum((lg["mark"]["mid"] - (lg["open_price"] or 0)) * lg["qty"] * 100 for lg in legs)
        rows.append((sess, t["id"], t["name"], t.get("ib_account"), t["underlying"], round((t.get("one_pnl") or 0) + unreal, 2), t.get("margin"), now))
    if rows:
        db.write("INSERT OR REPLACE INTO trade_pnl VALUES (?,?,?,?,?,?,?,?)", rows, many=True)
    return len(rows)
