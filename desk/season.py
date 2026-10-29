"""Seasonality for the major US indices: seasonal path vs this year, forward windows from today's date,
months, realised volatility and VIX by month, weekday and turn-of-month effects, presidential cycle.

History: yfinance index closes (S&P 500 from 1927, Nasdaq-100 from 1985, Russell 2000 from 1987, Dow from
1992), cached in bars_daily and refreshed daily. VIX from index_daily (CBOE / IBKR, 1990 on).
"""
import datetime as dt
import math

import numpy as np
import pandas as pd

from . import db
from .history import series
from .market import fetch_yf, fetch_yf_max

INDICES = {"SPX": ("^GSPC", "S&P 500"), "NDX": ("^NDX", "Nasdaq-100"), "RUT": ("^RUT", "Russell 2000"), "DJI": ("^DJI", "Dow Jones"),
           "VIX": (None, "VIX")}  # VIX is a level: its seasonality is in points, not % returns
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CYCLE = {0: "election", 1: "post-election", 2: "midterm", 3: "pre-election"}
HORIZONS = [5, 10, 21, 42, 63]


def closes(sym):
    if sym == "VIX":
        v = series("VIX").dropna()
        v.index = pd.to_datetime(v.index)
        v = v[v > 0]
        # the Cboe history has rows on exchange holidays (most years from 2022): keep S&P 500 sessions only,
        # plus anything after the last S&P bar so a lagging index refresh does not drop today's VIX
        spx = closes("SPX").index
        return v[v.index.isin(spx) | (v.index > spx[-1])] if len(spx) else v
    yf_sym = INDICES[sym][0]
    fetch_yf_max([yf_sym])
    rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=? ORDER BY date", (yf_sym,))
    s = pd.Series({r["date"]: r["c"] for r in rows}, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s[s > 0].dropna()


def _years(all_years, cur, lookback, cycle):
    ys = [y for y in all_years if y < cur]
    if cycle == "same":
        ys = [y for y in ys if y % 4 == cur % 4]
    if lookback:
        ys = ys[-lookback:]
    return ys


def compute(sym="SPX", lookback=20, cycle="all", today=None):
    s = closes(sym)
    if len(s) < 300:
        return {"error": f"No history for {sym}."}
    today = pd.Timestamp(today or s.index[-1])
    cur = today.year
    lv = sym == "VIX"
    chg = (lambda a, b: b - a) if lv else (lambda a, b: 100 * (b / a - 1))
    r = s.diff() / 100 if lv else s.pct_change()  # x100 below gives points for VIX, % for indices
    lr = np.log(s).diff()
    all_years = sorted(set(s.index.year))
    ys = _years(all_years, cur, lookback, cycle)
    if len(ys) < 3:
        return {"error": "Not enough years for that filter."}

    # ---- seasonal path: cumulative % from the prior year's last close, by trading day of the year
    def ypath(y):
        yr = s[s.index.year == y]
        if lv:
            return yr.values.astype(float)  # a level needs no prior close, so the first year of history counts too
        prev = s[s.index.year < y]
        if not len(prev):
            return None
        return (yr / prev.iloc[-1] - 1).values * 100

    paths = {y: ypath(y) for y in ys}
    paths = {y: p for y, p in paths.items() if p is not None and len(p) > 200}
    if not paths:
        return {"error": "Not enough full years for that filter."}
    # years run 250-253 sessions: stretch each onto a common axis by its position in the year, so every point
    # averages every year and the last point is each year's own year end (indexing raw sessions left the final
    # one or two points to the few 253-session years)
    n = 253
    grid = np.linspace(0, 1, n)
    mat = np.array([np.interp(grid, np.linspace(0, 1, len(p)), p) for p in paths.values()])
    avg_path = mat.mean(axis=0)
    med_path = np.median(mat, axis=0)
    cur_path = ypath(cur)
    # month boundaries on the same axis (typical year)
    ref = s[s.index.year == ys[-1]]
    month_ticks = [{"i": round(int(np.argmax(ref.index.month == m)) * (n - 1) / (len(ref) - 1)), "label": MONTHS[m - 1]}
                   for m in range(1, 13) if (ref.index.month == m).any()]
    today_i = int((s.index.year == cur).sum()) - 1

    # ---- forward windows from today's calendar date in each past year
    fwd = []
    for h in HORIZONS:
        vals, vols = [], []
        for y in ys:
            try:
                start_day = pd.Timestamp(year=y, month=today.month, day=min(today.day, 28 if today.month == 2 else today.day))
            except ValueError:
                continue
            idx = s.index.searchsorted(start_day)
            if idx + h >= len(s) or s.index[idx].year != y:
                continue
            vals.append(chg(s.iloc[idx], s.iloc[idx + h]))
            seg = lr.iloc[idx + 1: idx + h + 1]
            if len(seg) > 2:
                vols.append(float(seg.std(ddof=1) * math.sqrt(252) * 100))
        if vals:
            v = np.array(vals)
            fwd.append({"h": h, "n": len(v), "mean": float(v.mean()), "median": float(np.median(v)), "up": float((v > 0).mean() * 100),
                        "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90)), "worst": float(v.min()),
                        "best": float(v.max()), "rv": float(np.mean(vols)) if vols and not lv else None})
    all_rv = float(lr[lr.index.year.isin(ys)].std() * math.sqrt(252) * 100)

    # ---- months: return per year and month, realised vol per month
    me = s.resample("ME").last()
    mret = me.diff() if lv else me.pct_change() * 100
    mvol = lr.groupby([lr.index.year, lr.index.month]).std() * math.sqrt(252) * 100
    table, mstats = {}, []
    for y in sorted(set(ys) | {cur}):
        table[y] = [None if not ((mret.index.year == y) & (mret.index.month == m)).any() else
                    float(mret[(mret.index.year == y) & (mret.index.month == m)].iloc[0]) for m in range(1, 13)]
    for m in range(1, 13):
        v = np.array([table[y][m - 1] for y in ys if table[y][m - 1] is not None])
        vv = np.array([mvol.get((y, m)) for y in ys if (y, m) in mvol.index])
        if len(v):
            mstats.append({"m": MONTHS[m - 1], "mean": float(v.mean()), "median": float(np.median(v)), "up": float((v > 0).mean() * 100),
                           "worst": float(v.min()), "best": float(v.max()), "rv": float(np.nanmean(vv)) if len(vv) and not lv else None, "cur": table.get(cur, [None] * 12)[m - 1]})

    # ---- VIX through the month (1990 on): average change in points and how often it rose
    vix = closes("VIX")
    vstats = []
    if len(vix):
        vme = vix.resample("ME").last()
        vch = vme.diff()
        for m in range(1, 13):
            v = vch[(vch.index.month == m) & (vch.index.year.isin(ys))].dropna()
            lvl = vix[(vix.index.month == m) & (vix.index.year.isin(ys))]
            if len(v):
                vstats.append({"m": MONTHS[m - 1], "chg": float(v.mean()), "up": float((v > 0).mean() * 100), "level": float(lvl.mean()) if len(lvl) else None})

    # ---- weekday and turn of month (daily returns in the chosen years)
    rr = r[r.index.year.isin(ys)].dropna() * 100
    wd = [{"d": d, "mean": float(rr[rr.index.dayofweek == i].mean()), "up": float((rr[rr.index.dayofweek == i] > 0).mean() * 100)}
          for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"])]
    df = pd.DataFrame({"r": rr})
    df["ym"] = df.index.to_period("M")
    df["tdm"] = df.groupby("ym").cumcount() + 1
    df["tdm_rev"] = df.groupby("ym")["r"].transform("count") - df["tdm"] + 1
    tom = []
    for k in range(5, 0, -1):
        x = df[df["tdm_rev"] == k]["r"]
        tom.append({"d": f"−{k}" if k > 1 else "last", "mean": float(x.mean()), "up": float((x > 0).mean() * 100)})
    for k in range(1, 6):
        x = df[df["tdm"] == k]["r"]
        tom.append({"d": f"+{k}", "mean": float(x.mean()), "up": float((x > 0).mean() * 100)})
    avg_day = float(rr.mean())

    # ---- presidential cycle: average year return by cycle year (all years of history)
    yret = s.resample("YE").mean() if lv else s.resample("YE").last().pct_change() * 100  # VIX: average level that year
    cyc = []
    for k in range(4):
        v = yret[(yret.index.year % 4 == k) & (yret.index.year < cur)].dropna()
        if lookback:
            v = v[v.index.year >= cur - lookback]
        cyc.append({"k": CYCLE[k], "mean": float(v.mean()) if len(v) else None, "up": float((v > 0).mean() * 100) if len(v) else None,
                    "n": int(len(v)), "now": k == cur % 4})

    # rest of the year: seasonal average from today's index to the year end vs this year so far
    rest = None
    if 0 <= today_i < n:
        outs = []
        for p in paths.values():
            if len(p) > today_i:
                outs.append(p[-1] - p[today_i] if lv else ((1 + p[-1] / 100) / (1 + p[today_i] / 100) - 1) * 100)
        if outs:
            o = np.array(outs)
            rest = {"seasonal_to_date": float(avg_path[today_i]), "seasonal_rest": float(o.mean()), "rest_median": float(np.median(o)),
                    "rest_up": float((o > 0).mean() * 100), "ytd": float(cur_path[-1]) if cur_path is not None and len(cur_path) else None}

    return {"sym": sym, "name": INDICES[sym][1], "unit": "pts" if lv else "%", "years": ys, "first": ys[0], "last": ys[-1], "n_years": len(ys), "cur": cur,
            "cycle_now": CYCLE[cur % 4], "today": today.date().isoformat(), "today_i": today_i, "spot": float(s.iloc[-1]),
            "path": {"avg": [None if not np.isfinite(x) else round(float(x), 3) for x in avg_path],
                     "median": [None if not np.isfinite(x) else round(float(x), 3) for x in med_path],
                     "cur": [round(float(x), 3) for x in cur_path] if cur_path is not None else []},
            "month_ticks": month_ticks, "forward": fwd, "rv_all": all_rv, "months": mstats, "table": {str(k): v for k, v in table.items()},
            "vix": vstats, "weekday": wd, "tom": tom, "avg_day": avg_day, "cycle": cyc, "rest": rest,
            "history_from": s.index[0].date().isoformat()}
