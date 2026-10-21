"""Expected moves for every underlying you hold (open ONE trades + IBKR stock positions), from TWS.

Per expiry: at-the-money straddle mid and implied volatility. 1-sigma move = spot x IV x sqrt(days/365);
the straddle is the market's own price for the move (about 0.8 sigma). Your open trades' strikes are placed
on the same scale (sigmas from spot) so entries, adjustments and exits can be planned against them.
"""
import datetime as dt
import json
import math
import threading

from . import db
from .chain import LOCK, connect, dte, option_params, snapshot, underlying

status = {"running": False, "log": [], "last": None}


def _log(m):
    status["log"] = (status["log"] + [f"{dt.datetime.now():%H:%M:%S}  {m}"])[-30:]


def holdings():
    """{underlying: {expiry: [legs]}} from the open ONE trades, plus stock positions at IBKR."""
    from .risk import load_open_trades
    out = {"SPX": {}, "RUT": {}}
    trades, _ = load_open_trades()
    for t in trades:
        u = t["underlying"]
        for lg in t["legs"]:
            occ = lg.get("occ") or {}
            e = dt.datetime.strptime(lg["one_expiry"], "%d/%m/%Y").strftime("%Y%m%d")
            out.setdefault(u, {}).setdefault(e, []).append({"trade": t["name"], "account": t.get("ib_account"),
                                                            "strike": occ.get("strike"), "right": lg.get("right"), "qty": lg["qty"]})
    raw = db.get_meta("risk_marks")
    stocks = json.loads(raw).get("stocks", []) if raw else []
    for s in stocks:
        out.setdefault(s["symbol"], {})
    return out


def _pick(params, held, max_dte=120):
    """Next expiry, the next two Fridays, monthlies to max_dte, and every expiry you hold."""
    exps = sorted(e for e in params if dte(e) >= 0)
    pick = set(exps[:1])
    fridays = [e for e in exps if dt.datetime.strptime(e, "%Y%m%d").weekday() == 4]
    pick |= set(fridays[:2])
    for e in exps:
        d = dt.datetime.strptime(e, "%Y%m%d").date()
        if d.weekday() == 4 and 15 <= d.day <= 21 and dte(e) <= max_dte:
            pick.add(e)
    pick |= {e for e in held if e in params}
    return sorted(pick)


def fetch():
    from ib_async import Option
    if not LOCK.acquire(blocking=False):
        return {"error": "Another chain fetch is running."}
    status["running"] = True
    ib = None
    try:
        held = holdings()
        ib = connect()
        out = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "symbols": {}}
        for sym, hx in held.items():
            try:
                und, spot = underlying(ib, sym)
            except LookupError:
                try:  # e.g. an ASX holding
                    und, spot = underlying(ib, sym, currency="AUD", exchange="ASX")
                except Exception as e:
                    out["symbols"][sym] = {"error": str(e)}
                    continue
            if not spot:
                out["symbols"][sym] = {"error": "no price"}
                continue
            params = option_params(ib, und)
            if not params:
                out["symbols"][sym] = {"spot": spot, "error": "no listed options (or no option data subscription)"}
                continue
            exps = _pick(params, hx)
            cons, back = [], {}
            for e in exps:
                cls, strikes, ib_e = params[e]
                back[ib_e] = e
                # the strike list is the union over expiries, so far-dated ones may not list the nearest strike:
                # also ask for the nearest 25- and 50-point strikes and use the closest pair that quotes
                near = sorted(strikes, key=lambda x: abs(x - spot))[:2]
                ks = set(near) | {min((x for x in strikes if x % m == 0), key=lambda x: abs(x - spot), default=near[0]) for m in (25, 50)}
                cons += [Option(sym, ib_e, k, r, "SMART", tradingClass=cls, currency=und.currency) for k in ks for r in ("C", "P")]
            rows = snapshot(ib, cons)
            for r in rows:
                r["expiry"] = back.get(r["expiry"], r["expiry"])
            per = []
            for e in exps:
                pairs = {}
                for r in rows:
                    if r["expiry"] == e:
                        pairs.setdefault(r["strike"], {})[r["right"]] = r
                good = [(k, v) for k, v in pairs.items() if v.get("C") and v.get("P") and v["C"]["mid"] is not None and v["P"]["mid"] is not None]
                if not good:
                    good = [(k, v) for k, v in pairs.items() if v.get("C") and v.get("P")]
                if not good:
                    continue
                k, v = min(good, key=lambda kv: abs(kv[0] - spot))
                c, p = v["C"], v["P"]
                straddle = (c["mid"] + p["mid"]) if c["mid"] is not None and p["mid"] is not None else None
                ivs = [x["ib_iv"] for x in (c, p) if x.get("ib_iv")]
                iv = sum(ivs) / len(ivs) if ivs else None
                n = max(dte(e), 0)
                t = max(n, 0.5) / 365
                if iv is None and straddle:
                    iv = straddle / (0.7979 * spot * math.sqrt(t))
                sd = spot * iv * math.sqrt(t) if iv else None
                per.append({"expiry": e, "dte": n, "strike": c["strike"], "straddle": straddle, "iv": iv, "sd": sd,
                            "held": e in hx, "legs": hx.get(e, [])})
            out["symbols"][sym] = {"spot": spot, "currency": und.currency, "expiries": per,
                                   "day_sd": spot * per[0]["iv"] / math.sqrt(365) if per and per[0]["iv"] else None}
            _log(f"{sym}: {len(per)} expiries")
        db.set_meta("em_cache", json.dumps(out))
        status["last"] = out["ts"]
        return {"ok": True}
    except Exception as e:
        _log(f"expected moves failed: {e}")
        return {"error": f"Could not fetch from TWS: {e}"}
    finally:
        if ib is not None:
            ib.disconnect()
        status["running"] = False
        LOCK.release()


def refresh_async():
    if status["running"]:
        return False
    threading.Thread(target=fetch, daemon=True).start()
    return True


def payload():
    raw = db.get_meta("em_cache")
    return {**(json.loads(raw) if raw else {"symbols": {}}), "running": status["running"], "log": status["log"]}
