"""Follow-up review: partial fills against repeats, how long a leader alert lasts, and event times in two zones."""
import datetime as dt

import pandas as pd
import pytest

from desk import accounts, db, heads, market, trades
from desk.recorder import ET


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_PATH", tmp_path / "t.db")
    db.init()
    accounts.init()
    return tmp_path


def fill(exec_id, commission, perm=7, side="BOT", symbol="RUTW  261113P02740000", when=None, account="U1111111"):
    when = when or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    db.write("""INSERT OR IGNORE INTO executions (exec_id, account, time_utc, local_symbol, sec_type, side, qty, price, commission, order_id, perm_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (exec_id, account, when, symbol, "OPT", side, 1, 21.28, commission, 200939, perm))


def at(day, hour, minute=0):
    return dt.datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}").replace(tzinfo=ET)


def move(date, ret=-12.6, z=-4.0):
    return {"date": date, "ret": ret, "z": z}


# ---- fills
def test_same_time_qty_and_price_with_their_own_exec_ids_are_parts_of_one_order(desk):
    fill("0002be80.6af4d1cf.01.01", 0.52)
    fill("0002be84.6ae4bcf0.01.01", 1.19)
    rows = accounts.fills()
    assert len(rows) == 2
    assert sorted((r["part"], r["parts"]) for r in rows) == [(1, 2), (2, 2)]
    assert round(sum(r["commission"] for r in rows), 2) == 1.71


def test_a_repeated_exec_id_is_stored_once(desk):
    fill("0002be80.6af4d1cf.01.01", 0.52)
    fill("0002be80.6af4d1cf.01.01", 0.52)
    rows = accounts.fills()
    assert [(r["part"], r["parts"]) for r in rows] == [(1, 1)]


def test_a_corrected_fill_replaces_the_original(desk):
    fill("0002be80.6af4d1cf.02.01", 0.52)
    fill("0002be80.6af4d1cf.02.02", 0.61)
    accounts.drop_corrected_fills()
    rows = accounts.fills()
    assert [r["exec_id"] for r in rows] == ["0002be80.6af4d1cf.02.02"]
    assert (rows[0]["part"], rows[0]["parts"]) == (1, 1)


def test_parts_stay_within_one_order_side_and_account(desk):
    fill("a.1.01.01", 1, perm=7)
    fill("b.1.01.01", 1, perm=8)
    fill("c.1.01.01", 1, perm=7, side="SLD")
    fill("d.1.01.01", 1, perm=7, account="U2222222")
    fill("e.1.01.01", 1, perm=0)
    fill("f.1.01.01", 1, perm=0)
    assert {r["parts"] for r in accounts.fills()} == {1}


# ---- leader alerts
@pytest.mark.parametrize("now, last", [
    (at("2026-10-30", 12), "2026-10-29"),  # Friday, before the close
    (at("2026-10-30", 16), "2026-10-30"),  # at the close
    (at("2026-10-31", 12), "2026-10-30"),  # Saturday
    (at("2026-11-02", 9), "2026-10-30"),  # Monday's open: Friday is still the last close
    (at("2026-11-27", 12), "2026-11-25"),  # Friday after Thanksgiving, before the close
])
def test_the_last_session_is_the_last_close_passed(now, last):
    assert heads.last_session(now) == last


def test_a_break_lasts_until_the_next_session_closes():
    wed = [move("2026-10-29")]
    assert heads.live_breaks(wed, at("2026-10-30", 12)) == wed
    assert heads.live_breaks(wed, at("2026-10-30", 17)) == []
    assert heads.live_breaks(wed, at("2026-11-02", 12)) == []


def test_a_friday_break_carries_over_the_weekend_to_monday_close():
    fri = [move("2026-10-30")]
    assert heads.live_breaks(fri, at("2026-10-31", 12)) == fri
    assert heads.live_breaks(fri, at("2026-11-02", 12)) == fri
    assert heads.live_breaks(fri, at("2026-11-02", 17)) == []


def test_only_real_breaks_count():
    assert heads.live_breaks([move("2026-10-30", -1.4, -0.5)], at("2026-10-30", 17)) == []


def leader_week(monkeypatch, moves):
    bars = [{"date": f"2026-{m:02d}-{d:02d}", "c": 100.0} for m in (8, 9) for d in range(1, 29)]
    monkeypatch.setattr(heads.db, "query", lambda sql, *a: [{"d": "2026-10-30"}] if "MAX" in sql else bars)
    monkeypatch.setattr(heads, "leaders", lambda: {"GOOGL": ["SPX top 10"]})
    monkeypatch.setattr(heads, "issuers", lambda: {"GOOGL": {"weight": 3.1, "name": "Alphabet"}})
    monkeypatch.setattr(heads, "leader_moves", lambda c: moves)


def test_an_expired_alert_stays_in_the_table_without_raising_the_alert(monkeypatch):
    leader_week(monkeypatch, [move("2026-10-30", -1.4, -0.5), move("2026-10-29")])
    out = heads.spillover(at("2026-10-31", 12))
    row = next(r for r in out["rows"] if r["sym"] == "GOOGL")
    assert not row["alert"] and not row["broke"]
    assert row["expired"] == "Thu 29 Oct"
    assert out["alerts"] == []


def test_a_live_alert_names_the_day_of_the_break(monkeypatch):
    leader_week(monkeypatch, [move("2026-10-30", -7.0, -3.3), move("2026-10-29", -1.0, -0.5)])
    out = heads.spillover(at("2026-10-31", 12))
    assert out["alerts"][0] == "GOOGL -7.0% on Fri 30 Oct (-3.3σ)"


# ---- two zones
@pytest.mark.parametrize("when, text", [
    ("2026-11-04T00:00:00Z", "Tue 3 Nov 7:00 PM ET · Wed 11:00 AM Melb"),  # EST and AEDT
    ("2026-11-06T13:30:00+00:00", "Fri 6 Nov 8:30 AM ET · Sat 12:30 AM Melb"),
    ("2026-07-15T12:30:00Z", "Wed 15 Jul 8:30 AM ET · Wed 10:30 PM Melb"),  # EDT and AEST
    ("2026-07-15T16:00:00+00:00", "Wed 15 Jul 12:00 PM ET · Thu 2:00 AM Melb"),
])
def test_two_zones_shows_the_us_date_then_the_local_clock(when, text):
    assert market.two_zones(when) == text


def test_two_zones_reads_a_datetime_and_treats_a_naive_one_as_utc():
    assert market.two_zones(dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc)) == market.two_zones(dt.datetime(2026, 11, 4))


def test_calendar_rows_carry_both_zones(desk):
    rows = market.calendar("2026-11-01", "2026-11-07", fetch=False)["result"]
    zones = {r["kind"]: r["zones"] for r in rows}
    assert zones["Election"] == "Tue 3 Nov 7:00 PM ET · Wed 11:00 AM Melb"
    assert zones["Payrolls"] == "Fri 6 Nov 8:30 AM ET · Sat 12:30 AM Melb"


# ---- this week's big events
@pytest.mark.parametrize("now, sunday", [
    (at("2026-11-02", 12), "2026-11-08"),
    (at("2026-11-06", 15), "2026-11-08"),
    (at("2026-11-07", 12), "2026-11-15"),  # from Saturday on, the week ahead
    (at("2026-11-08", 12), "2026-11-15"),
])
def test_week_end_is_the_sunday_of_the_week_being_traded(now, sunday):
    assert heads.week_end(now).date().isoformat() == sunday


# ---- stress count
def test_signals_without_data_are_left_out_of_the_count(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=300).date
    fired = pd.DataFrame({k: [False] * 300 for k in heads.SIGNALS}, index=idx)
    read = pd.DataFrame({k: [1.0] * 300 for k in heads.SIGNALS}, index=idx)
    read["ad"] = float("nan")
    read["lows"] = float("nan")
    monkeypatch.setattr(heads, "stress_frame", lambda: (fired, read))
    out = heads.stress()
    assert out["of"] == len(heads.SIGNALS) - 2
    assert out["no_data"] == ["Advance/decline divergence", "New 52-week lows"]


# ---- names
@pytest.mark.parametrize("name, tidy", [
    ("15 Dec '27 SPX 2LOTS", "15 DEC '27 SPX 2 LOTS"),
    ("13 NOV.A14 RUT 1 LOTS", "13 NOV.A14 RUT 1 LOT"),
    ("OTC '27 ZEBRA 2 lots", "OCT '27 ZEBRA 2 LOTS"),
    ("1LOT CSP", "1 LOT CSP"),
    ("HOTC 4 LOTS", "HOTC 4 LOTS"),
])
def test_names_are_tidied(monkeypatch, name, tidy):
    monkeypatch.setattr(trades, "load_config", lambda: {"risk": {"name_fixes": {"OTC": "OCT"}}})
    assert trades.fix_name(name) == tidy


def test_an_empty_name_stays_empty(monkeypatch):
    monkeypatch.setattr(trades, "load_config", lambda: {})
    assert trades.fix_name("") == ""
    assert trades.fix_name(None) is None
