"""Heads-up for event-driven gap risk: who reports and what's released next, where futures stand overnight, which
leaders broke, and how many stress signals are firing. Information only: the size call, gates, rankings and Today's
pick never read this module.

Every source sits on its own clock and keeps its last good copy, so a failure shows as an old timestamp or
"feed unavailable", never as a calm reading:
* weights: State Street's daily SPY and XLK holdings files (S&P 500 weights; market-cap share if they fail);
* holdings: yfinance's top holdings of SMH;
* scan: TradingView's stock scanner (earnings dates, after-hours moves) for the S&P 500, the SOX and the top of the
  Russell 2000. Dates it marks unconfirmed are checked against Nasdaq's earnings calendar;
* futures: yfinance 5-minute bars for ES, NQ and RTY, each against its own price at the last cash close, because a
  future trades at a basis to cash;
* vx: CBOE's daily VIX futures settlements. End of day only: no free source gives them overnight.
"""
import datetime as dt
import io
import json
import re
import threading

import pandas as pd
import requests

from . import db, market
from .history import series
from .recorder import ET

UA = market.UA
RED_PCT, AMBER_PCT = 15, 5     # % of the S&P 500 reporting inside the window
TOP_KINDS = ("Payrolls", "CPI", "FOMC", "Election")
FUT_ALERT, AH_ALERT = 0.75, 5  # % moves that alert: index futures, a top-10 name out of hours
LEADER_SD, LEADER_PCT = 3, 7   # a leader's down day: σ of its last 60 sessions, or plain %
TOP_N, RUT_N, ETF_N = 10, 5, 8
ISSUER = {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA"}  # two share classes, one earnings report
FUTURES = {"ES=F": ("ES", "SPX"), "NQ=F": ("NQ", "NDX"), "RTY=F": ("RTY", "RUT")}
STRESS_BARS = ["CL=F", "^TNX", "DX-Y.NYB", "BTC-USD"]  # not in market.MARKET_SYMBOLS: the cloud build fails on a short history there
SCAN_COLS = ["name", "description", "market_cap_basic", "earnings_release_next_date", "earnings_release_next_time",
             "earnings_release_date", "premarket_change", "postmarket_change", "change", "close"]
SSGA = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{}.xlsx"
_lock = threading.Lock()


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(d):
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _when(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _box(key):
    raw = db.get_meta(f"heads:{key}")
    return json.loads(raw) if raw else {}


def _data(key, default=None):
    return _box(key).get("data", default)


def _source(key, fetch, every_min, force=False):
    """Refresh one source when it's due; a failure keeps the last good copy, records why and waits 5 minutes to retry."""
    box, now = _box(key), _now()
    age = lambda k: (now - _when(box[k])).total_seconds() / 60 if box.get(k) else 1e9  # noqa: E731
    if (age("ts") < every_min and not force) or age("tried") < (0.5 if force else 5):
        return
    box["tried"] = _iso(now)
    try:
        box.update(data=fetch(), ts=_iso(now), err=None)
    except Exception as e:
        box["err"] = f"{type(e).__name__}: {str(e)[:120]}"
    db.set_meta(f"heads:{key}", json.dumps(box))


# ------------------------------------------------------------------ sources
def parse_ssga(content):
    """State Street's holdings workbook to ({ticker: weight %}, as-of date)."""
    df = pd.read_excel(io.BytesIO(content), header=None)
    i = next(k for k in range(15) if str(df.iloc[k, 0]).strip().lower() == "name")
    h = df.iloc[i + 1:].copy()
    h.columns = [str(c).strip() for c in df.iloc[i]]
    w = {str(t).strip(): float(x) for t, x in zip(h["Ticker"], h["Weight"]) if isinstance(t, str) and t.strip() not in ("", "-") and pd.notna(x)}
    if len(w) < 20:
        raise ValueError("too few holdings")
    stamp = next((str(v) for v in df.iloc[:i, 1] if "as of" in str(v).lower()), "")
    m = re.search(r"\d{1,2}-[A-Za-z]{3}-\d{4}", stamp)
    return w, dt.datetime.strptime(m[0], "%d-%b-%Y").date().isoformat() if m else None


def _weights():
    out = {}
    for t in ("spy", "xlk"):
        r = requests.get(SSGA.format(t), headers=UA, timeout=30)
        r.raise_for_status()
        out[t], out[t + "_asof"] = parse_ssga(r.content)
    return out


def _holdings():
    import yfinance as yf
    with market.YF_LOCK:
        h = yf.Ticker("SMH").funds_data.top_holdings
    names = [str(s) for s in h.index[:ETF_N]]
    if not names:
        raise ValueError("no holdings")
    return names


def _scan_set(symbols, n):
    body = {"columns": SCAN_COLS, "symbols": symbols, "range": [0, n], "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}}
    r = requests.post("https://scanner.tradingview.com/america/scan", json=body, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json().get("data") or []


def parse_scan(rows, tag):
    out = {}
    for x in rows:
        v = dict(zip(SCAN_COLS, x["d"]))
        if v["name"]:
            out[v["name"]] = {"sym": v["name"], "name": v["description"], "cap": v["market_cap_basic"], "next": v["earnings_release_next_date"], "code": v["earnings_release_next_time"],
                              "last": v["earnings_release_date"], "pre": v["premarket_change"], "post": v["postmarket_change"], "chg": v["change"], "close": v["close"], "idx": [tag]}
    return out


def _scan():
    spx = parse_scan(_scan_set({"symbolset": ["SYML:SP;SPX"]}, 700), "SPX")
    if len(spx) < 400:
        raise ValueError(f"only {len(spx)} S&P 500 names")
    out = dict(spx)
    for tag, ss, n in (("RUT", "SYML:TVC;RUT", RUT_N), ("SOX", "SYML:NASDAQ;SOX", 60)):
        for sym, r in parse_scan(_scan_set({"symbolset": [ss]}, n), tag).items():
            out[sym] = {**r, "idx": out[sym]["idx"] + [tag]} if sym in out else r
    return out


def _nasdaq():
    """{symbol: [day, session]} for the next week: the cross-check on dates TradingView marks unconfirmed."""
    out, d = {}, _now().astimezone(ET).date()
    headers = {**UA, "Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    for k in range(8):
        day = (d + dt.timedelta(days=k)).isoformat()
        if dt.date.fromisoformat(day).weekday() >= 5:
            continue
        r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": day}, headers=headers, timeout=20)
        r.raise_for_status()
        for x in (r.json().get("data") or {}).get("rows") or []:
            out.setdefault(x["symbol"].replace("/", "."), [day, x.get("time") or ""])
    if not out:
        raise ValueError("empty calendar")
    return out


def _futures():
    import yfinance as yf
    from .updater import _last_close
    now = _now()
    close = _last_close(now)
    with market.YF_LOCK:
        df = yf.download(list(FUTURES), period="5d", interval="5m", prepost=True, auto_adjust=False, progress=False, group_by="ticker", threads=False)
    out = []
    for s, (name, idx) in FUTURES.items():
        c = df[s]["Close"].dropna()
        out.append({"sym": name, "index": idx, **move_since(c, close)})
    if not any(r["last"] for r in out):
        raise ValueError("no bars")
    return {"close": _iso(close), "rows": out}


def move_since(closes, close):
    """A future's change since the bar ending at the cash close, from a 5-minute close series (tz-aware index)."""
    empty = {"last": None, "ref": None, "chg": None, "at": None, "spark": []}
    if not len(closes):
        return empty
    before, after = closes[closes.index < close], closes[closes.index >= close]
    if not len(before):
        return empty
    ref, last = float(before.iloc[-1]), float(closes.iloc[-1])
    step = max(len(after) // 48, 1)
    return {"last": last, "ref": ref, "chg": 100 * (last / ref - 1), "at": _iso(closes.index[-1].to_pydatetime()),
            "spark": [round(100 * (float(v) / ref - 1), 3) for v in after.iloc[::step]]}


def parse_vx(text):
    """CBOE's settlement CSV to the monthly VIX futures [{sym, expiry, px}] (weeklies repeat the monthly's value)."""
    df = pd.read_csv(io.StringIO(text))
    df = df[df["Symbol"].astype(str).str.fullmatch(r"VX/[A-Z]\d")]
    rows = [{"sym": r["Symbol"], "expiry": str(r["Expiration Date"])[:10], "px": float(r["Price"])} for _, r in df.iterrows()]
    return sorted(rows, key=lambda r: r["expiry"])


def _vx():
    """The two latest settlement files: front vs second month, and the same spread the session before."""
    d, got = _now().astimezone(ET).date(), []
    for k in range(10):
        day = d - dt.timedelta(days=k)
        if day.weekday() >= 5:
            continue
        r = requests.get("https://www.cboe.com/us/futures/market_statistics/settlement/csv", params={"dt": day.isoformat()}, headers=UA, timeout=20)
        rows = parse_vx(r.text) if r.status_code == 200 and r.text.startswith("Product") else []
        if len(rows) >= 2:
            got.append((day.isoformat(), rows))
        if len(got) == 2:
            break
    if not got:
        raise ValueError("no settlement file")
    day, rows = got[0]
    prev = got[1][1] if len(got) > 1 else None
    return {"date": day, "front": rows[0], "second": rows[1], "spread": rows[1]["px"] - rows[0]["px"], "prev_spread": prev[1]["px"] - prev[0]["px"] if prev else None}


def _bars():
    market.fetch_yf(leader_names() + STRESS_BARS, period="1y", max_age_h=0.4)
    return {"n": len(leader_names())}


def refresh(now=False):
    """Every source that is due; `now` also forces the two that move minute to minute. Failures stay in each source's box."""
    if not _lock.acquire(blocking=False):
        return {"running": True}
    try:
        _source("weights", _weights, 720)
        _source("holdings", _holdings, 1200)
        _source("scan", _scan, 8, force=now)
        _source("nasdaq", _nasdaq, 120)
        _source("futures", _futures, 8, force=now)
        _source("vx", _vx, 120)
        _source("bars", _bars, 25)
        return {"ok": True, "failed": [k for k in ("weights", "holdings", "scan", "nasdaq", "futures", "vx", "bars") if _box(k).get("err")]}
    finally:
        _lock.release()


def kick():
    """Background refresh when the page reads figures over 10 minutes old."""
    box = _box("futures")
    if (not box.get("ts") or (_now() - _when(box["ts"])).total_seconds() > 600) and not _lock.locked():
        threading.Thread(target=refresh, daemon=True).start()


# ------------------------------------------------------------------ who matters
def issuers(scan=None, w=None):
    """S&P 500 members by issuer with their weight: Alphabet's two share classes count as one."""
    scan = _data("scan", {}) if scan is None else scan
    w = (_data("weights") or {}).get("spy") or {} if w is None else w
    members = [r for r in scan.values() if "SPX" in r["idx"]]
    total = sum(r["cap"] or 0 for r in members) or 1
    out = {}
    for r in members:
        key = ISSUER.get(r["sym"], r["sym"])
        wt = w.get(r["sym"], 0.0) if w else 100.0 * (r["cap"] or 0) / total
        if key in out:
            out[key]["weight"] += wt
        else:
            out[key] = {**r, "sym": key, "weight": wt}
    return out


def leaders():
    """{symbol: why it's watched}: the top 10 S&P 500 issuers, the top 5 Russell 2000 names and the leaders of SMH and XLK."""
    iss, scan = issuers(), _data("scan", {})
    w = _data("weights") or {}
    out = {}
    for s in sorted(iss, key=lambda k: -iss[k]["weight"])[:TOP_N]:
        out.setdefault(s, []).append("SPX top 10")
    for s in [r["sym"] for r in scan.values() if "RUT" in r["idx"]][:RUT_N]:
        out.setdefault(s, []).append("RUT top 5")
    for s in (_data("holdings") or [])[:ETF_N]:
        out.setdefault(ISSUER.get(s, s), []).append("SMH")
    for s in sorted(w.get("xlk") or {}, key=lambda k: -w["xlk"][k])[:ETF_N]:
        out.setdefault(ISSUER.get(s, s), []).append("XLK")
    return out


def leader_names():
    return [market._yf_symbol(s) for s in leaders()]


# ------------------------------------------------------------------ event risk
def window_end(now, hours):
    """`hours` of trading-day time from now: weekends and market holidays don't use the window up, so Friday evening's
    24 hours reach Monday evening, and from a Saturday they cover the whole of Monday."""
    from .accounts import US_HOLIDAYS
    t, left = now.astimezone(ET), hours * 3600
    while True:
        midnight = dt.datetime.combine(t.date() + dt.timedelta(days=1), dt.time(0), tzinfo=ET)
        span = (midnight - t).total_seconds()
        if t.weekday() < 5 and t.date().isoformat() not in US_HOLIDAYS:
            if span >= left:
                return t + dt.timedelta(seconds=left)
            left -= span
        t = midnight


def report_time(r, nasdaq):
    """When a name reports: (UTC time, session, confirmed). TradingView's code 1 = after the close, -1 = before the open;
    0 is its estimate, so Nasdaq's date wins there."""
    if r.get("next") and r.get("code") in (1, -1):
        return dt.datetime.fromtimestamp(r["next"], dt.timezone.utc), "after close" if r["code"] == 1 else "before open", True
    hit = nasdaq.get(r["sym"]) or (nasdaq.get("BRK.A") if r["sym"].startswith("BRK") else None)
    if hit:
        at, session = {"time-after-hours": ("16:30", "after close"), "time-pre-market": ("08:00", "before open")}.get(hit[1], ("12:00", "time not set"))
        return dt.datetime.fromisoformat(f"{hit[0]}T{at}:00").replace(tzinfo=ET).astimezone(dt.timezone.utc), session, session != "time not set"
    if r.get("next"):
        return dt.datetime.fromtimestamp(r["next"], dt.timezone.utc), "estimated", False
    return None, None, False


def earnings_rows(now, iss=None, nasdaq=None, watched=None):
    """Upcoming reports over the next week, biggest first within each session."""
    iss = issuers() if iss is None else iss
    nasdaq = _data("nasdaq", {}) if nasdaq is None else nasdaq
    watched = leaders() if watched is None else watched
    scan = _data("scan", {})
    pool = {**{s: r for s, r in scan.items() if s in watched}, **iss}
    rows, end = [], window_end(now, 24 * 7)
    top = set(sorted(iss, key=lambda k: -iss[k]["weight"])[:TOP_N])
    for s, r in pool.items():
        when, session, firm = report_time(r, nasdaq)
        if when and now <= when <= end:
            us = when.astimezone(ET)
            rows.append({"sym": s, "name": r["name"], "when": _iso(when), "zones": market.two_zones(when) if firm else f"{us:%a} {us.day} {us:%b}, US date", "session": session, "firm": firm,
                         "weight": round(r.get("weight") or 0, 2), "top": s in top, "groups": watched.get(s, [])})
    return sorted(rows, key=lambda x: (x["when"], -x["weight"]))


def event_score(now, macro, earn, feeds):
    """Green, amber or red for the next sessions, or grey when a feed is down and nothing else says otherwise.
    feeds: {"macro": bool, "earnings": bool}."""
    w24, w48 = window_end(now, 24), window_end(now, 48)
    inw = lambda rows, key, end: [r for r in rows if now <= _when(r[key]) <= end]  # noqa: E731
    e24, e48 = inw(earn, "when", w24), inw(earn, "when", w48)
    m24, m48 = inw(macro, "date", w24), inw(macro, "date", w48)
    p24, p48 = sum(r["weight"] for r in e24), sum(r["weight"] for r in e48)
    top24, top48 = [m for m in m24 if m.get("kind") in TOP_KINDS], [m for m in m48 if m.get("kind") in TOP_KINDS]
    other = [m for m in m24 if m.get("importance", 0) >= 1 and m.get("kind") not in TOP_KINDS]
    big = [r for r in e24 if r["top"]]
    names = lambda rows: ", ".join(dict.fromkeys(r.get("title") or r["sym"] for r in rows))  # noqa: E731
    red, amber = [], []
    if p24 > RED_PCT:
        red.append(f"{p24:.1f}% of the S&P 500 reports within 24 trading hours")
    if top24:
        red.append(f"{names(top24)} within 24 trading hours")
    if not red:
        if p24 >= AMBER_PCT:
            amber.append(f"{p24:.1f}% of the S&P 500 reports within 24 trading hours")
        if big:
            amber.append(f"top-10 name reporting within 24 trading hours: {names(big)}")
        if top48:
            amber.append(f"{names(top48)} within 48 trading hours")
        if other:
            amber.append(f"high-impact release within 24 trading hours: {names(other)}")
        if p48 > RED_PCT:
            amber.append(f"{p48:.1f}% of the S&P 500 reports within 48 trading hours")
    down = [k for k, up in (("macro calendar", feeds.get("macro")), ("earnings", feeds.get("earnings"))) if not up]
    level = "red" if red else "amber" if amber else "unknown" if down else "green"
    why = red or amber or ([f"{' and '.join(down)} feed unavailable, so a quiet reading can't be trusted"] if down else ["no top-tier release or heavy earnings in the next two sessions"])
    return {"level": level, "why": why, "pct24": round(p24, 1), "pct48": round(p48, 1), "w24": _iso(w24), "w48": _iso(w48), "feeds_down": down}


def by_session(earn, n=5):
    """% of the S&P 500 reporting per trading day, split before the open and after the close, for the chart."""
    days = {}
    for r in earn:
        d = _when(r["when"]).astimezone(ET).date().isoformat()
        x = days.setdefault(d, {"day": d, "pre": 0.0, "post": 0.0})
        x["pre" if r["session"] == "before open" else "post"] += r["weight"]
    return [{**d, "pre": round(d["pre"], 2), "post": round(d["post"], 2)} for d in sorted(days.values(), key=lambda x: x["day"])[:n]]


# ------------------------------------------------------------------ overnight
def session(now):
    """Which quote counts now: premarket 04:00-09:30 ET on weekdays, regular hours, otherwise the after-hours session."""
    t = now.astimezone(ET)
    if t.weekday() >= 5:
        return "post"
    return "pre" if dt.time(4) <= t.time() < dt.time(9, 30) else "regular" if dt.time(9, 30) <= t.time() < dt.time(16) else "post"


def overnight(now, top=None):
    fut, vx = _data("futures"), _data("vx")
    iss = issuers()
    top = top or sorted(iss.values(), key=lambda r: -r["weight"])[:TOP_N]
    sess = session(now)
    label = {"pre": "premarket", "post": "after hours", "regular": "regular session"}[sess]
    movers, alerts = [], []
    for r in top:
        v = r.get(sess) if sess != "regular" else r.get("chg")
        hot = sess != "regular" and v is not None and abs(v) > AH_ALERT
        movers.append({"sym": r["sym"], "name": r["name"], "weight": round(r["weight"], 2), "move": v, "alert": hot})
        if hot:
            alerts.append(f"{r['sym']} {v:+.1f}% {label}")
    rows = []
    for f in (fut or {}).get("rows", []):
        s = series(f["index"]).dropna()
        cash = float(s.iloc[-1]) if len(s) else None
        hot = f["chg"] is not None and abs(f["chg"]) > FUT_ALERT
        rows.append({**f, "cash": cash, "implied": cash * (1 + f["chg"] / 100) if cash and f["chg"] is not None else None, "alert": hot})
        if hot:
            alerts.append(f"{f['sym']} {f['chg']:+.2f}% since the cash close")
    return {"session": label, "close": (fut or {}).get("close"), "futures": rows, "vx": vx, "movers": movers, "alerts": alerts}


def gaps_now():
    """{index: % since the cash close} for the Risk grid's gap what-if."""
    fut = _data("futures") or {}
    return {"ts": _box("futures").get("ts"), "chg": {f["index"]: f["chg"] for f in fut.get("rows", []) if f.get("chg") is not None}}


# ------------------------------------------------------------------ leader spillover
def leader_moves(closes, sessions=2):
    """A close series to its last sessions' moves: [{date, ret, z}], σ from the 60 sessions before each day."""
    r = 100 * closes.pct_change().dropna()
    out = []
    for k in range(sessions):
        i = len(r) - 1 - k
        if i < 30:
            break
        sd = r.iloc[max(0, i - 60):i].std()
        out.append({"date": str(r.index[i]), "ret": round(float(r.iloc[i]), 2), "z": round(float(r.iloc[i] / sd), 2) if sd else None})
    return out


def is_break(m):
    return m["ret"] <= -LEADER_PCT or (m["z"] is not None and m["z"] <= -LEADER_SD)


def last_session(now):
    """The last session whose 16:00 ET close has passed, as an ISO date."""
    from .accounts import US_HOLIDAYS
    t = now.astimezone(ET)
    d = t.date() if t.time() >= dt.time(16, 0) else t.date() - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in US_HOLIDAYS:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def live_breaks(moves, now):
    """Breaks that still count. A break flags the next session, so it expires at that session's close."""
    fresh = last_session(now)
    return [m for m in moves if is_break(m) and m["date"] >= fresh]


def _day(d):
    d = dt.date.fromisoformat(str(d)[:10])
    return f"{d:%a} {d.day} {d:%b}"


def spillover(now=None):
    """Each leader's last two sessions. A live break by a top-10 issuer or SMH is an alert; the other leaders are shown only."""
    now = now or _now()
    who, iss = leaders(), issuers()
    names = list(who) + ["SMH"]
    last = db.query("SELECT MAX(date) d FROM bars_daily WHERE symbol='SPY'")[0]["d"] if names else None
    rows, alerts = [], []
    for s in names:
        y = market._yf_symbol(s)
        b = db.query("SELECT date, c FROM bars_daily WHERE symbol=? ORDER BY date DESC LIMIT 90", (y,))
        if len(b) < 40:
            continue
        c = pd.Series({r["date"]: r["c"] for r in reversed(b)})
        mv = leader_moves(c)
        if not mv:
            continue
        counts = s == "SMH" or "SPX top 10" in who.get(s, [])
        hit = live_breaks(mv, now)
        old = [m for m in mv if is_break(m) and m not in hit]
        rows.append({"sym": s, "groups": who.get(s, ["ETF"]), "weight": round(iss[s]["weight"], 2) if s in iss else None, "moves": mv, "alert": bool(hit) and counts, "broke": bool(hit),
                     "expired": _day(old[0]["date"]) if old else None})
        if hit and counts:
            m = hit[0]
            alerts.append(f"{s} {m['ret']:+.1f}% on {_day(m['date'])}" + (f" ({m['z']:+.1f}σ)" if m["z"] is not None else ""))
    rows.sort(key=lambda r: (not r["alert"], r["moves"][0]["z"] if r["moves"][0]["z"] is not None else 0))
    return {"date": last, "rows": rows, "alerts": alerts}


# ------------------------------------------------------------------ stress combo
def _bars_close(sym, idx):
    rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=?", (sym,))
    return pd.Series({r["date"]: r["c"] for r in rows}, dtype=float).sort_index().reindex(idx, method="ffill") if rows else pd.Series(index=idx, dtype=float)


def stress_frame(sessions=330):
    """One row per S&P session: the readings and whether each signal fired. Cross-assets are taken at the S&P's sessions, so
    BTC's weekend moves land on Monday. Rules are one-sided where only one side is stress (HYG, BTC)."""
    idx = series("SPX").dropna().index[-sessions:]
    ix = lambda s: series(s).dropna().reindex(idx, method="ffill")  # noqa: E731
    v9, v3, vv, sk, ad, nl = ix("VIX9D"), ix("VIX3M"), ix("VVIX"), ix("SKEW"), ix("BR.SPX.AD"), ix("BR.SPX.NL")
    spy, rsp, hyg = _bars_close("SPY|adj", idx), _bars_close("RSP|adj", idx), _bars_close("HYG|adj", idx)
    r93 = v9 / v3
    rel = (rsp / spy).pct_change(5) * 100
    spy5 = spy.pct_change(5) * 100
    z = lambda x, n=60: (x / x.rolling(n).std().shift(1))  # noqa: E731
    skd = sk.diff()
    fired = pd.DataFrame({
        "ts_up": (r93.diff() > 0) & (r93.diff().shift(1) > 0) & (r93.diff(2) >= 0.05),
        "vvix": (vv >= 100) | (vv.pct_change() * 100 >= 10),
        "skew": (skd / skd.rolling(120).std().shift(1)).abs() >= 2,
        "rsp": (spy5 >= 0) & (rel <= -(rel.rolling(250, min_periods=120).std())),
        "ad": (spy5 > 0) & (ad.rolling(5).sum() < 0),
        "lows": nl >= 5,
        "oil": z(_bars_close("CL=F", idx).pct_change()).abs() >= 2,
        "tnx": z(_bars_close("^TNX", idx).diff()).abs() >= 2,
        "dxy": z(_bars_close("DX-Y.NYB", idx).pct_change()).abs() >= 2,
        "hyg": z(hyg.pct_change()) <= -2,
        "btc": z(_bars_close("BTC-USD", idx).pct_change()) <= -2,
    }, index=idx)
    read = {"ts_up": r93, "vvix": vv, "skew": sk, "rsp": rel, "ad": ad.rolling(5).sum(), "lows": nl, "oil": _bars_close("CL=F", idx).pct_change() * 100, "tnx": _bars_close("^TNX", idx).diff() * 100,
            "dxy": _bars_close("DX-Y.NYB", idx).pct_change() * 100, "hyg": hyg.pct_change() * 100, "btc": _bars_close("BTC-USD", idx).pct_change() * 100}
    return fired, pd.DataFrame(read, index=idx)


SIGNALS = {  # id: (group, name, how it fires, reading format)
    "ts_up": ("Vol curve", "VIX9D/VIX3M rising", "up two sessions running, by 0.05 or more", "{:.3f}"),
    "vvix": ("Vol curve", "VVIX", "100 or higher, or up 10% in a day", "{:.1f}"),
    "skew": ("Vol curve", "SKEW change", "a day's change of 2σ or more, either way", "{:.1f}"),
    "rsp": ("Breadth", "RSP lagging SPY", "SPY flat or up over 5 sessions while RSP lags it by 1σ or more", "{:+.2f}% vs SPY, 5 days"),
    "ad": ("Breadth", "Advance/decline divergence", "SPY up over 5 sessions, net advancers negative (S&P 500 members)", "{:+.0f} pts, 5-day sum"),
    "lows": ("Breadth", "New 52-week lows", "5% or more of S&P 500 members", "{:.1f}% of members"),
    "oil": ("Cross-asset", "Oil", "a 2σ day, either way", "{:+.1f}%"),
    "tnx": ("Cross-asset", "10-year yield", "a 2σ day, either way", "{:+.1f} bp"),
    "dxy": ("Cross-asset", "Dollar index", "a 2σ day, either way", "{:+.2f}%"),
    "hyg": ("Cross-asset", "High yield (HYG)", "a 2σ down day", "{:+.2f}%"),
    "btc": ("Cross-asset", "Bitcoin", "a 2σ down day", "{:+.1f}%"),
}
STRESS_AMBER, STRESS_RED = 3, 5


def stress():
    fired, read = stress_frame()
    if not len(fired):
        return {"n": None, "of": len(SIGNALS), "signals": [], "hist": [], "no_data": []}
    last = read.iloc[-1]
    sig = []
    for k, (group, name, rule, f) in SIGNALS.items():
        v = last[k]
        have = pd.notna(v)
        sig.append({"id": k, "group": group, "name": name, "rule": rule, "on": bool(fired[k].iloc[-1]) if have else None, "reading": f.format(float(v)) if have else "no data"})
    n = fired.sum(axis=1)
    year = n.iloc[-252:]
    rate = fired.iloc[-252:].mean() * 100
    for s in sig:
        s["rate"] = round(float(rate[s["id"]]), 1)
    now_n = int(n.iloc[-1])
    return {"n": now_n, "of": sum(1 for s in sig if s["on"] is not None), "date": str(fired.index[-1]), "signals": sig, "level": "red" if now_n >= STRESS_RED else "amber" if now_n >= STRESS_AMBER else "calm",
            "pct": round(100.0 * float((year < now_n).mean())), "hist": [{"d": str(d), "n": int(v)} for d, v in n.iloc[-30:].items()], "no_data": [s["name"] for s in sig if s["on"] is None]}


# ------------------------------------------------------------------ the page's one read
def feeds(cal):
    """Each source's state for the page and the Data check: a source is down when it has no copy, or the last try failed."""
    out = {}
    for key, name, stale_h in (("scan", "Earnings and after-hours (TradingView)", 26), ("nasdaq", "Earnings cross-check (Nasdaq)", 72), ("weights", "S&P 500 weights (State Street)", 96),
                               ("holdings", "SMH holdings (yfinance)", 200), ("futures", "Index futures (yfinance)", 26), ("vx", "VIX futures settlements (CBOE)", 96)):
        b = _box(key)
        age = (_now() - _when(b["ts"])).total_seconds() / 3600 if b.get("ts") else None
        out[key] = {"name": name, "ts": b.get("ts"), "err": b.get("err"), "ok": age is not None and age <= stale_h}
    out["calendar"] = {"name": "Economic calendar", "ts": None, "err": None, "ok": cal["feed"] != "unavailable", "state": cal["feed"], "note": cal.get("note") or ""}
    return out


def week_end(now):
    """The end of the ET week being traded: from Saturday on, the week ahead."""
    d = now.astimezone(ET).date()
    if d.weekday() >= 5:
        d += dt.timedelta(days=7 - d.weekday())
    return dt.datetime.combine(d + dt.timedelta(days=6 - d.weekday()), dt.time(23, 59), tzinfo=ET)


def payload(now=None):
    """Reads cached copies only, so any request can call it."""
    now = now or _now()
    d0 = now.astimezone(dt.timezone.utc).date()
    cal = market.calendar(d0.isoformat(), (d0 + dt.timedelta(days=14)).isoformat(), widen=False, fetch=False)
    macro = [r for r in cal["result"] if _when(r["date"]) >= now]
    earn = earnings_rows(now)
    f = feeds(cal)
    score = event_score(now, macro, earn, {"macro": f["calendar"]["ok"], "earnings": f["scan"]["ok"]})
    sp = spillover(now)
    st = stress()
    night = overnight(now)
    return {"ts": _box("futures").get("ts") or _box("scan").get("ts"), "now": _iso(now), "score": score, "macro": macro, "earnings": earn, "sessions": by_session(earn), "overnight": night, "leaders": sp,
            "stress": st, "feeds": f, "feed_note": cal.get("note") or "", "live_to": cal.get("live_to"), "known_to": market.known_to(), "coming_to": window_end(now, 72).isoformat(), "week_to": week_end(now).isoformat(), "weights_asof": (_data("weights") or {}).get("spy_asof"),
            "alerts": night["alerts"] + sp["alerts"]}
