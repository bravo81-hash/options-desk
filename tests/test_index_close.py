import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from desk import db, history, ibdata, pick

ET = ZoneInfo("America/New_York")
PRE_OPEN = dt.datetime(2026, 10, 30, 8, 0, tzinfo=ET)
MID_SESSION = dt.datetime(2026, 10, 30, 11, 0, tzinfo=ET)
AFTER_CLOSE = dt.datetime(2026, 10, 30, 16, 30, tzinfo=ET)


def bar(d, close):
    return SimpleNamespace(date=dt.date.fromisoformat(d), close=close)


@pytest.fixture
def tws(tmp_path, monkeypatch):
    """A temporary database and a fake TWS serving the bars in the returned dict."""
    monkeypatch.setattr(db, "_PATH", tmp_path / "t.db")
    db.init()
    bars = {}

    class FakeIB:
        def connect(self, *a, **k):
            pass

        def qualifyContracts(self, c):
            c.conId = 1
            return [c]

        def reqHistoricalData(self, c, *a, **k):
            return bars.get(c.symbol, [])

        def isConnected(self):
            return True

        def disconnect(self):
            pass

    monkeypatch.setattr("ib_async.IB", FakeIB)
    return bars


def stored(sym):
    return {r["date"]: r["close"] for r in db.query("SELECT date, close FROM index_daily WHERE symbol=?", (sym,))}


def official(monkeypatch, *rows):
    """Run the CBOE download against a fake VIX9D file."""
    text = "DATE,OPEN,HIGH,LOW,CLOSE\n" + "".join(f"{d},1,1,1,{c}\n" for d, c in rows)
    monkeypatch.setattr(history, "CBOE", ["VIX9D"])
    monkeypatch.setattr(history.requests, "get", lambda *a, **k: SimpleNamespace(text=text, raise_for_status=lambda: None))
    history.refresh_cboe(force=True)


def test_tws_cannot_overwrite_an_official_close(tws, monkeypatch):
    official(monkeypatch, ("10/29/2026", 15.87))
    tws["VIX9D"] = [bar("2026-10-29", 14.62)]
    ibdata.refresh(force=True, now=AFTER_CLOSE)
    assert stored("VIX9D") == {"2026-10-29": 15.87}


def test_tws_supplies_the_day_cboe_has_not_published_until_it_does(tws, monkeypatch):
    official(monkeypatch, ("10/29/2026", 15.87))
    tws["VIX9D"] = [bar("2026-10-29", 14.62), bar("2026-10-30", 16.0)]
    ibdata.refresh(force=True, now=AFTER_CLOSE)
    assert stored("VIX9D") == {"2026-10-29": 15.87, "2026-10-30": 16.0}
    official(monkeypatch, ("10/29/2026", 15.87), ("10/30/2026", 16.4))
    ibdata.refresh(force=True, now=AFTER_CLOSE)
    assert stored("VIX9D") == {"2026-10-29": 15.87, "2026-10-30": 16.4}


def test_symbols_cboe_does_not_publish_still_refresh(tws):
    tws["NDX"] = [bar("2026-10-29", 100.0)]
    ibdata.refresh(force=True, now=AFTER_CLOSE)
    tws["NDX"] = [bar("2026-10-29", 101.0)]
    ibdata.refresh(force=True, now=AFTER_CLOSE)
    assert stored("NDX") == {"2026-10-29": 101.0}


def test_pre_market_bar_is_not_stored(tws):
    tws["VIX"] = [bar("2026-10-29", 17.2), bar("2026-10-30", 18.48)]
    ibdata.refresh(force=True, now=PRE_OPEN)
    assert stored("VIX") == {"2026-10-29": 17.2}
    assert not db.get_meta("index_live")


def test_live_bar_is_kept_during_the_session(tws):
    tws["SPX"] = [bar("2026-10-30", 7700.0)]
    ibdata.refresh(force=True, now=MID_SESSION)
    assert stored("SPX") == {"2026-10-30": 7700.0}
    assert db.get_meta("index_live") == "2026-10-30"
    ibdata.drop_unfinished(MID_SESSION)
    assert stored("SPX") == {"2026-10-30": 7700.0}


def test_live_bar_left_after_the_close_is_removed(tws, monkeypatch):
    official(monkeypatch, ("10/30/2026", 16.4))
    tws["SPX"] = [bar("2026-10-29", 7720.0), bar("2026-10-30", 7700.0)]
    tws["VIX9D"] = [bar("2026-10-30", 15.0)]
    ibdata.refresh(force=True, now=MID_SESSION)
    ibdata.drop_unfinished(AFTER_CLOSE)
    assert stored("SPX") == {"2026-10-29": 7720.0}
    assert stored("VIX9D") == {"2026-10-30": 16.4}


def test_refresh_after_the_close_makes_the_bar_final(tws):
    tws["SPX"] = [bar("2026-10-30", 7700.0)]
    ibdata.refresh(force=True, now=MID_SESSION)
    tws["SPX"] = [bar("2026-10-30", 7710.0)]
    ibdata.refresh(force=True, now=AFTER_CLOSE)
    ibdata.drop_unfinished(AFTER_CLOSE)
    assert stored("SPX") == {"2026-10-30": 7710.0}


def test_download_rechecks_sooner_while_a_session_is_unpublished(tws, monkeypatch):
    official(monkeypatch, ("10/28/2026", 15.6))
    assert history._recheck_after() == dt.timedelta(minutes=30)
    official(monkeypatch, (history.last_session().strftime("%m/%d/%Y"), 15.6))
    assert history._recheck_after() == dt.timedelta(hours=8)


def test_ivts_reads_both_series_on_the_same_date(tws):
    db.write("INSERT INTO index_daily VALUES (?,?,?)", [("VIX", "2026-10-29", 17.2), ("VIX", "2026-10-30", 18.48),
                                                         ("VIX3M", "2026-10-29", 19.37)], many=True)
    assert abs(pick._ivts() - 17.2 / 19.37) < 1e-9
