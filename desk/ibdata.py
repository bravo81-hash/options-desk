"""Daily bars from IBKR (your market-data subscriptions), preferred over the free sources when TWS is up.

* Indexes (VIX family, SKEW, VVIX, RVX, VXN, SPX, RUT, NDX) -> index_daily, the table the term-structure,
  calendar scanner and Market tab read. The CBOE CSVs stay as the long history and the fallback.

ETFs, ES and breadth stay on yfinance: IBKR's ETF volume is SMART-routed volume (about 35% below the
consolidated volume TradingView shows), which would skew the volume-based warnings (OBV, Force Index)
against the Pine scripts; and 600 breadth members are impractical under IBKR's historical-data pacing.
Read-only: historical-data requests only.
"""
import datetime as dt
import threading

from . import db, load_config

INDEXES = {"VIX": "CBOE", "VIX9D": "CBOE", "VIX3M": "CBOE", "VIX6M": "CBOE", "VIX1Y": "CBOE", "VVIX": "CBOE",
           "SKEW": "CBOE", "RVX": "CBOE", "VXN": "CBOE", "SPX": "CBOE", "RUT": "RUSSELL", "NDX": "NASDAQ"}
_lock = threading.Lock()
status = {"last": None, "source": {}, "log": []}


def _log(m):
    status["log"] = (status["log"] + [f"{dt.datetime.now():%H:%M:%S}  {m}"])[-30:]


def refresh(max_age_min=10, force=False):
    """Pull daily bars for the indexes. Returns the number of symbols updated,
    or None when TWS is not reachable (callers then fall back to yfinance / CBOE)."""
    import os
    if os.environ.get("DESK_CLOUD"):
        return None  # cloud copy: no TWS; indexes come from yfinance / CBOE
    from zoneinfo import ZoneInfo
    et = dt.datetime.now(ZoneInfo("America/New_York"))
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
        n = 0
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
                db.write("INSERT OR REPLACE INTO index_daily VALUES (?,?,?)",
                         [(sym, b.date.isoformat(), float(b.close)) for b in bars], many=True)
                status["source"][sym] = "IBKR"
                n += 1
            except Exception as e:
                _log(f"{sym}: {e}")
        status["last"] = dt.datetime.now()
        db.set_meta("ibdata_last", status["last"].isoformat(timespec="seconds"))
        _log(f"IBKR daily bars refreshed for {n} symbols")
        return n
    finally:
        if ib is not None and ib.isConnected():
            ib.disconnect()
        _lock.release()
