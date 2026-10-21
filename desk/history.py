"""Free daily history: CBOE index CSVs. Series access helpers for every table."""
import datetime as dt
import io

import pandas as pd
import requests

from . import db

CBOE = ["VIX9D", "VIX", "VIX3M", "VIX6M", "VIX1Y", "SKEW", "VVIX", "RVX", "VXN"]
URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"
# fixed maturities (calendar days) of the SPX volatility indices
CBOE_TENORS = [("VIX9D", 9), ("VIX", 30), ("VIX3M", 93), ("VIX6M", 183), ("VIX1Y", 365)]


def refresh_cboe(force=False):
    last = db.get_meta("cboe_refreshed")
    if not force and last and dt.datetime.fromisoformat(last) > dt.datetime.now() - dt.timedelta(hours=8):
        return {"skipped": True, "last": last}
    done = {}
    for sym in CBOE:
        r = requests.get(URL.format(sym), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        col = "CLOSE" if "CLOSE" in df.columns else df.columns[-1]
        df["d"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
        rows = [(sym, d, float(c)) for d, c in zip(df["d"], df[col]) if pd.notna(c)]
        db.write("INSERT OR REPLACE INTO index_daily (symbol, date, close) VALUES (?,?,?)", rows, many=True)
        done[sym] = len(rows)
    db.set_meta("cboe_refreshed", dt.datetime.now().isoformat(timespec="seconds"))
    return done


def series(symbol, start=None):
    """pandas Series indexed by ISO date string."""
    sql = "SELECT date, close FROM index_daily WHERE symbol=?"
    args = [symbol]
    if start:
        sql += " AND date>=?"
        args.append(start)
    rows = db.query(sql + " ORDER BY date", args)
    return pd.Series({r["date"]: r["close"] for r in rows}, dtype=float)


def cboe_curve_frame(start="2011-01-01"):
    """DataFrame date x [VIX9D..VIX1Y] (in vol points), only dates with VIX9D/VIX/VIX3M."""
    cols = {name: series(name, start) for name, _ in CBOE_TENORS}
    df = pd.DataFrame(cols).dropna(subset=["VIX9D", "VIX", "VIX3M"])
    return df


def realized_vol(spot, n=20):
    r = (spot / spot.shift(1)).apply(lambda x: None if pd.isna(x) else x)
    import numpy as np
    lr = np.log(r.astype(float))
    return lr.rolling(n).std() * (252 ** 0.5)
