"""Focused option-chain snapshots from TWS for the A14 scanner and the expected-move view.

One connection at a time (client id `chain_client_id`, default 43), read-only, market-data snapshots only.
Live quotes while the market is open, frozen closing quotes otherwise (reqMarketDataType 2).
"""
import asyncio
import datetime as dt
import threading

from . import load_config
from .recorder import ET

LOCK = threading.Lock()
INDEX_EXCH = {"SPX": "CBOE", "RUT": "RUSSELL", "NDX": "NASDAQ", "XSP": "CBOE"}
WEEKLY_CLASS = {"SPX": "SPXW", "RUT": "RUTW", "NDX": "NDXP"}


def connect():
    from ib_async import IB
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    cfg = load_config()
    ib = IB()
    ib.connect(cfg["tws"]["host"], cfg["tws"]["port"], clientId=cfg.get("chain_client_id", 43), readonly=True, timeout=15)
    ib.reqMarketDataType(2)
    return ib


def underlying(ib, sym, currency="USD", exchange=None):
    """Qualified underlying contract and its price (last/mid, else the close)."""
    from ib_async import Index, Stock
    if sym in INDEX_EXCH:
        c = Index(sym, INDEX_EXCH[sym], "USD")
    else:
        c = Stock(sym, exchange or "SMART", currency)
    if not ib.qualifyContracts(c) or not c.conId:
        raise LookupError(f"{sym}: unknown underlying")
    tk = ib.reqMktData(c, "", True, False)
    good = lambda v: v is not None and v == v and v > 0
    for _ in range(15):  # wait for the last trade: off-hours "close" is the session before
        ib.sleep(0.4)
        if good(tk.last):
            break
    px = tk.last if good(tk.last) else tk.marketPrice()
    if not good(px) and sym in INDEX_EXCH:
        from .history import series
        s = series(sym).dropna()  # latest IBKR daily bar
        px = float(s.iloc[-1]) if len(s) else None
    if not good(px):
        px = tk.close if good(tk.close) else None
    return c, px


def option_params(ib, und):
    """{expiry: (trading_class, sorted strikes, ib_expiry)}, keyed by the settlement date you see in ONE.

    AM-settled monthlies (SPX, RUT) are listed by IBKR under their last trading day, the Thursday; they are
    keyed here by the Friday they settle on. A third-Friday expiry uses the standard (AM) class, as you trade
    them; other expiries use the weekly (PM) class."""
    params = [p for p in ib.reqSecDefOptParams(und.symbol, "", und.secType, und.conId) if p.exchange == "SMART"]
    out = {}
    std = und.symbol
    for p in params:
        for e in p.expirations:
            d = dt.datetime.strptime(e, "%Y%m%d").date()
            key = e
            if p.tradingClass == std and d.weekday() == 3 and 15 <= (d + dt.timedelta(days=1)).day <= 21:
                key = (d + dt.timedelta(days=1)).strftime("%Y%m%d")
            k = dt.datetime.strptime(key, "%Y%m%d").date()
            third_fri = k.weekday() == 4 and 15 <= k.day <= 21
            prefer = (p.tradingClass == std) if third_fri else (p.tradingClass != std)
            if key not in out or prefer:
                out[key] = (p.tradingClass, sorted(p.strikes), e)
    return out


def snapshot(ib, contracts, batch=80):
    """Qualify and snapshot option contracts -> list of dict rows."""
    q = []
    for i in range(0, len(contracts), 50):
        q += [c for c in ib.qualifyContracts(*contracts[i:i + 50]) if c and c.conId]
    rows = []
    for i in range(0, len(q), batch):
        part = q[i:i + batch]
        tks = [ib.reqMktData(c, "", True, False) for c in part]
        for _ in range(24):
            ib.sleep(0.5)
            if all(t.bid == t.bid and t.ask == t.ask and t.bid is not None and t.ask is not None for t in tks):
                break
        for c, t in zip(part, tks):
            bid = t.bid if t.bid == t.bid and t.bid is not None and t.bid >= 0 else None
            ask = t.ask if t.ask == t.ask and t.ask is not None and t.ask > 0 else None
            g = t.modelGreeks
            rows.append(dict(expiry=c.lastTradeDateOrContractMonth, strike=c.strike, right=c.right, trading_class=c.tradingClass,
                             local=c.localSymbol, bid=bid, ask=ask, mid=(bid + ask) / 2 if bid is not None and ask is not None else None,
                             ib_iv=g.impliedVol if g and g.impliedVol == g.impliedVol else None,
                             und=g.undPrice if g and g.undPrice == g.undPrice else None,
                             close=t.close if t.close == t.close and t.close and t.close > 0 else None))
    return rows


def market_open():
    now = dt.datetime.now(ET)
    return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 15)


def dte(expiry, today=None):
    return (dt.datetime.strptime(expiry, "%Y%m%d").date() - (today or dt.datetime.now(ET).date())).days
