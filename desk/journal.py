"""Trade journal: every closed trade in the newest ONE export, with its legs, how it got there,
the market around it, and a one-line learning note (auto-suggested, editable).

P&L fluctuation (exact data only):
* price path: the underlying's daily closes through the trade against its strikes, with adjustment dates —
  for every trade; worst / best move in % of the entry price;
* marked path: the trade's full mark-to-market P&L recorded by this app at each session close
  (trade_pnl table). Only exists for trades that were open while the desk was recording (from Oct 2026);
  when present it gives the true worst (MAE) and best (MFE) points.
"""
import datetime as dt
import functools
import json
import os
import re
import threading
import uuid

from . import db, load_config, one, positions
from .history import series
from .trades import _newest, classify, fix_name, labels, load_optionstrat

SYD = dt.timezone(dt.timedelta(hours=10))  # ONE times are Sydney local; -14h gives the US session date (AEDT)
# The guest's rules of thumb and the desk's filters: every one can be changed in Journal > Settings
DEFAULTS = {"cap_warn_pct": 1.0, "cap_pct": 2.0, "loss_bar": 30, "cv_max": 10.0, "skew_min": 0.5, "extreme_x": 2.5, "streak_n": 4,
            "revenge_minutes": 30, "revenge_loss_r": 0.25, "revenge_size": 1.25, "roll_minutes": 60, "creep_x": 2.0}
# Everything a person typed or the page logged: no report can rebuild these, so export/import and the snapshot carry them
MANUAL = ("journal_notes", "journal_settings", "journal_tags", "journal_tickets", "journal_overrides", "journal_reviews", "journal_planlog")


def init():
    db.write("""CREATE TABLE IF NOT EXISTS trade_pnl (date TEXT, trade_key TEXT, name TEXT, account TEXT, underlying TEXT,
                pnl REAL, margin REAL, updated TEXT, PRIMARY KEY (date, trade_key))""")
    db.write("CREATE TABLE IF NOT EXISTS journal_notes (trade_key TEXT PRIMARY KEY, note TEXT, updated TEXT)")
    db.write("CREATE TABLE IF NOT EXISTS journal_settings (key TEXT PRIMARY KEY, value REAL, updated TEXT)")
    db.write("""CREATE TABLE IF NOT EXISTS journal_tags (decision TEXT, phase TEXT, mood TEXT, confidence INTEGER, tired INTEGER,
                updated TEXT, PRIMARY KEY (decision, phase))""")
    db.write("""CREATE TABLE IF NOT EXISTS journal_tickets (id TEXT PRIMARY KEY, created TEXT, strategy TEXT, ticker TEXT, account TEXT, worst REAL,
                stop_pct REAL, plan REAL, nav REAL, checklist TEXT, mood TEXT, confidence INTEGER, tired INTEGER, note TEXT, updated TEXT)""")
    db.write("CREATE TABLE IF NOT EXISTS journal_overrides (id TEXT PRIMARY KEY, decision TEXT, kind TEXT, rule TEXT, why TEXT, rules_said TEXT, updated TEXT)")
    db.write("CREATE TABLE IF NOT EXISTS journal_reviews (decision TEXT PRIMARY KEY, cause TEXT, emotion TEXT, rule_broken TEXT, lesson TEXT, updated TEXT)")
    db.write("""CREATE TABLE IF NOT EXISTS journal_planlog (date TEXT, trade_key TEXT, act TEXT, label TEXT, adj TEXT, pct REAL, updated TEXT,
                PRIMARY KEY (date, trade_key))""")
    positions.init()


def _us(t):
    """ONE local (Sydney) timestamp -> US session date (ISO)."""
    return (t - dt.timedelta(hours=14)).date().isoformat() if t else None


def parse(path=None):
    rows, path, _ = one.read(path)
    trades = []
    for r in rows:
        legs = []
        for lg in r["legs"]:
            if not lg["close"]:
                continue
            m = re.search(r"(\d{6})([CP])(\d{8})$", lg["symbol"].replace(" ", ""))
            legs.append({"open": lg["open"], "side": lg["side"], "qty": lg["qty"], "symbol": lg["symbol"], "expiry": lg["expiry"],
                         "right": m.group(2) if m else lg["type"][:1], "strike": int(m.group(3)) / 1000 if m else None,
                         "open_px": lg["open_px"], "comm": lg["comm"], "close": lg["close"], "close_px": lg["close_px"], "dit": lg["dit"], "pnl": lg["pnl"]})
        trades.append({"key": f"{r['account']}#{r['trade_id']}", "group": r["account"], "status": r["status"], "underlying": r["underlying"],
                       "expiry": r["expiration"], "trade_id": r["trade_id"], "name": fix_name(r["name"]), "raw_name": r["name"], "open": one.when(r["opened"]),
                       "close": one.when(r["closed"]), "dte": r["dte"], "dit": r["dit"], "margin": r["margin"], "comms": r["comms"],
                       "pnl": r["pnl"], "ret": r["ret"], "legs": legs, "strategy": classify(r["account"], r["name"])})
    return trades, path


def _context(t, load=series):
    """Market at entry and the underlying's path through the trade."""
    d0, d1 = _us(t["open"]), _us(t["close"])
    out = {"entry": d0, "exit": d1}
    vix, v3 = load("VIX"), load("VIX3M")
    a = lambda s, d: float(s[s.index <= d].iloc[-1]) if d and len(s[s.index <= d]) else None  # noqa: E731
    out["vix"] = a(vix, d0)
    v3m = a(v3, d0)
    out["ivts"] = out["vix"] / v3m if out["vix"] and v3m else None
    und = t["underlying"] if t["underlying"] in ("SPX", "RUT", "NDX") else None
    if und and d0:
        s = load(und)
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


def settings():
    saved = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM journal_settings")}
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def _heat(rows):
    """Open risk at each entry, per account: what else was on when this one went on, this one included."""
    for r in rows:
        live = [x for x in rows if x["acct"] == r["acct"] and x["entry"] <= r["entry"] and (x["close"] is None or x["close"] > r["entry"])]
        r["heat_n"] = len(live)
        r["heat_noplan"] = sum(1 for x in live if x["plan"] is None)
        r["heat_plan_pct"] = 100 * sum(x["plan"] or 0 for x in live) / r["nav"] if r["nav"] else None
        r["heat_risk_pct"] = 100 * sum(x["risk0"] for x in live) / r["nav"] if r["nav"] else None


def heat_series(rows, nav):
    """{account: [{d, plan, risk, n}]} on every session a position opened or closed. Planned loss leaves out trades with no card."""
    out = {}
    for acct in sorted({r["acct"] for r in rows}):
        mine = [r for r in rows if r["acct"] == acct]
        pts = []
        for d in sorted({r["entry_us"] for r in mine} | {r["exit_us"] for r in mine if r["exit_us"]}):
            live = [r for r in mine if r["entry_us"] <= d and (r["exit_us"] is None or r["exit_us"] > d)]
            usd = nav(mine[0]["ib"], d)
            if usd:
                pts.append({"d": d, "plan": round(100 * sum(r["plan"] or 0 for r in live) / usd, 2), "risk": round(100 * sum(r["risk0"] for r in live) / usd, 1), "n": len(live)})
        out[acct] = pts
    return out


def book(trades, ctxs, cfg):
    """Every position with what it risked and how it was run, closed and open, twins and rolls resolved. All amounts USD."""
    pos, exported = positions.load()
    conf = load_config().get("risk", {})
    amap, names, nav = conf.get("account_map", {}), conf.get("account_labels", {}), positions.nav_lookup()
    rows, pending = [], []
    for t in trades:
        p = pos.get(t["key"])
        if not p or p["risk0"] <= 0:
            pending.append(t["key"])
            continue
        ctx, done = ctxs.get(t["key"]) or {}, t["status"] != "Open"
        ib = amap.get(re.sub(r"^\d+\.\s*", "", t["group"]).strip())
        exp = dt.datetime.strptime(t["expiry"], "%d/%m/%Y").date() if t["expiry"] else None
        close, entry_us = (t["close"] if done else None), _us(p["entry"])
        rows.append({"key": t["key"], "keys": [t["key"]], "trade_id": t["trade_id"], "name": t["name"], "group": t["group"], "ib": ib, "acct": names.get(ib, t["group"]),
                     "strategy": t["strategy"], "labels": labels(t["group"], t["raw_name"]), "ticker": t["underlying"], "expiry_iso": exp.isoformat() if exp else None,
                     "entry": p["entry"], "close": close, "open": not done, "entry_us": entry_us, "exit_us": _us(close),
                     "dte0": (exp - dt.date.fromisoformat(entry_us)).days if exp else None, "dte_exit": (exp - dt.date.fromisoformat(_us(close))).days if exp and close else None,
                     "dit": t["dit"], "pnl": t["pnl"] if done else None, "ret": t["ret"], "margin": t["margin"], "comms": t["comms"], "risk0": p["risk0"], "peak": p["peak"],
                     "adj": p["adj"], "risk_days": p["risk_days"], "lots0": p["lots0"], "lots_peak": p["lots_peak"], "capped": p["capped"],
                     "r": t["pnl"] / p["risk0"] if done and t["pnl"] is not None else None, "vix": ctx.get("vix"), "ivts": ctx.get("ivts"), "vs20": ctx.get("vs_sma20")})
    positions.resolve_twins(rows)
    positions.link_rolls(rows, cfg["roll_minutes"])
    rows = positions.chains(rows)
    for r in rows:
        stop = (positions.CARDS.get(r["strategy"]) or {}).get("stop")
        r["decision"] = positions.decision_id(r["ticker"], r["strategy"], r["expiry_iso"], r["entry_us"])
        r["nav"] = nav(r["ib"], r["entry_us"])
        r["plan"] = r["risk0"] * stop / 100 if stop else None
        for k, v in (("plan_pct", r["plan"]), ("risk_pct", r["risk0"]), ("peak_pct", r["peak"])):
            r[k] = 100 * v / r["nav"] if r["nav"] and v is not None else None
        r["creep"] = r["peak"] / r["risk0"]
        r["rod"] = 100 * r["pnl"] / r["risk_days"] if r["close"] and r["risk_days"] > 0 else None
        marks = [m["v"] for k in r["keys"] for m in _marked_path(k)]
        r["mae_r"] = min(marks + [0]) / r["risk0"] if marks else None
        r["mfe_r"] = max(marks + [0]) / r["risk0"] if marks else None
        r["checks"] = positions.rule_checks(r, cfg["cap_pct"])
        live = [c for c in r["checks"] if c[2]]
        r["followed"] = all(c[1] for c in live) if live else None
        r["followed_ever"] = all(c[1] for c in r["checks"]) if r["checks"] else None
    _heat(rows)
    heat = heat_series(rows, nav)
    decisions = positions.fold(rows)
    flags = positions.behaviour(decisions, cfg)
    plans = {}
    for r in rows:
        if r["plan"] is not None:
            plans[r["decision"]] = plans.get(r["decision"], 0) + r["plan"]
    extreme, avg_loss = positions.extreme_flags(decisions, plans, cfg["extreme_x"])
    tickets = positions.link_tickets(decisions, db.query("SELECT * FROM journal_tickets"))
    now = {}
    for ib, label in names.items():
        usd = nav(ib, dt.date.today().isoformat())
        if usd:
            now[label] = round(usd)
    for r in rows:
        r.update(flags.get(r["decision"], {}), extreme=extreme.get(r["decision"], []), ticket=tickets.get(r["decision"]))
        r["entry"], r["close"] = r["entry"].isoformat(), r["close"].isoformat() if r["close"] else None
        for k in ("labels", "ib", "group"):
            r.pop(k, None)
    rows.sort(key=lambda r: r["entry"])
    exits = {k: r["exit_us"] for r in rows for k in r["keys"]}
    return {"rows": rows, "pending": pending, "exported": exported, "heat": heat, "avg_loss_r": avg_loss, "nav_now": now, "streak_now": positions.streak_now(decisions),
            "plan": positions.plan_scores(db.query("SELECT * FROM journal_planlog"), pos, exits)}


_history, _memo, _memo_lock = {}, {}, threading.Lock()


def history():
    """Wins and losses before ONE took over, by strategy. OptionStrat kept no legs or margin, so there is no R for these."""
    path = _newest(load_config()["trade_files"].get("optionstrat_glob", []))
    if not path:
        return {}
    key = (path, os.path.getmtime(path))
    if key not in _history:
        cut = dt.date.fromisoformat(load_config()["trade_files"]["one_start"])
        out = {}
        for t in load_optionstrat(path)[0]:
            if t["opened"] and t["opened"] < cut and t["pnl"] is not None:
                c = out.setdefault(t["strategy"], {"n": 0, "losses": 0, "pnl": 0.0})
                c["n"] += 1
                c["losses"] += int(t["pnl"] <= 0)
                c["pnl"] += t["pnl"]
        _history.clear()
        _history[key] = out
    return _history[key]


def manual():
    """What was typed in, read back for the page and, through the snapshot, for the cloud copy."""
    return {t: [dict(r) for r in db.query(f"SELECT * FROM {t}")] for t in MANUAL}


def _stamp():
    """Everything the page's payload is built from. The build takes seconds and the Actions tab asks for part of it on every load."""
    path = one.report_path()
    q = [f"SELECT COUNT(*) n, MAX(updated) v FROM {t}" for t in MANUAL + ("trade_pnl",)] + [f"SELECT COUNT(*) n, MAX(date) v FROM {t}" for t in ("account_daily", "fx_daily", "index_daily")]
    return str(db._PATH), path, path and os.path.getmtime(path), tuple(tuple(db.query(sql)[0].values()) for sql in q)


def closed():
    init()
    with _memo_lock:  # the Actions tab and the Journal can both ask at once: one build, and the other waits for it
        stamp = _stamp()
        if _memo.get("stamp") != stamp:
            _memo.update(stamp=stamp, out=_build())
        return _memo["out"]


def due():
    """What the journal is owed, for the Actions tab and the nav badge: post-mortems not yet written, and the winning streak as it stands."""
    J = closed()
    done, seen, items = {r["decision"] for r in J["manual"]["journal_reviews"]}, set(), []
    for r in J["book"]:
        if r["extreme"] and r["decision"] not in done and r["decision"] not in seen:
            seen.add(r["decision"])
            items.append({"decision": r["decision"], "ticker": r["ticker"], "strategy": r["strategy"], "why": r["extreme"], "exit": r["exit_us"]})
    return {"due": items, "streak": J["streak_now"], "streak_n": J["settings"]["streak_n"]}


def _build():
    trades, path = parse()
    cfg = settings()
    notes = {r["trade_key"]: r["note"] for r in db.query("SELECT * FROM journal_notes")}
    load = functools.lru_cache(maxsize=None)(series)  # 3 series a trade, the same few each time
    ctxs = {t["key"]: _context(t, load) for t in trades}
    bk = book(trades, ctxs, cfg)
    pos = positions.load()[0]
    side = {k: r for r in bk["rows"] for k in r["keys"]}
    out = []
    for t in trades:
        if t["status"] not in ("Closed", "Expired"):
            continue
        ctx = ctxs[t["key"]]
        rp = _realised_path(t)
        mp = _marked_path(t["key"])
        vals = [p["v"] for p in rp]
        swing = {"realised_min": min(vals) if vals else None, "realised_max": max(vals) if vals else None,
                 "mae": min([p["v"] for p in mp] + [0]) if mp else None, "mfe": max([p["v"] for p in mp] + [0]) if mp else None,
                 "marked_days": len(mp)}
        p, s = pos.get(t["key"]), side.get(t["key"])
        adj = p["adj"] if p else _adjustments(t)
        auto = suggest_note(t, ctx, adj, swing)
        adj_dates = sorted({_us(e) for e in p["events"][1:]}) if p else sorted(
            {_us(lg["open"]) for lg in t["legs"] if lg["open"] and t["open"] and (lg["open"] - t["open"]).total_seconds() > 600}
            | {_us(lg["close"]) for lg in t["legs"] if lg["close"] and t["close"] and (t["close"] - lg["close"]).total_seconds() > 600})
        out.append({"key": t["key"], "trade_id": t["trade_id"], "group": t["group"], "name": t["name"], "ticker": t["underlying"],
                    "strategy": s["strategy"] if s else t["strategy"], "expiry": t["expiry"], "open": t["open"].isoformat() if t["open"] else None,
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
    return {"trades": out, "file": path, "book": bk["rows"], "pending": bk["pending"], "detail_exported": bk["exported"], "heat": bk["heat"],
            "avg_loss_r": bk["avg_loss_r"], "nav_now": bk["nav_now"], "streak_now": bk["streak_now"], "plan": bk["plan"], "settings": cfg, "defaults": DEFAULTS, "history": history(), "cards": positions.CARDS,
            "rules_from": {"card": positions.CARD_FROM, "gate": positions.GATE_FROM, "cap": positions.CAP_FROM}, "manual": manual()}


def save_note(key, note):
    init()
    note = (note or "").strip()
    if note:
        db.write("INSERT OR REPLACE INTO journal_notes VALUES (?,?,?)", (key, note[:300], dt.datetime.now().isoformat(timespec="seconds")))
    else:
        db.write("DELETE FROM journal_notes WHERE trade_key=?", (key,))
    return {"ok": True}


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def save_settings(values):
    init()
    for k, v in (values or {}).items():
        if k in DEFAULTS:
            db.write("INSERT OR REPLACE INTO journal_settings VALUES (?,?,?)", (k, float(v), _now()))
    return {"ok": True, "settings": settings()}


def save_tag(b):
    init()
    db.write("INSERT OR REPLACE INTO journal_tags VALUES (?,?,?,?,?,?)", (b["decision"], "before" if b.get("phase") == "before" else "after", (b.get("mood") or "")[:30],
             b.get("confidence"), 1 if b.get("tired") else 0, _now()))
    return {"ok": True}


def save_ticket(b):
    """A pre-commitment, written before the trade exists: the desk only sees a trade once it has filled."""
    init()
    worst, stop = float(b.get("worst") or 0), b.get("stop_pct")
    tid = b.get("id") or uuid.uuid4().hex[:12]
    db.write("INSERT OR REPLACE INTO journal_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (tid, b.get("created") or _now(), b.get("strategy"), (b.get("ticker") or "").upper(), b.get("account"), worst, stop, worst * float(stop) / 100 if stop else None,
              b.get("nav"), json.dumps(b.get("checklist") or {}), (b.get("mood") or "")[:30], b.get("confidence"), 1 if b.get("tired") else 0, (b.get("note") or "")[:300], _now()))
    return {"ok": True, "id": tid}


def delete_ticket(tid):
    init()
    db.write("DELETE FROM journal_tickets WHERE id=?", (tid,))
    return {"ok": True}


def save_override(b):
    init()
    oid = b.get("id") or uuid.uuid4().hex[:12]
    db.write("INSERT OR REPLACE INTO journal_overrides VALUES (?,?,?,?,?,?,?)", (oid, b.get("decision"), (b.get("kind") or "other")[:20], (b.get("rule") or "")[:120],
             (b.get("why") or "")[:300], (b.get("rules_said") or "")[:120], _now()))
    return {"ok": True, "id": oid}


def delete_override(oid):
    init()
    db.write("DELETE FROM journal_overrides WHERE id=?", (oid,))
    return {"ok": True}


def save_review(b):
    init()
    db.write("INSERT OR REPLACE INTO journal_reviews VALUES (?,?,?,?,?,?)", (b["decision"], (b.get("cause") or "")[:300], (b.get("emotion") or "")[:120],
             (b.get("rule_broken") or "")[:120], (b.get("lesson") or "")[:300], _now()))
    return {"ok": True}


def log_plan(items, sess=None):
    """What Trade plan said about each open trade, as it stood when last looked at that session. A plan is worked out in the browser,
    so the page sends it; the fills that follow show whether it was followed."""
    from .recorder import session_date
    init()
    sess = sess or session_date().isoformat()
    have = {r["trade_key"]: (r["act"], r["label"], r["adj"]) for r in db.query("SELECT * FROM journal_planlog WHERE date=?", (sess,))}
    rows = [(sess, i["key"], i.get("act"), i.get("label"), i.get("adj"), i.get("pct"), _now()) for i in items or []
            if i.get("key") and have.get(i["key"]) != (i.get("act"), i.get("label"), i.get("adj"))]  # an unchanged plan changes nothing, so it doesn't rebuild the page or the snapshot
    if rows:
        db.write("INSERT OR REPLACE INTO journal_planlog VALUES (?,?,?,?,?,?,?)", rows, many=True)
    return {"ok": True, "n": len(rows)}


def export_manual():
    init()
    return {"version": 1, "exported": _now(), "tables": manual()}


def import_manual(body):
    """Put an export back. Rows with the same key are replaced by the file's; nothing else is touched."""
    init()
    n = 0
    for table, rows in (body.get("tables") or {}).items():
        if table in MANUAL and rows:
            cols = [r["name"] for r in db.query(f"PRAGMA table_info({table})")]
            db.write(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [[r.get(c) for c in cols] for r in rows], many=True)
            n += len(rows)
    return {"ok": True, "rows": n}


def snapshot_open():
    """Record every open trade's marked P&L for the current session (called after each TWS refresh)."""
    from .recorder import close_capture, session_date
    from .risk import payload
    init()
    pl = payload()
    if not pl.get("marks_ts"):
        return 0
    sess = session_date().isoformat()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = []
    kept = {r["trade_key"] for r in db.query("SELECT trade_key FROM trade_pnl WHERE date=? AND updated>=?", (sess, close_capture(sess)))}
    for t in pl["trades"]:
        legs = t["legs"]
        if t["id"] in kept or not legs or any(not (lg.get("mark") or {}).get("mid") is not None for lg in legs):
            continue  # only fully marked trades: a missing leg would distort the path
        unreal = sum((lg["mark"]["mid"] - (lg["open_price"] or 0)) * lg["qty"] * 100 for lg in legs)
        rows.append((sess, t["id"], t["name"], t.get("ib_account"), t["underlying"], round((t.get("one_pnl") or 0) + unreal, 2), t.get("margin"), now))
    if rows:
        db.write("INSERT OR REPLACE INTO trade_pnl VALUES (?,?,?,?,?,?,?,?)", rows, many=True)
    return len(rows)
