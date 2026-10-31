"""Market data for the Market tab (the former claude.ai Market Desk), from free local sources.

* Daily bars: IBKR for indexes and the VIX family when TWS is up (CBOE CSVs as history/fallback);
  yfinance for ETFs and ES futures (consolidated volume, as on TradingView). Cached in SQLite.
* Breadth: computed here from S&P 500 / Nasdaq-100 members (Wikipedia lists + yfinance closes):
  % of members above their 20/50/200-day SMA, overall and per GICS sector.
* Economic calendar: Forex Factory's weekly JSON (US events, high/medium impact) for its own week, TradingView's
  calendar after that, and the official schedules in KNOWN wherever neither has the event. Release dates further
  out: the Fed's meeting page and TradingView's calendar, cached by refresh_releases().
* Account: TWS (read-only), every managed sub-account.

Symbols arrive in the TradingView form the page already used (e.g. AMEX:SPY, INDEX:S5FI) and are
mapped to these sources.
"""
import datetime as dt
import io
import json
import re
import threading
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from . import db
from .history import series

UA = {"User-Agent": "Mozilla/5.0"}
ET = ZoneInfo("America/New_York")
SECTOR_CODES = {"SKFI": "Information Technology", "SFFI": "Financials", "SLFI": "Communication Services",
                "SYFI": "Consumer Discretionary", "SIFI": "Industrials", "SVFI": "Health Care",
                "SPFI": "Consumer Staples", "SEFI": "Energy", "SUFI": "Utilities", "SSFI": "Real Estate",
                "SBFI": "Materials"}
BREADTH = {"S5TW": "BR.SPX.20", "S5FI": "BR.SPX.50", "S5TH": "BR.SPX.200", "NDFI": "BR.NDX.50", "NDTW": "BR.NDX.20", "NDTH": "BR.NDX.200"}
for code, sec in SECTOR_CODES.items():
    BREADTH[code] = f"BR.SPX.{sec}.50"
CBOE_SYMS = {"VIX", "VIX9D", "VIX3M", "VIX6M", "VIX1Y", "SKEW", "VVIX", "RVX", "VXN", "SPX", "RUT", "NDX"}  # index_daily: official CBOE closes, IBKR for newer days
_lock = threading.Lock()
# yfinance keeps downloads in shared module state: two downloads running at once (scheduler thread + page
# requests) swap each other's rows (seen: ES prices stored under XLK, EEM's under ES). One at a time.
YF_LOCK = threading.RLock()


def _clean(sub):
    """Drop rows whose close jumps >40% against both neighbours (a row from another symbol)."""
    c = sub["Close"]
    prev, nxt = c.shift(1), c.shift(-1)
    bad = ((c / prev - 1).abs() > 0.4) & ((c / nxt - 1).abs() > 0.4)
    return sub[~bad.fillna(False)]
status = {"breadth_running": False, "log": []}


def _log(m):
    status["log"] = (status["log"] + [f"{dt.datetime.now():%H:%M:%S}  {m}"])[-40:]


def _init():
    db.write("""CREATE TABLE IF NOT EXISTS bars_daily (symbol TEXT, date TEXT, o REAL, h REAL, l REAL, c REAL, v REAL,
                PRIMARY KEY (symbol, date))""")


def _yf_symbol(tv):
    ex, _, tk = tv.partition(":") if ":" in tv else ("", "", tv)
    if tk.upper() in ("ES1!",):
        return "ES=F"
    if tk.upper() in ("NQ1!",):
        return "NQ=F"
    return tk.replace(".", "-").upper()


def fetch_yf(symbols, period="2y", max_age_h=6, force=False):
    """Refresh yfinance daily bars for the given yfinance tickers when stale."""
    import yfinance as yf
    _init()
    need = []
    for s in symbols:
        last = db.get_meta(f"yf:{s}")
        if force or not last or dt.datetime.fromisoformat(last) < dt.datetime.now() - dt.timedelta(hours=max_age_h):
            need.append(s)
    if not need:
        return 0
    with YF_LOCK:
        df = yf.download(need, period=period, auto_adjust=False, progress=False, threads=True, group_by="ticker")
    n = 0
    for s in need:
        try:
            sub = df[s] if len(need) > 1 else df
            if isinstance(sub.columns, pd.MultiIndex):
                sub = sub.droplevel(0, axis=1)
            sub = _clean(sub.dropna(subset=["Close"]))
        except KeyError:
            continue
        rows = [(s, d.strftime("%Y-%m-%d"), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]),
                 float(r["Volume"]) if pd.notna(r["Volume"]) else 0.0) for d, r in sub.iterrows()]
        # dividend-adjusted copy (OHLC scaled by Adj Close / Close) for return and ratio work: raw closes on
        # distribution-paying ETFs (HYG, TLT, AGG, IEF...) drop on every ex-date and fake a credit/rates move
        if "Adj Close" in sub.columns:
            adj = []
            for d, r in sub.iterrows():
                f = float(r["Adj Close"]) / float(r["Close"]) if pd.notna(r["Adj Close"]) and r["Close"] else 1.0
                adj.append((s + "|adj", d.strftime("%Y-%m-%d"), float(r["Open"]) * f, float(r["High"]) * f, float(r["Low"]) * f,
                            float(r["Adj Close"]) if pd.notna(r["Adj Close"]) else float(r["Close"]),
                            float(r["Volume"]) if pd.notna(r["Volume"]) else 0.0))
            db.write("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?)", adj, many=True)
        if rows:
            db.write("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?)", rows, many=True)
            db.set_meta(f"yf:{s}", dt.datetime.now().isoformat(timespec="seconds"))
            n += 1
    return n


def fetch_yf_max(symbols):
    """Full history once a day (the regular refresh only pulls 2 years); used by the studies."""
    need = [x for x in symbols if db.get_meta(f"yfmax:{x}") != dt.date.today().isoformat()]
    if need:
        fetch_yf(need, period="max", force=True)
        for x in need:
            db.set_meta(f"yfmax:{x}", dt.date.today().isoformat())


def _frame(sym):
    rows = db.query("SELECT date, o, h, l, c, v FROM bars_daily WHERE symbol=? ORDER BY date", (sym,))
    if not rows:
        return None
    return pd.DataFrame(rows).set_index("date")


def _close_frame(name):
    s = series(name).dropna()
    if not len(s):
        return None
    return pd.DataFrame({"o": s, "h": s, "l": s, "c": s, "v": 0.0})


def ohlcv(tv_symbol, interval="1D", count=300, adj=False):
    """Bars in the same column shape the Market page expects: {t,o,h,l,c,v} (t = unix seconds)."""
    ex, _, tk = tv_symbol.partition(":")
    tk = tk or ex
    if ex == "INDEX" and tk in BREADTH:
        df = _close_frame(BREADTH[tk])
        if df is None:
            raise LookupError(f"{tv_symbol}: breadth not computed yet (it builds in the background after start-up).")
    elif tk in CBOE_SYMS:
        df = _close_frame(tk)
        if df is None:
            raise LookupError(f"{tv_symbol}: no CBOE history yet.")
    elif ex == "INDEX":
        raise LookupError(f"{tv_symbol} is not available from free sources.")
    else:
        y = _yf_symbol(tv_symbol)
        fetch_yf([y])
        df = (_frame(y + "|adj") if adj else None)
        if df is None:
            df = _frame(y)
        if df is None:
            raise LookupError(f"{tv_symbol}: no data from yfinance (check the ticker).")
    if interval == "1W":
        idx = pd.to_datetime(df.index)
        w = df.set_axis(idx).resample("W-FRI").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}).dropna(subset=["c"])
        w.index = [(d - pd.Timedelta(days=4)).strftime("%Y-%m-%d") for d in w.index]  # week starts Monday, like TradingView
        df = w
    df = df.iloc[-int(count):]
    t = [int(dt.datetime.strptime(d, "%Y-%m-%d").replace(hour=13, minute=30, tzinfo=dt.timezone.utc).timestamp()) for d in df.index]
    return {"success": True, "symbol": tv_symbol, "bars": {"t": t, "o": df["o"].round(4).tolist(), "h": df["h"].round(4).tolist(),
            "l": df["l"].round(4).tolist(), "c": df["c"].round(4).tolist(), "v": df["v"].tolist()}}


# ------------------------------------------------------------------ breadth
def _members():
    html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=UA, timeout=30).text
    sp = pd.read_html(io.StringIO(html))[0]
    sp_members = {r["Symbol"].replace(".", "-"): r["GICS Sector"] for _, r in sp.iterrows()}
    ndx_members = []
    try:
        html = requests.get("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", headers=UA, timeout=30).text
        for t in pd.read_html(io.StringIO(html)):
            col = next((c for c in t.columns if str(c).lower() in ("ticker", "symbol")), None)
            if col is not None and 90 <= len(t) <= 110:
                ndx_members = [str(x).replace(".", "-") for x in t[col]]
                break
    except Exception as e:
        _log(f"Nasdaq-100 list failed: {e}")
    return sp_members, ndx_members


def refresh_breadth(force=False):
    last = db.get_meta("breadth_refreshed")
    if not force and last and dt.datetime.fromisoformat(last) > dt.datetime.now() - dt.timedelta(hours=10):
        return {"skipped": True}
    if not _lock.acquire(blocking=False):
        return {"running": True}
    status["breadth_running"] = True
    try:
        import yfinance as yf
        sp, ndx = _members()
        tickers = sorted(set(sp) | set(ndx))
        _log(f"breadth: downloading {len(tickers)} members")
        with YF_LOCK:
            px = yf.download(tickers, period="2y", auto_adjust=False, progress=False, threads=True)["Close"]
        px = px.dropna(how="all")
        rows = []

        def pct_above(cols, n):
            sub = px[[c for c in cols if c in px.columns]]
            ma = sub.rolling(n).mean()
            valid = sub.notna() & ma.notna()
            above = (sub > ma) & valid
            share = 100.0 * above.sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
            return share.dropna()

        for n in (20, 50, 200):
            for d, v in pct_above(list(sp), n).items():
                rows.append((f"BR.SPX.{n}", d.strftime("%Y-%m-%d"), float(v)))
            if ndx:
                for d, v in pct_above(ndx, n).items():
                    rows.append((f"BR.NDX.{n}", d.strftime("%Y-%m-%d"), float(v)))
        for sec in sorted(set(sp.values())):
            cols = [t for t, s in sp.items() if s == sec]
            for d, v in pct_above(cols, 50).items():
                rows.append((f"BR.SPX.{sec}.50", d.strftime("%Y-%m-%d"), float(v)))
        # S&P 500 members' net advancers and new 52-week lows, % of members: the free stand-in for NYSE/Nasdaq A/D
        sub = px[[c for c in sp if c in px.columns]]
        chg, n = sub.diff(), sub.notna().sum(axis=1).replace(0, np.nan)
        net = (100.0 * ((chg > 0).sum(axis=1) - (chg < 0).sum(axis=1)) / n).iloc[1:]
        lows = (100.0 * (sub <= sub.rolling(252, min_periods=200).min()).sum(axis=1) / n).iloc[200:]
        rows += [("BR.SPX.AD", d.strftime("%Y-%m-%d"), float(v)) for d, v in net.dropna().items()]
        rows += [("BR.SPX.NL", d.strftime("%Y-%m-%d"), float(v)) for d, v in lows.dropna().items()]
        db.write("INSERT OR REPLACE INTO index_daily (symbol, date, close) VALUES (?,?,?)", rows, many=True)
        db.set_meta("breadth_refreshed", dt.datetime.now().isoformat(timespec="seconds"))
        db.set_meta("breadth_members", json.dumps({"spx": len(sp), "ndx": len(ndx)}))
        _log(f"breadth: stored {len(rows)} points ({len(sp)} S&P 500, {len(ndx)} Nasdaq-100 members)")
        return {"ok": True, "points": len(rows)}
    except Exception as e:
        _log(f"breadth failed: {e}")
        return {"error": str(e)}
    finally:
        status["breadth_running"] = False
        _lock.release()


MARKET_SYMBOLS = ["SPY", "RSP", "ES=F", "QQQ", "IWM", "XLK", "XLF", "XLC", "XLY", "XLI", "XLV", "XLP", "XLE", "XLU",
                  "XLRE", "XLB", "SMH", "XHB", "HYG", "TLT", "WOOD", "GLD", "EEM", "AGG", "IEF"]


def refresh_all(force=False):
    from . import ibdata
    try:
        ibdata.refresh(force=force)  # VIX family and indexes from IBKR when TWS is up
    except Exception as e:
        _log(f"IBKR index bars failed: {e}")
    fetch_yf(MARKET_SYMBOLS, force=force)
    return refresh_breadth(force=force)


# ------------------------------------------------------------------ economic calendar
# Official schedules, read from bls.gov and federalreserve.gov on 2026-11-01. The fallback when the feeds fail, and the
# only source for the election. Extend each year: the Data check warns when under 60 days are left.
KNOWN = {
    "CPI": ("08:30", "CPI (schedule)", ["2026-11-10", "2026-12-10", "2027-01-13", "2027-02-11", "2027-03-10", "2027-04-13", "2027-05-12",
                                        "2027-06-10", "2027-07-14", "2027-08-11", "2027-09-14", "2027-10-14", "2027-11-10", "2027-12-10"]),
    "Payrolls": ("08:30", "Nonfarm payrolls (schedule)", ["2026-11-06", "2026-12-04", "2027-01-08", "2027-02-05", "2027-03-05", "2027-04-02", "2027-05-07",
                                                          "2027-06-04", "2027-07-02", "2027-08-06", "2027-09-03", "2027-10-08", "2027-11-05", "2027-12-03"]),
    "FOMC": ("14:00", "FOMC decision (schedule)", ["2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
                                                   "2027-10-27", "2027-12-08"]),
    "Election": ("19:00", "US midterm election", ["2026-11-03"]),  # first polls close: the night's results are the event
}
_ff_tried = None  # Forex Factory's last attempt: a failure isn't stored, so without this every request would retry it
FF_RETRY = dt.timedelta(minutes=30)


def _zulu(d):
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def known_events():
    """KNOWN as calendar rows, plus any FOMC day on the Fed's own page."""
    rows = []
    fed = json.loads(db.get_meta("fed:fomc") or "[]")
    for kind, (at, title, days) in KNOWN.items():
        for day in sorted(set(days) | set(fed if kind == "FOMC" else ())):
            when = dt.datetime.fromisoformat(f"{day}T{at}:00").replace(tzinfo=ET)
            rows.append({"date": _zulu(when), "title": title, "importance": 1, "kind": kind, "source": "schedule", "forecast": None, "previous": None, "actual": None, "period": ""})
    return rows


def known_to():
    """Last day the hard-coded schedules reach: the earliest of their ends, so no kind runs out unnoticed."""
    return min((max(days) for kind, (_, _, days) in KNOWN.items() if kind != "Election"), default=None)


def _forex_factory(fetch=True):
    """Forex Factory's current week (the only file left: its next-week and last-week files return 404 and this one
    keeps the old week until Sunday, US time). Returns (rows, day the feed ends or None)."""
    global _ff_tried
    key = "ff:thisweek"
    cached, stamp = db.get_meta(key), db.get_meta(key + ":ts")
    fresh = stamp and dt.datetime.fromisoformat(stamp) > dt.datetime.now() - dt.timedelta(hours=2)
    if fetch and not fresh and (_ff_tried is None or dt.datetime.now() - _ff_tried > FF_RETRY):
        _ff_tried = dt.datetime.now()
        try:
            r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", headers=UA, timeout=20)
            if r.status_code == 200:
                cached = r.text
                db.set_meta(key, cached)
                db.set_meta(key + ":ts", dt.datetime.now().isoformat(timespec="seconds"))
        except Exception:
            pass
    try:
        events = json.loads(cached) if cached else []
    except ValueError:
        events = []
    rows, seen = [], set()
    for e in events:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        k = (e["title"], e["date"])
        if k in seen:
            continue
        seen.add(k)
        rows.append({"date": _zulu(dt.datetime.fromisoformat(e["date"])), "title": e["title"], "importance": 1 if e["impact"] == "High" else 0, "kind": _release_kind(e["title"]),
                     "source": "ff", "forecast": e.get("forecast") or None, "previous": e.get("previous") or None, "actual": e.get("actual") or None, "period": ""})
    return rows, (max(e["date"] for e in events)[:10] if events else None)


def _merged(fetch=True):
    """Forex Factory for its week, TradingView after it, the official schedule wherever neither has the event.
    Returns (rows, how far a live feed reaches)."""
    ff, ff_to = _forex_factory(fetch)
    tv = json.loads(db.get_meta("tv:events") or "[]")
    tv = [r for r in tv if (not ff_to or r["date"][:10] > ff_to) and "election" not in r["title"].lower()]  # date-only row: KNOWN has the time
    rows = ff + tv
    have = {(r["date"][:10], r.get("kind")) for r in rows}
    rows += [r for r in known_events() if (r["date"][:10], r["kind"]) not in have]
    ts = db.get_meta("tv:events:ts")
    tv_on = bool(tv) and bool(ts) and dt.datetime.fromisoformat(ts) > dt.datetime.now() - dt.timedelta(days=3)
    tv_to = max((r["date"][:10] for r in tv), default=None) if tv_on else None
    return sorted(rows, key=lambda r: r["date"]), max(filter(None, (ff_to, tv_to)), default=None)


def calendar(date_from=None, date_to=None, widen=True, fetch=True):
    rows, live_to = _merged(fetch)
    today = dt.datetime.now(dt.timezone.utc).date()
    lo = dt.datetime.fromisoformat(date_from).date() if date_from else None
    hi = dt.datetime.fromisoformat(date_to).date() if date_to else None
    near = (hi or today + dt.timedelta(days=45)).isoformat()  # the schedules run for a year: a plain call doesn't need them all
    rows = [r for r in rows if r["source"] != "schedule" or r["date"][:10] <= near]
    out = [r for r in rows if (not lo or r["date"][:10] >= lo.isoformat()) and (not hi or r["date"][:10] <= hi.isoformat())]
    want = (hi or today + dt.timedelta(days=7)).isoformat()
    state = "unavailable" if not live_to or live_to < today.isoformat() else "ok" if live_to >= want else "partial"
    note = {"unavailable": "Calendar feed unavailable: showing the known schedule only (CPI, payrolls, FOMC, elections).",
            "partial": f"Calendar feeds reach {live_to}: after that, the known schedule only (CPI, payrolls, FOMC, elections).", "ok": ""}[state]
    if widen and not out and (lo or hi):  # nothing in the window: show the rest of the feed rather than a blank box
        res = calendar()
        res["note"] = note or "Nothing in this window: showing the rest of the feed."
        return res
    return {"result": out, "status": "ok", "feed": state, "live_to": live_to, "note": note}


# long-range dates for the calendar checks. Forex Factory only covers the current week, so: the Fed's own page for
# FOMC decisions, and TradingView's calendar (undocumented, about 30 days out) for the data releases
RELEASES = [("FOMC", ("fed interest rate decision", "federal funds rate")), ("Payrolls", ("non farm payrolls", "nonfarm payrolls", "non-farm employment")),
            ("CPI", ("inflation rate", "core inflation rate", "cpi")), ("PCE", ("pce price index",)), ("GDP", ("gdp growth rate", "gdp q/q"))]
NOT_RELEASE = ("minutes", "expectations", "nowcast", "forecast")
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def _release_kind(title):
    t = title.lower()
    if any(w in t for w in NOT_RELEASE):
        return None
    return next((k for k, words in RELEASES if any(t.startswith(w) or f" {w}" in t for w in words)), None)


def parse_releases(rows):
    """TradingView rows to one entry per release and day: {date, kind, title}, sorted."""
    seen, out = set(), []
    for e in rows:
        kind = _release_kind(e.get("title") or "")
        day = (e.get("date") or "")[:10]
        if kind and day and (day, kind) not in seen:
            seen.add((day, kind))
            out.append({"date": day, "kind": kind, "title": e["title"]})
    return sorted(out, key=lambda r: (r["date"], r["kind"]))


def parse_events(rows):
    """TradingView rows of medium or high importance in the calendar's shape."""
    out = []
    for e in rows:
        if (e.get("importance") or 0) >= 0 and e.get("title") and e.get("date"):
            out.append({"date": _zulu(dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00"))), "title": e["title"], "importance": 1 if e["importance"] >= 1 else 0, "kind": _release_kind(e["title"]),
                        "source": "tv", "forecast": e.get("forecast"), "previous": e.get("previous"), "actual": e.get("actual"), "period": e.get("period") or ""})
    return out


def parse_fomc(html):
    """Decision days from the Fed's meeting calendar page: the last day of each meeting."""
    year, out = None, []
    pattern = r"(\d{4}) FOMC Meetings|fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<"
    for y, month, days in re.findall(pattern, html, re.S):
        if y:
            year = int(y)
            continue
        m, d = MONTHS.get(re.split(r"[/-]", month.strip())[-1][:3].lower()), re.findall(r"\d+", days)
        if year and m and d:
            out.append(f"{year}-{m:02d}-{int(d[-1]):02d}")
    return sorted(set(out))


def _fetch_tv():
    now = dt.datetime.now(dt.timezone.utc)
    frm, to = now.strftime("%Y-%m-%dT00:00:00.000Z"), (now + dt.timedelta(days=100)).strftime("%Y-%m-%dT00:00:00.000Z")
    r = requests.get("https://economic-calendar.tradingview.com/events", params={"from": frm, "to": to, "countries": "US"}, timeout=20,
                     headers={**UA, "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"})
    r.raise_for_status()
    feed = r.json().get("result") or []
    rows = parse_releases(feed)
    if not rows:
        raise ValueError("no releases in the feed")
    db.set_meta("tv:releases", json.dumps({"rows": rows, "to": max(e["date"] for e in feed)[:10]}))
    db.set_meta("tv:releases:ts", dt.datetime.now().isoformat(timespec="seconds"))
    db.set_meta("tv:events", json.dumps(parse_events(feed)))
    db.set_meta("tv:events:ts", dt.datetime.now().isoformat(timespec="seconds"))


def _fetch_fomc():
    r = requests.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", headers=UA, timeout=20)
    r.raise_for_status()
    days = parse_fomc(r.text)
    if not days:
        raise ValueError("no meetings on the page")
    db.set_meta("fed:fomc", json.dumps(days))


def refresh_releases():
    """Both sources in turn; a failure keeps the last good list. Returns what failed."""
    bad = []
    for name, fetch in (("TradingView", _fetch_tv), ("Fed", _fetch_fomc)):
        try:
            fetch()
        except Exception as e:
            bad.append(f"{name}: {type(e).__name__}")
    return bad


def releases():
    """Cached dates, never the network, so any request can read them. `to` is how far the data releases are known."""
    raw, ts = db.get_meta("tv:releases"), db.get_meta("tv:releases:ts")
    tv = json.loads(raw) if raw else {"rows": [], "to": None}
    rows = {(r["date"], r["kind"]): r for r in tv["rows"]}
    for d in json.loads(db.get_meta("fed:fomc") or "[]"):
        rows[(d, "FOMC")] = {"date": d, "kind": "FOMC", "title": "FOMC decision"}
    age = (dt.datetime.now() - dt.datetime.fromisoformat(ts)).days if ts else 99
    return {"ok": age <= 7, "rows": sorted(rows.values(), key=lambda r: (r["date"], r["kind"])), "ts": ts, "to": tv["to"]}


def releases_past(rel, expiry):
    """What an expiry (ISO date) runs past from today on. `beyond`: it runs past the known data releases, so an empty
    list is not a clean window; `events` is None when the dates are unavailable."""
    if not rel["ok"]:
        return {"events": None, "beyond": True}
    today = dt.date.today().isoformat()
    return {"events": [r for r in rel["rows"] if today <= r["date"] <= expiry], "beyond": expiry > rel["to"]}
