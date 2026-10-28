"""Encrypted snapshot of the laptop-only views for the cloud copy.

Every GET the trade tabs make (Risk grid with the last TWS marks, Trade plan, Journal, Evidence, P&L & Recon,
the last recorded scanner results ...) is rendered through the Flask test client, scrubbed of account numbers,
e-mail addresses and local paths, gzipped and encrypted with AES-256-GCM under a key derived from a passphrase
the user sets on the laptop (PBKDF2-SHA256). Only the ciphertext leaves the laptop: it is pushed as a single
orphan commit to the `snapshot` branch from a separate bare repo (data/snapshot.git), so the main repo's
history and branches are never involved. The cloud page decrypts it in the browser (cloud/cloud.js).
"""
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import subprocess
import threading

from . import ROOT, db, load_config
from .trades import _newest

DATA = ROOT / "data"
KEYFILE = DATA / "snapshot_key.json"
BARE = DATA / "snapshot.git"
OUT = DATA / "snapshot.json"
ITER = 600_000
BRANCH = "snapshot"
MIN_GAP_MIN = 20  # at most one automatic publish per 20 minutes
FLASK = None  # set by app.py to the running Flask app
status = {"running": False, "last": None, "error": None, "bytes": None, "entries": None}
_lock = threading.Lock()

# query parameters that select a snapshot entry; anything else the UI sends is ignored (keep in step with cloud.js)
KEEP = {"calendar": ["symbol"], "pair": ["symbol", "front", "back"], "pair/curve": ["symbol", "front", "back", "strike"],
        "skew": ["symbol", "tenor"], "pick": ["vol"], "a14/scan": ["sym", "vol"], "a14/curve": ["sym", "expiry", "u", "s", "l"]}
PLAIN = ["risk", "a14/stats", "a14/history", "journal", "evidence", "status", "pnl/weekly", "pnl/today", "recon", "em",
         "md/account", "freshness", "backtest", "conditions"]
A14_CURVES = 30  # risk curves for the top candidates per underlying (default sort: since-2009 return per day)


def jsnum(x):
    """Numbers as the browser writes them into a URL (7625, not 7625.0)."""
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def key(path, params=None):
    keep = KEEP.get(path, [])
    q = [(k, str(params[k])) for k in sorted(keep) if params and params.get(k) not in (None, "")]
    return path + ("?" + "&".join(f"{k}={v}" for k, v in q) if q else "")


# ------------------------------------------------------------------ passphrase
def set_passphrase(phrase):
    if not isinstance(phrase, str) or len(phrase) < 12:
        return {"error": "Use at least 12 characters (four or more unrelated words is best)."}
    salt = os.urandom(16)
    k = hashlib.pbkdf2_hmac("sha256", phrase.encode("utf-8"), salt, ITER, 32)
    DATA.mkdir(exist_ok=True)
    KEYFILE.write_text(json.dumps({"salt": base64.b64encode(salt).decode(), "iter": ITER, "key": base64.b64encode(k).decode(),
                                   "set": dt.datetime.now().isoformat(timespec="seconds")}))
    db.set_meta("snapshot_fp", "")  # force a publish with the new key
    return {"ok": True}


def _key():
    if not KEYFILE.exists():
        return None
    return json.loads(KEYFILE.read_text())


# ------------------------------------------------------------------ build
def _scrubber():
    cfg = load_config()["risk"]
    labels = cfg.get("account_labels") or {}
    accts = set(labels) | set((cfg.get("account_map") or {}).values())
    alias = {a: "acct-" + re.sub(r"[^A-Za-z0-9]+", "-", labels.get(a) or str(i + 1)).strip("-") for i, a in enumerate(sorted(x for x in accts if x))}
    acct_re = re.compile(r"\b(?:DU|U|F)\d{5,}\b")
    mail_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    home = os.path.expanduser("~")
    home_re = re.compile(re.escape(home), re.I)

    def s(v):
        for a, b in alias.items():
            v = v.replace(a, b)
        v = acct_re.sub(lambda m: alias.setdefault(m.group(0), f"acct-x{len(alias) + 1}"), v)
        return home_re.sub("~", mail_re.sub("(e-mail)", v))

    def walk(o):
        if isinstance(o, str):
            return s(o)
        if isinstance(o, dict):
            return {walk(k) if isinstance(k, str) else k: walk(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [walk(v) for v in o]
        return o
    return walk


def build():
    fa = FLASK or __import__("app").app  # test-client requests on the running app; none of these GETs touch TWS
    client = fa.test_client()
    out = {}

    def get(path, params=None):
        q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        r = client.get(f"/api/{path}" + (f"?{q}" if q else ""))
        d = r.get_json(silent=True)
        if d is not None:
            out[key(path, params)] = d
        return d

    for p in PLAIN:
        get(p)
    for sym in ("SPX", "RUT"):
        cal = get("calendar", {"symbol": sym}) or {}
        for pr in cal.get("pairs") or []:
            get("pair", {"symbol": sym, "front": pr["front"], "back": pr["back"]})
            if pr.get("strike") is not None:
                get("pair/curve", {"symbol": sym, "front": pr["front"], "back": pr["back"], "strike": jsnum(pr["strike"])})
        for ten in (14, 30, 45, 60):
            get("skew", {"symbol": sym, "tenor": ten})
    for vol in ("rv20", "iv"):
        get("pick", {"vol": vol})
        for sym in ("SPX,RUT", "SPX", "RUT"):
            sc = get("a14/scan", {"sym": sym, "vol": vol}) or {}
            if sym == "SPX,RUT" and vol == "rv20":
                cands = sc.get("candidates") or []
                for u in ("SPX", "RUT"):
                    top = sorted([c for c in cands if c.get("sym") == u and c.get("exp_day") is not None], key=lambda c: -(c.get("hist_day") if c.get("hist_day") is not None else c["exp_day"]))[:A14_CURVES]
                    for c in top:
                        get("a14/curve", {"sym": u, "expiry": c["expiry"], "u": jsnum(c["upper"]), "s": jsnum(c["short"]), "l": jsnum(c["lower"])})
    return _scrubber()(out)


def _encrypt(payload, k):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = gzip.compress(json.dumps(payload, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8"), 9)
    iv = os.urandom(12)
    ct = AESGCM(base64.b64decode(k["key"])).encrypt(iv, raw, None)
    return {"v": 1, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "kdf": "PBKDF2-SHA256", "iter": k["iter"],
            "salt": k["salt"], "iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode()}


# ------------------------------------------------------------------ push (separate bare repo, one orphan commit)
def _git(*args, inp=None):
    r = subprocess.run(["git", "-C", str(BARE), *args], input=inp, capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=180)
    if r.returncode:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _remote():
    r = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.strip()


def _push(path, message="encrypted snapshot"):
    if not (BARE / "HEAD").exists():
        subprocess.run(["git", "init", "--bare", "-q", str(BARE)], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    blob = _git("hash-object", "-w", str(path))
    tree = _git("mktree", "-z", inp=f"100644 blob {blob}\tsnapshot.json\0")  # NUL-terminated: text mode on Windows turns \n into \r\n
    env_id = ["-c", "user.name=options-desk", "-c", "user.email=options-desk@localhost"]
    commit = _git(*env_id, "commit-tree", tree, "-m", message)
    _git("push", "--force", "-q", _remote(), f"{commit}:refs/heads/{BRANCH}")
    _git("update-ref", f"refs/heads/{BRANCH}", commit)
    _git("gc", "--prune=now", "-q")


# ------------------------------------------------------------------ publish + automatic trigger
def fingerprint():
    """Changes whenever anything the snapshot shows has changed."""
    q = lambda sql: str((db.query(sql) or [{}])[0].get("v"))  # noqa: E731
    files = load_config()["trade_files"]
    parts = [db.get_meta("risk_marks") and json.loads(db.get_meta("risk_marks")).get("ts"),
             q("SELECT MAX(ts) v FROM snaps"), db.get_meta("a14_chain") and json.loads(db.get_meta("a14_chain")).get("ts"),
             db.get_meta("em_cache") and json.loads(db.get_meta("em_cache")).get("ts")]
    for g in (files.get("one_glob", []), files.get("one_detail_glob", [])):
        f = _newest(g)
        parts.append(f and f"{f}:{os.path.getmtime(f)}")
    for sql in ("SELECT MAX(date) v FROM account_daily", "SELECT MAX(updated) v FROM journal_notes", "SELECT COUNT(*) v FROM executions"):
        try:
            parts.append(q(sql))
        except Exception:
            parts.append(None)
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


def publish(force=False):
    k = _key()
    if not k:
        status["error"] = "no passphrase set"
        return status
    if not _lock.acquire(blocking=False):
        return status
    status.update(running=True, error=None)
    try:
        fp = fingerprint()
        if not force and db.get_meta("snapshot_fp") == fp:
            return status
        payload = build()
        enc = _encrypt(payload, k)
        OUT.write_text(json.dumps(enc, separators=(",", ":")))
        _push(OUT)
        db.set_meta("snapshot_fp", fp)
        db.set_meta("snapshot_last", enc["built"])
        status.update(last=enc["built"], bytes=OUT.stat().st_size, entries=len(payload))
    except Exception as e:
        status["error"] = str(e)[:300]
    finally:
        status["running"] = False
        _lock.release()
    return status


def auto():
    """Called from the scheduler loop: publish when something changed, at most every MIN_GAP_MIN minutes."""
    if not _key() or status["running"] or load_config().get("snapshot", {}).get("auto", True) is False:
        return
    last = db.get_meta("snapshot_last")
    if last and dt.datetime.fromisoformat(last) > dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=MIN_GAP_MIN):
        return
    if db.get_meta("snapshot_fp") == fingerprint():
        return
    publish()


def info():
    k = _key()
    return {"key_set": bool(k), "key_set_at": k and k.get("set"), "last": db.get_meta("snapshot_last"), "running": status["running"],
            "error": status["error"], "bytes": status["bytes"] or (OUT.stat().st_size if OUT.exists() else None), "entries": status["entries"],
            "branch": BRANCH, "auto": load_config().get("snapshot", {}).get("auto", True) is not False}
