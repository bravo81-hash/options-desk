"""Unified trade journal: OptionStrat export (before ONE) + newest ONE Summary Report.

Each trade: source, account/group, strategy, name, underlying, opened_et, closed_et, pnl, ret_pct, status.
Dates are converted to the US/Eastern trading date the trade was entered.
"""
import csv
import datetime as dt
import glob
import os
import re

from . import expand, load_config

STRATS = [  # (label, patterns matched against group + name, upper-case)
    ("TimeEdge", [r"\bTE\b", r"TIMEEDGE", r"TIME EDGE", r"DUALCAL", r"DUALDIAG", r"DUALDIAL"]),
    ("TimeZone", [r"\bTZ\b", r"TIMEZONE", r"TIME ZONE"]),
    ("Triple Cal", [r"TRIPLE", r"TRIPPLE"]),
    ("Flyagonal", [r"FLYAGONAL", r"FLYDIAG"]),
    ("A14", [r"\bA14\b"]),
    ("HV7", [r"\bHV7\b"]),
    ("Allantis", [r"ALLANTIS"]),
    ("IF", [r"\bIF\b", r"SPX - IF"]),
    ("Batman", [r"BATMAN"]),
    ("M200", [r"M200"]),
    ("Earnings", [r"EARNINGS", r"^ER\."]),
]
CALENDAR_FAMILY = {"TimeEdge", "TimeZone", "Triple Cal", "Flyagonal"}


def fix_name(name):
    """Corrections from config.local.json (risk.name_fixes: {"MNG": "MGN"}): whole words, display only. Trade ids don't use the name."""
    for wrong, right in (load_config().get("risk", {}).get("name_fixes") or {}).items():
        name = re.sub(rf"\b{re.escape(wrong)}\b", right, name)
    return name


def classify(group, name):
    text = f"{group or ''} | {name or ''}".upper().replace(".", " ")
    for label, pats in STRATS:
        if any(re.search(p, text) for p in pats):
            return label
    return "Other"


def _newest(patterns):
    files = []
    for p in patterns:
        files += glob.glob(expand(p))
    return max(files, key=os.path.getmtime) if files else None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _one_dt(s):
    """ONE times are local (AEST/AEDT); entry ~6am local = previous US session close."""
    if not s:
        return None
    for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y"):
        try:
            local = dt.datetime.strptime(s.strip(), fmt)
            return (local - dt.timedelta(hours=14)).date()  # local -> US/Eastern trading date
        except ValueError:
            continue
    return None


def _os_session(x):
    """OptionStrat times are local too (entries cluster 5-9am, the last US hours): same shift as ONE, a weekend time is the Friday session."""
    d = (x - dt.timedelta(hours=14)).date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def load_one(path=None):
    path = path or _newest(load_config()["trade_files"]["one_glob"])
    if not path:
        return [], None
    out = []
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.reader(fh):
            if len(r) > 15 and r[0] == "" and r[2] in ("Open", "Closed", "Expired") and r[1]:
                acct = r[1]
                if acct.lower().startswith("backtest"):
                    continue
                out.append(dict(source="ONE", group=acct, name=fix_name(r[7]), underlying=r[3], status=r[2],
                                opened=_one_dt(r[8]), closed=_one_dt(r[9]), pnl=_f(r[14]), ret_pct=_f(r[15]),
                                margin=_f(r[12]), strategy=classify(acct, r[7])))
    return out, path


def load_optionstrat(path=None):
    path = path or _newest(load_config()["trade_files"]["optionstrat_glob"])
    if not path:
        return [], None
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for r in list(wb.worksheets[0].iter_rows(values_only=True))[2:]:
        if r[3] is None or not isinstance(r[3], dt.datetime):
            continue
        created, closed = r[3], r[4]
        to_et = lambda x: _os_session(x) if isinstance(x, dt.datetime) else None
        name = str(r[0] or "")
        und = name.split(" ")[0].split(".")[1] if name.upper().startswith(("SMSF.", "ER.")) and "." in name else name.split(" ")[0].split(".")[0]
        out.append(dict(source="OptionStrat", group=r[18] or "", name=name, underlying=und, status="Closed",
                        opened=to_et(created), closed=to_et(closed), pnl=_f(r[2]),
                        ret_pct=(_f(r[1]) or 0) * 100, margin=None, strategy=classify(r[18], name)))
    return out, path


def journal():
    """OptionStrat for trades opened before ONE took over, ONE from then on."""
    cut = dt.date.fromisoformat(load_config()["trade_files"]["one_start"])
    one, one_path = load_one()
    os_, os_path = load_optionstrat()
    trades = [t for t in os_ if t["opened"] and t["opened"] < cut] + [t for t in one if t["opened"] and t["opened"] >= cut]
    trades.sort(key=lambda t: t["opened"])
    return trades, {"one": one_path, "optionstrat": os_path}
