"""SQLite store. One file: data/desk.db."""
import sqlite3
import threading

from . import DATA

_PATH = DATA / "desk.db"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_daily (       -- CBOE indices, IB spot and IV30 history
  symbol TEXT, date TEXT, close REAL, PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS snaps (             -- one row per recorded chain snapshot
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, ts TEXT, date TEXT,
  spot REAL, n_quotes INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS quotes (            -- raw option quotes of a snapshot
  snap_id INTEGER, expiry TEXT, dte REAL, strike REAL, right TEXT,
  bid REAL, ask REAL, mid REAL, iv REAL, delta REAL, gamma REAL, vega REAL, theta REAL,
  ib_iv REAL, fwd REAL);
CREATE INDEX IF NOT EXISTS ix_quotes ON quotes (snap_id, expiry);
CREATE TABLE IF NOT EXISTS expiry_summary (    -- per-expiry vol points of a snapshot
  snap_id INTEGER, symbol TEXT, date TEXT, expiry TEXT, dte REAL, t REAL,
  atm_strike REAL, atm_iv REAL, p25_iv REAL, p10_iv REAL, c25_iv REAL,
  atm_put_mid REAL, atm_call_mid REAL);
CREATE INDEX IF NOT EXISTS ix_es ON expiry_summary (symbol, date);
CREATE TABLE IF NOT EXISTS tenor_daily (       -- fixed-maturity points, interpolated
  symbol TEXT, date TEXT, tenor INTEGER, atm_iv REAL, p25_iv REAL, p10_iv REAL, c25_iv REAL,
  PRIMARY KEY (symbol, date, tenor));
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect():
    con = sqlite3.connect(_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _lock, connect() as con:
        con.executescript(SCHEMA)


def write(sql, rows=None, many=False):
    with _lock, connect() as con:
        if many:
            con.executemany(sql, rows)
        else:
            cur = con.execute(sql, rows or ())
            return cur.lastrowid


def query(sql, args=()):
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def get_meta(k, default=None):
    r = query("SELECT v FROM meta WHERE k=?", (k,))
    return r[0]["v"] if r else default


def set_meta(k, v):
    write("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, str(v)))
