"""IBKR Flex statements: official daily NAV, deposits and withdrawals, and the commission on every fill.

The TWS API keeps none of this for past days. An Activity Flex Query in Client Portal does, for up to a year. It is read
with the token and query id the user pastes into the Recorder tab. The token stays in data/flex_key.json: only IBKR ever
receives it, and no API, log or snapshot shows it. A statement can only be read, never trade.

A day's statement appears the next morning, so TWS still supplies today. Once it does, the official figures win: its NAV
replaces the desk's capture of that day, and its commission the fill's. Fills are matched by execution id; older fills
the journal never held are not added to it.
"""
import datetime as dt
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET

import requests

from . import DATA, db
from .accounts import _num, init

log = logging.getLogger("desk.flex")

KEYFILE = DATA / "flex_key.json"
BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
HEADERS = {"User-Agent": "Java"}  # IBKR turns away the default python-requests agent
SOURCE = "IBKR Flex"
WAIT_S, TRIES = 10, 18  # a year of statements can take a couple of minutes to build (limit: 10 requests a minute)
RETRY_H = 3  # today's statement isn't out yet: ask again this much later, not on every update
LATER = {"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021"}  # "try again shortly"
FIXES = {
    "1012": "The Flex token has expired: make a new one in Client Portal and save it here.",
    "1013": "IBKR refused this computer's IP address: remove the IP restriction on the Flex token.",
    "1014": "IBKR doesn't recognise that Query ID.",
    "1015": "IBKR doesn't recognise that token: paste the Current Token again.",
}
_lock = threading.Lock()


class FlexError(Exception):
    pass


# ------------------------------------------------------------------ token
def set_key(token, query_id):
    token, query_id = str(token or "").strip(), str(query_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{12,}", token):
        return {"error": "That doesn't look like a Flex token: copy the Current Token from Client Portal."}
    if not query_id.isdigit():
        return {"error": "The Query ID is a number: it's in the info pop-up beside the query."}
    KEYFILE.write_text(json.dumps({"token": token, "query_id": query_id, "set": dt.datetime.now().isoformat(timespec="seconds")}))
    db.set_meta("flex_try", "{}")
    return {"ok": True}


def _key():
    return json.loads(KEYFILE.read_text()) if KEYFILE.exists() else None


# ------------------------------------------------------------------ fetch
def _call(path, token, q):
    """One request. The token is in its URL, so what requests says about a failure must never be passed on."""
    try:
        r = requests.get(f"{BASE}/{path}", params={"t": token, "q": q, "v": 3}, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        raise FlexError(f"Could not reach IBKR ({type(e).__name__})") from None
    return ET.fromstring(r.content)


def _why(root):
    code = root.findtext("ErrorCode")
    return FIXES.get(code) or f"IBKR: {root.findtext('ErrorMessage') or 'no reason given'} ({code})"


def fetch(token, query_id):
    """The statement as an XML element: asks IBKR to build it, then collects it when it's ready."""
    first = _call("SendRequest", token, query_id)
    if first.findtext("Status") != "Success":
        raise FlexError(_why(first))
    ref = first.findtext("ReferenceCode")
    for _ in range(TRIES):
        root = _call("GetStatement", token, ref)
        if root.tag == "FlexQueryResponse":
            return root
        if root.findtext("ErrorCode") not in LATER:
            raise FlexError(_why(root))
        time.sleep(WAIT_S)
    raise FlexError("IBKR is still building the statement: a later update will try again.")


# ------------------------------------------------------------------ read
def _day(s):
    """ISO date from a Flex date or date-time (yyyyMMdd, or yyyy-MM-dd)."""
    d = (s or "").split(";")[0].replace("-", "")[:8]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else None


def _own(a):
    """A sub-account: the FA master and consolidated rows only repeat them."""
    return bool(re.fullmatch(r"D?U\d+", a or ""))


def _flow(out, e, amount, kind):
    a, d = e.get("accountId"), _day(e.get("reportDate") or e.get("dateTime"))
    if _own(a) and d and amount:
        out[e.get("transactionID") or f"{kind}:{a}:{d}:{amount}"] = (d, a, amount, kind)


def parse(root):
    nav, comm, flows = {}, {}, {}
    for r in root.iter("EquitySummaryByReportDateInBase"):
        a, d, v = r.get("accountId"), _day(r.get("reportDate")), _num(r.get("total"))
        if _own(a) and d and v and not r.get("model"):
            nav[(d, a)] = (v, r.get("currency"))
    for t in root.iter("Trade"):
        c = _num(t.get("ibCommission"))
        if t.get("ibExecID") and c is not None:
            comm[t.get("ibExecID")] = -c  # a charge is negative here, positive in TWS and in the journal
    for c in root.iter("CashTransaction"):
        if (c.get("type") or "").startswith("Deposits") and (c.get("levelOfDetail") or "").upper() != "SUMMARY" and c.get("currency") != "BASE_SUMMARY":
            _flow(flows, c, (_num(c.get("amount")) or 0.0) * (_num(c.get("fxRateToBase")) or 1.0), "deposit")
    for t in root.iter("Transfer"):  # between accounts; a position moved in or out changes NAV just like cash
        sign = {"IN": 1.0, "OUT": -1.0}.get(t.get("direction"))
        cash = abs(_num(t.get("cashTransfer")) or 0.0) * (_num(t.get("fxRateToBase")) or 1.0)
        if sign:
            _flow(flows, t, sign * (cash + abs(_num(t.get("positionAmountInBase")) or 0.0)), "transfer")
    sections = {"Net Asset Value (NAV) Summary in Base": nav, "Trades at Execution level": comm,
                "Cash Transactions": root.find(".//CashTransactions"), "Transfers (ACATS, Internal)": root.find(".//Transfers")}
    st = list(root.iter("FlexStatement"))
    return {"nav": nav, "comm": comm, "flows": flows, "missing": [k for k, v in sections.items() if v is None or v == {}],
            "from": min((d for d in (_day(s.get("fromDate")) for s in st) if d), default=""),
            "to": max((d for d in (_day(s.get("toDate")) for s in st) if d), default="")}


def store(p):
    """Writes a statement and returns what it changed."""
    init()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    held = {(r["date"], r["account"]) for r in db.query("SELECT date, account FROM account_daily")}
    db.write("""INSERT INTO account_daily (date, account, nav, currency, source, updated) VALUES (?,?,?,?,?,?)
                ON CONFLICT(date, account) DO UPDATE SET nav=excluded.nav, currency=excluded.currency, source=excluded.source,
                updated=excluded.updated""", [(d, a, v, c, SOURCE, now) for (d, a), (v, c) in p["nav"].items()], many=True)
    db.write("INSERT OR REPLACE INTO flex_flows VALUES (?,?,?,?,?)", [(k, *v) for k, v in p["flows"].items()], many=True)
    fills = {r["exec_id"] for r in db.query("SELECT exec_id FROM executions")}
    hits = [(c, e) for e, c in p["comm"].items() if e in fills]
    db.write("UPDATE executions SET commission=? WHERE exec_id=?", hits, many=True)
    return {"ts": now, "from": p["from"], "to": p["to"], "through": max((d for d, _ in p["nav"]), default=None),
            "nav_days": len({d for d, _ in p["nav"]}), "new_days": len(set(p["nav"]) - held), "flows": len(p["flows"]),
            "fills_matched": len(hits), "statement_fills": len(p["comm"]), "missing": p["missing"]}


# ------------------------------------------------------------------ run
def run():
    k = _key()
    if not k:
        return {"error": "IBKR Flex isn't set up"}
    if not _lock.acquire(blocking=False):
        return {"error": "already importing"}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    try:
        p = parse(fetch(k["token"], k["query_id"]))
        if not p["nav"]:
            raise FlexError("The statement has no daily NAV for a sub-account: check the query's NAV section, and that it's by account, not consolidated.")
        out = store(p)
        db.set_meta("flex_last", json.dumps(out))
        db.set_meta("flex_try", json.dumps({"ts": now}))
        return {"ok": True, "detail": f"NAV through {out['through']}, commissions on {out['fills_matched']} fills"}
    except Exception as e:
        msg = str(e).replace(k["token"], "(token)")[:240]
        log.warning("flex import failed: %s", msg)
        db.set_meta("flex_try", json.dumps({"ts": now, "error": msg}))
        return {"error": msg}
    finally:
        _lock.release()


def _meta(k):
    return json.loads(db.get_meta(k) or "{}")


def skip_reason(now, close):
    """Why an update needn't ask IBKR. `close` is the last finished session; its statement comes the next morning."""
    if not KEYFILE.exists():
        return "not set up: see the Recorder tab"
    through, tried = _meta("flex_last").get("through"), _meta("flex_try").get("ts")
    if through and through >= close:
        return f"statements current through {through}"
    if tried:
        ago = now - dt.datetime.fromisoformat(tried)
        if ago < dt.timedelta(hours=RETRY_H):
            return f"asked IBKR {int(ago.total_seconds() // 60)} min ago"
    return None


def covered():
    """The dates statements have reported: inside them, deposits come from IBKR, not config."""
    last = _meta("flex_last")
    return last.get("from") or "", last.get("to") or ""


def info():
    """Status for the pages. Never the token."""
    init()
    last, tried, k = _meta("flex_last"), _meta("flex_try"), _key()
    f = db.query("SELECT COUNT(*) n, COALESCE(SUM(commission<>0), 0) priced FROM executions WHERE sec_type<>'BAG' AND account NOT LIKE 'F%'")[0]
    return {"configured": bool(k), "set": k and k.get("set"), "running": _lock.locked(), "last": last or None, "through": last.get("through"),
            "tried": tried.get("ts"), "error": tried.get("error"), "fills": f["n"], "fills_priced": f["priced"]}
