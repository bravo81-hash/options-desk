"""Daily bars from IBKR (your market-data subscriptions), for the days the free sources don't cover yet.

* Indexes (VIX family, SKEW, VVIX, RVX, VXN, SPX, RUT, NDX) -> index_daily, the table the term-structure,
  calendar scanner and Market tab read. For symbols in CBOE's files the official close always wins: IBKR's feed
  of VIX9D and VIX1Y stops at 16:00 ET and its daily bar keeps that last tick, but CBOE strikes the close at 16:15
  (2026-10-29: VIX9D 14.62 vs 15.87 official), so bars here only extend past the newest official date.

Only sessions that have opened are stored: VIX prints from 03:15 ET, and that pre-market bar is not a day of the
series. A bar from a session in progress is live until a refresh after the close replaces it; if none comes
(laptop asleep, TWS shut), drop_unfinished removes it so it can't read as that day's close.

ETFs, ES and breadth stay on yfinance: IBKR's ETF volume is SMART-routed volume (about 35% below the
consolidated volume TradingView shows), which would skew the volume-based warnings (OBV, Force Index)
against the Pine scripts; and 600 breadth members are impractical under IBKR's historical-data pacing.
Read-only: historical-data requests only.
"""
import datetime as dt
import threading

from . import db, history, load_config

INDEXES = {"VIX": "CBOE", "VIX9D": "CBOE", "VIX3M": "CBOE", "VIX6M": "CBOE", "VIX1Y": "CBOE", "VVIX": "CBOE",
           "SKEW": "CBOE", "RVX": "CBOE", "VXN": "CBOE", "SPX": "CBOE", "RUT": "RUSSELL", "NDX": "NASDAQ"}
_lock = threading.Lock()
status = {"last": None, "source": {}, "log": []}


def _log(m):
    status["log"] = (status["log"] + [f"{dt.datetime.now():%H:%M:%S}  {m}"])[-30:]


def drop_unfinished(now=None):
    """Remove a live bar whose session ended with no refresh after the close. Official rows stay."""
    d = db.get_meta("index_live")
    if d and d <= history.last_session(now).isoformat():
        for sym in INDEXES:
            if d > (history.official_through(sym) or ""):
                db.write("DELETE FROM index_daily WHERE symbol=? AND date=?", (sym, d))
        db.set_meta("index_live", "")
        _log(f"Removed the unfinished bars of {d}: no final bar arrived")


def refresh(max_age_min=10, force=False, now=None):
    """Pull daily bars for the indexes. Returns the number of symbols updated,
    or None when TWS is not reachable (callers then fall back to yfinance / CBOE)."""
    import os
    if os.environ.get("DESK_CLOUD"):
        return None  # cloud copy: no TWS; indexes come from yfinance / CBOE
    from zoneinfo import ZoneInfo
    et = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    newest = (et.date() if et.time() >= dt.time(9, 30) else et.date() - dt.timedelta(days=1)).isoformat()
    if et.weekday() >= 5 or not (9 <= et.hour < 17):
        max_age_min = max(max_age_min, 60)  # outside US hours the bars barely change
    if not force and status["last"] and dt.datetime.now() - status["last"] < dt.timedelta(minutes=max_age_min):
        return 0
    if not _lock.acquire(blocking=False):
        return 0
    ib = None
    try:
        from ib_async import IB
        cfg = load_config()
        ib = IB()
        try:
            ib.connect(cfg["tws"]["host"], cfg["tws"]["port"], clientId=cfg.get("ibdata_client_id", 45), readonly=True, timeout=10)
        except Exception as e:
            _log(f"TWS not reachable: {e}")
            return None
        from ib_async import Index
        n, latest = 0, ""
        for sym, exch in INDEXES.items():
            try:
                c = Index(sym, exch, "USD")
                if not ib.qualifyContracts(c) or not c.conId:
                    continue
                have = db.query("SELECT COUNT(*) n FROM index_daily WHERE symbol=? AND date>=?",
                                (sym, (dt.date.today() - dt.timedelta(days=400)).isoformat()))[0]["n"]
                bars = ib.reqHistoricalData(c, "", "2 Y" if have < 200 else "1 M", "1 day", "TRADES", True, formatDate=1, timeout=30)
                if not bars:
                    continue
                official = history.official_through(sym) or ""
                rows = [(sym, b.date.isoformat(), float(b.close)) for b in bars if official < b.date.isoformat() <= newest]
                db.write("INSERT OR REPLACE INTO index_daily VALUES (?,?,?)", rows, many=True)
                latest = max([latest] + [r[1] for r in rows])
                status["source"][sym] = "IBKR"
                n += 1
            except Exception as e:
                _log(f"{sym}: {e}")
        db.set_meta("index_live", latest if latest > history.last_session(et).isoformat() else "")
        status["last"] = dt.datetime.now()
        db.set_meta("ibdata_last", status["last"].isoformat(timespec="seconds"))
        _log(f"IBKR daily bars refreshed for {n} symbols")
        return n
    finally:
        if ib is not None and ib.isConnected():
            ib.disconnect()
        _lock.release()
