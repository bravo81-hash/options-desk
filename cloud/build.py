"""Build the public, market-data-only cloud copy of the desk as a static site (GitHub Pages).

Runs on GitHub Actions on a schedule. No TWS, no account data: it downloads market data (yfinance, CBOE,
Forex Factory), validates it, then writes every endpoint the public pages need as static JSON under
site/api/, copies web/ to site/, and injects cloud.js (static data layer + "laptop only" notices).
If validation fails the script exits non-zero and the previous site stays published.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["DESK_CLOUD"] = "1"
ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("DESK_DATA", str(ROOT / "cloud" / "data"))  # never the laptop's data/desk.db
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from desk import db, heads, history, market  # noqa: E402
from desk.accounts import US_HOLIDAYS  # noqa: E402
from desk.market import fetch_yf, fetch_yf_max  # noqa: E402

SITE = ROOT / "site"
ET = ZoneInfo("America/New_York")
SAN = lambda s: re.sub(r"[^A-Za-z0-9._-]", "_", s)  # noqa: E731
problems = []


def log(m):
    print(f"[build] {m}", flush=True)


def last_close():
    now = dt.datetime.now(ET)
    d = now.date() if (now.hour, now.minute) >= (16, 15) else now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in US_HOLIDAYS:
        d -= dt.timedelta(days=1)
    return d


def sessions_behind(date_str, lc):
    if not date_str:
        return 99
    d, n = dt.date.fromisoformat(date_str), 0
    while d < lc:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in US_HOLIDAYS:
            n += 1
    return n


# ---------------------------------------------------------------- 1. data
def load_data():
    db.init()
    log("CBOE VIX family")
    history.refresh_cboe(force=True)
    log("index history (yfinance) -> SPX / RUT / NDX")
    fetch_yf_max(["^GSPC", "^RUT", "^NDX"])
    # the data cache carries an afternoon build's bars: without this the evening build keeps them as the close
    fetch_yf(["^GSPC", "^RUT", "^NDX"] + market.MARKET_SYMBOLS, force=True)
    for yf_sym, sym in (("^GSPC", "SPX"), ("^RUT", "RUT"), ("^NDX", "NDX")):
        rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=?", (yf_sym,))
        db.write("INSERT OR REPLACE INTO index_daily VALUES (?,?,?)", [(sym, r["date"], r["c"]) for r in rows], many=True)
    log("ETFs + breadth")
    market.refresh_all()
    log("calendars, earnings, futures (each keeps its last copy on failure)")
    log(f"  release dates not refreshed: {market.refresh_releases() or 'none'}")
    log(f"  heads-up: {heads.refresh(now=True)}")


# ---------------------------------------------------------------- 2. validation
def validate():
    lc = last_close()
    for s in market.MARKET_SYMBOLS + ["^GSPC", "^RUT", "^NDX"]:
        rows = db.query("SELECT date, c FROM bars_daily WHERE symbol=? ORDER BY date", (s,))
        if len(rows) < 250:
            problems.append(f"{s}: only {len(rows)} bars")
            continue
        c = pd.Series([r["c"] for r in rows[-520:]])
        jumps = int(((c / c.shift(1) - 1).abs() > 0.25).sum())
        if jumps:
            problems.append(f"{s}: {jumps} jumps over 25% (corrupt rows?)")
        if (c <= 0).any():
            problems.append(f"{s}: non-positive prices")
        behind = sessions_behind(rows[-1]["date"], lc)
        if behind > 2:
            problems.append(f"{s}: {behind} sessions behind ({rows[-1]['date']})")
    for s in ("VIX", "VIX3M", "VIX9D", "SPX", "RUT"):
        rows = db.query("SELECT date, close FROM index_daily WHERE symbol=? ORDER BY date DESC LIMIT 260", (s,))
        if not rows:
            problems.append(f"{s}: no history")
            continue
        vals = [r["close"] for r in rows]
        if s.startswith("VIX") and not all(5 < v < 150 for v in vals):
            problems.append(f"{s}: values outside 5-150")
        if sessions_behind(rows[0]["date"], lc) > 2:
            problems.append(f"{s}: stale ({rows[0]['date']})")
    br = db.query("SELECT close FROM index_daily WHERE symbol='BR.SPX.50' ORDER BY date DESC LIMIT 60")
    if not br or not all(0 <= r["close"] <= 100 for r in br):
        problems.append("breadth: missing or out of range")
    return lc


# ---------------------------------------------------------------- 3. static API
def write(rel, data):
    p = SITE / "api" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False, default=str))


def clean(o):
    if isinstance(o, float):
        return None if (np.isnan(o) or np.isinf(o)) else o
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def build_api(lc):
    import app as deskapp  # Flask app (no TWS calls at import)
    client = deskapp.app.test_client()

    def get(url):
        r = client.get(url)
        return r.get_json()

    market_html = (ROOT / "web" / "market.html").read_text(encoding="utf-8")
    syms = sorted(set(re.findall(r'"((?:AMEX|NASDAQ|CBOE|INDEX|CME_MINI|RUSSELL|NYSE|ARCA):[A-Z0-9!._]+)"', market_html)))
    log(f"ohlcv for {len(syms)} symbols")
    for sym in syms:
        for interval, adj in (("1D", 0), ("1D", 1), ("1W", 0)):
            d = get(f"/api/md/ohlcv?symbol={sym}&interval={interval}&count=520&adj={adj}")
            if d and d.get("success"):
                write(f"md/ohlcv/{SAN(sym)}_{interval}_{adj}.json", d)
            elif interval == "1D" and adj == 0:
                problems.append(f"ohlcv {sym}: {(d or {}).get('error')}")
    today = dt.date.today()
    write("md/calendar.json", get(f"/api/md/calendar?date_from={(today - dt.timedelta(days=3)).isoformat()}&date_to={(today + dt.timedelta(days=21)).isoformat()}"))
    write("heads.json", get("/api/heads"))
    for name, url in (("vixcond", "/api/vixcond"), ("readiness", "/api/readiness"), ("term", "/api/term")):
        d = get(url)
        if not d or d.get("error"):
            problems.append(f"{name}: {(d or {}).get('error')}")
        write(f"{name}.json", d)
    for sym in ("SPX", "RUT"):
        write(f"skew_{sym}_30.json", get(f"/api/skew?symbol={sym}&tenor=30"))
    log("seasonality")
    for sym in ("SPX", "NDX", "RUT", "DJI", "VIX"):
        for years in (10, 20, 30, 50, 0):
            for cyc in ("all", "same"):
                write(f"season/{sym}_{years}_{cyc}.json", get(f"/api/season?sym={sym}&years={years}&cycle={cyc}"))
    # freshness for the cloud copy (market sources only)
    q = lambda sql: (db.query(sql) or [{}])[0].get("d")  # noqa: E731
    src = [("Index prices", q("SELECT MAX(date) d FROM index_daily WHERE symbol='SPX'"), "SPX / RUT / NDX daily closes (yfinance)"),
           ("VIX family", q("SELECT MAX(date) d FROM index_daily WHERE symbol='VIX3M'"), "CBOE VIX, VIX9D, VIX3M, VIX6M, VIX1Y, VVIX, SKEW, RVX"),
           ("ETF prices", q("SELECT MAX(date) d FROM bars_daily WHERE symbol='SPY'"), "Market tab ETFs and sectors (yfinance)"),
           ("Breadth", q("SELECT MAX(date) d FROM index_daily WHERE symbol='BR.SPX.50'"), "computed from S&P 500 / Nasdaq-100 members"),
           ("Event risk and overnight", (heads._box("scan").get("ts") or "")[:10] or None, "earnings, futures and after-hours moves as of the last cloud build")]
    write("freshness.json", {"last_close": lc.isoformat(), "cloud": True,
                             "sources": [{"name": n, "date": d, "stale": sessions_behind(d, lc) > 0, "what": w} for n, d, w in src]})
    write("cloud.json", {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "last_close": lc.isoformat()})


# ---------------------------------------------------------------- 4. pages
def build_pages():
    for f in (ROOT / "web").iterdir():
        if f.is_file():
            shutil.copy2(f, SITE / f.name)
    shutil.copy2(ROOT / "cloud" / "cloud.js", SITE / "cloud.js")
    for name in ("index.html", "market.html"):
        p = SITE / name
        s = p.read_text(encoding="utf-8")
        s = s.replace('src="/market"', 'src="market.html"')
        # the static data layer must load before any page script
        s = re.sub(r"(<head[^>]*>)", r'\1<script src="cloud.js"></script>', s, count=1)
        p.write_text(s, encoding="utf-8")
    (SITE / ".nojekyll").write_text("")
    fetch_snapshot()


def fetch_snapshot():
    """The laptop's encrypted snapshot (branch `snapshot`, ciphertext only; desk/snapshot.py). Optional: the
    page also reads it straight from the branch, this copy just survives networks that block raw GitHub."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return  # never shallow-fetch into the laptop's own repo
    try:
        subprocess.run(["git", "fetch", "-q", "--depth=1", "origin", "snapshot"], cwd=ROOT, check=True, capture_output=True, timeout=120)
        blob = subprocess.run(["git", "show", "FETCH_HEAD:snapshot.json"], cwd=ROOT, check=True, capture_output=True, timeout=60).stdout
        env = json.loads(blob)
        if env.get("v") != 1 or not env.get("ct"):
            raise ValueError("not an encrypted snapshot")
        (SITE / "private").mkdir(exist_ok=True)
        (SITE / "private" / "snapshot.json").write_bytes(blob)
        log(f"encrypted snapshot from {env.get('built')} ({len(blob) // 1024} kB)")
    except Exception as e:
        log(f"no encrypted snapshot: {e}")


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    load_data()
    lc = validate()
    build_api(lc)
    build_pages()
    if problems:
        log("VALIDATION FAILED — not publishing:")
        for p in problems:
            log("  " + p)
        sys.exit(1)
    log(f"ok: site built for the {lc} close")


if __name__ == "__main__":
    main()
