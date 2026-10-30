"""Market data for the Market tab (the former claude.ai Market Desk), from free local sources.

* Daily bars: IBKR for indexes and the VIX family when TWS is up (CBOE CSVs as history/fallback);
  yfinance for ETFs and ES futures (consolidated volume, as on TradingView). Cached in SQLite.
* Breadth: computed here from S&P 500 / Nasdaq-100 members (Wikipedia lists + yfinance closes):
  % of members above their 20/50/200-day SMA, overall and per GICS sector.
* Economic calendar: Forex Factory weekly JSON (US events, high/medium impact).
* Account: TWS (read-only), every managed sub-account.

Symbols arrive in the TradingView form the page already used (e.g. AMEX:SPY, INDEX:S5FI) and are
mapped to these sources.
"""
import datetime as dt
import io
import json
import threading

import numpy as np
import pandas as pd
import requests

from . import db
from .history import series

UA = {"User-Agent": "Mozilla/5.0"}
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
def calendar(date_from=None, date_to=None, widen=True):
    events = []
    for wk in ("thisweek", "nextweek"):
        key = f"ff:{wk}"
        cached = db.get_meta(key)
        stamp = db.get_meta(key + ":ts")
        fresh = stamp and dt.datetime.fromisoformat(stamp) > dt.datetime.now() - dt.timedelta(hours=2)
        if not fresh:
            try:
                r = requests.get(f"https://nfs.faireconomy.media/ff_calendar_{wk}.json", headers=UA, timeout=20)
                if r.status_code == 200:
                    cached = r.text
                    db.set_meta(key, cached)
                    db.set_meta(key + ":ts", dt.datetime.now().isoformat(timespec="seconds"))
            except Exception:
                pass
        if cached:
            try:
                events += json.loads(cached)
            except ValueError:
                pass
    out = []
    lo = dt.datetime.fromisoformat(date_from).date() if date_from else None
    hi = dt.datetime.fromisoformat(date_to).date() if date_to else None
    seen = set()
    for e in events:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        d = dt.datetime.fromisoformat(e["date"])
        du = d.astimezone(dt.timezone.utc)
        if (lo and du.date() < lo) or (hi and du.date() > hi):
            continue
        k = (e["title"], e["date"])
        if k in seen:
            continue
        seen.add(k)
        out.append({"date": du.isoformat().replace("+00:00", "Z"), "title": e["title"], "importance": 1 if e["impact"] == "High" else 0,
                    "forecast": e.get("forecast") or None, "previous": e.get("previous") or None, "actual": e.get("actual") or None, "period": ""})
    if widen and not out and (lo or hi):  # the free feed only covers the current week; show it rather than nothing
        res = calendar()
        res["note"] = "Next week's schedule appears when the free feed rolls over on Sunday (US time); showing this week's events."
        return res
    return {"result": out, "status": "ok"}
