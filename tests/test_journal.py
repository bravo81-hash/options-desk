"""Journal: either ONE report reads the same, whole positions, frozen R, twins and rolls, behaviour flags, dated rules, typed data."""
import datetime as dt
import re
from pathlib import Path

import pytest

from desk import accounts, db, journal, one, positions, risk, trades

T_HEAD = ",Account,Status,Underlying,Expiration,TradeType,TradeId,TradeName,OpenDate,CloseDate,DaysToExpiration,DaysInTrade,Margin,Comms,PnL,PnLperc"
S_HEAD = ",,Account,TradeId,OpenDate,Transaction,Qty,Symbol,Expiry,Type,Description,Underlying,AvgOpenPrice,Commission,CloseDate,AvgClosePrice,DIT,PnL"
D_HEAD = ",,Account,TradeId,Date,Transaction,Qty,Symbol,Expiry,Type,Description,Underlying,Price,Commission"
P1, P2, P3 = "SPX   261121P05900000", "SPX   261121P05800000", "SPX   261121P05700000"
AM = "6:01:45 AM"


def at(day, hm="06:00", s=0):
    return dt.datetime.fromisoformat(f"2026-{day}T{hm}:00") + dt.timedelta(seconds=s)


def fill(t, side, qty, sym, px, comm=1.0, exp="20/11/2026"):
    return {"t": t, "side": side, "qty": qty, "symbol": sym, "expiry": exp, "px": px, "comm": comm, "type": "Put", "desc": "", "underlying": "SPX"}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_PATH", tmp_path / "t.db")
    db.init()
    journal.init()
    return tmp_path


def reports(tmp, name="1.A14+HV7", status="Open"):
    """The same trade in both exports: 4 lots added to, then 3 closed at a loss."""
    trade = f",{name},{status},SPX,20/11/2026,Custom,7,A14 SPX,5/10/2026 {AM},,47,20,5000,6.0,-90.0,-1.8"
    summary = [T_HEAD, trade, S_HEAD,
               f",,{name},7,5/10/2026 {AM},Buy,3,{P1},20/11/2026,Put,x,SPX,12.0,5.0,7/10/2026 {AM},9.0,2,-905.0",
               f",,{name},7,5/10/2026 {AM},Buy,1,{P1},20/11/2026,Put,x,SPX,12.0,1.0"]
    detail = [T_HEAD, trade, D_HEAD,
              f",,{name},7,5/10/2026 {AM},Buy,2,{P1},20/11/2026,Put,x,SPX,11.0,2.0",
              f",,{name},7,6/10/2026 {AM},Buy,2,{P1},20/11/2026,Put,x,SPX,13.0,2.0",
              f",,{name},7,7/10/2026 {AM},Sell,3,{P1},20/11/2026,Put,x,SPX,9.0,2.0"]
    s, d = tmp / "2026-11-01-ONESummaryReport.csv", tmp / "2026-11-01-ONEDetailReport.csv"
    s.write_text("\n".join(summary), encoding="utf-8")
    d.write_text("\n".join(detail), encoding="utf-8")
    return s, d


# ------------------------------------------------------------------ either report
def test_either_report_gives_the_same_open_book(desk):
    s, d = reports(desk)
    (a, _), (b, _) = risk.load_open_trades(str(s)), risk.load_open_trades(str(d))
    assert [(lg["symbol"], lg["qty"], lg["open_price"]) for lg in a[0]["legs"]] == [(lg["symbol"], lg["qty"], lg["open_price"]) for lg in b[0]["legs"]] == [("SPX   261120P05900000", 1, 12.0)]
    assert a[0]["one_pnl"] == b[0]["one_pnl"] == -90.0 and a[0]["margin"] == b[0]["margin"] == 5000


def test_the_report_kind_is_recognised_and_the_newest_of_either_wins(desk, monkeypatch):
    s, d = reports(desk)
    assert one.read(str(s))[2] == "summary" and one.read(str(d))[2] == "detail"
    monkeypatch.setattr(one, "load_config", lambda: {"trade_files": {"one_glob": [str(s)], "one_detail_glob": [str(d)]}})
    import os
    os.utime(s, (1, 1))
    assert one.report_path() == str(d) and one.detail_path() == str(d)
    os.utime(s, None)
    os.utime(d, (1, 1))
    assert one.report_path() == str(s) and one.detail_path() == str(d)


def test_columns_are_found_by_name(desk):
    """ONE lets you reorder columns: nothing may depend on their position."""
    p = desk / "x-ONESummaryReport.csv"
    p.write_text("\n".join([",TradeId,Account,Status,PnL,Underlying,Expiration,TradeName,OpenDate,CloseDate,DaysToExpiration,DaysInTrade,Margin,Comms,PnLperc",
                            f",9,1.A14,Closed,250.5,RUT,20/11/2026,A14 RUT,5/10/2026 {AM},6/10/2026 {AM},40,1,4000,3,6.2"]), encoding="utf-8")
    t = one.read(str(p))[0][0]
    assert t["pnl"] == 250.5 and t["trade_id"] == "9" and t["underlying"] == "RUT" and t["margin"] == 4000


def test_fills_keep_a_moving_average_like_one(desk):
    f = [fill(at("10-05"), "Buy", 2, P1, 11), fill(at("10-06"), "Buy", 2, P1, 13), fill(at("10-07"), "Sell", 3, P1, 9)]
    legs = one.legs_from_fills(f)
    assert [lg["open_px"] for lg in legs] == [12.0, 12.0, 12.0]  # reducing leaves the average alone
    closed = [lg for lg in legs if lg["close"]]
    assert sum(lg["qty"] for lg in closed) == 3 and sum(lg["qty"] for lg in legs if not lg["close"]) == 1
    assert sum(lg["pnl"] for lg in closed) == pytest.approx(-900 - sum(lg["comm"] for lg in closed))
    assert legs[0]["dit"] == 2 and legs[0]["open"] == at("10-05")


def test_a_fill_through_flat_opens_the_other_side(desk):
    legs = one.legs_from_fills([fill(at("10-05"), "Buy", 1, P1, 10), fill(at("10-06"), "Sell", 3, P1, 12)])
    left = [lg for lg in legs if not lg["close"]]
    assert left[0]["side"] == "Sell" and left[0]["qty"] == 2 and left[0]["open_px"] == 12


def test_a_real_expiry_stays_in_the_book_only_while_open(desk):
    s, _ = reports(desk, status="Closed")
    assert risk.load_open_trades(str(s))[0] == []


def test_backtests_are_left_out(desk):
    s, _ = reports(desk, name="Backtest A14")
    assert one.read(str(s))[0] == []


# ------------------------------------------------------------------ worst case and replay
def bwb():
    """Buy 1 5900, sell 2 5800, buy 1 5700 for a 100 dollar credit: a balanced fly, so it can't lose."""
    return [fill(at("10-05"), "Buy", 1, P1, 50), fill(at("10-05", s=20), "Sell", 2, P2, 30), fill(at("10-05", s=40), "Buy", 1, P3, 9)]


def test_worst_case_of_a_put_fly_is_its_debit():
    assert positions.replay(bwb())["risk0"] == pytest.approx(-100)
    pos = {("e", 5900.0, "P"): 1, ("e", 5800.0, "P"): -2, ("e", 5700.0, "P"): 1}
    assert positions.worst(pos, 100.0) == pytest.approx(100.0)
    assert positions.worst(pos, -300.0) == pytest.approx(-300.0)


def test_worst_case_of_a_broken_wing_is_the_extra_width():
    pos = {("e", 5900.0, "P"): 1, ("e", 5800.0, "P"): -2, ("e", 5600.0, "P"): 1}
    assert positions.worst(pos, 500.0) == pytest.approx(500 - 10000)  # 100 narrower on top than below


def test_worst_case_of_a_calendar_is_its_debit():
    pos = {("nov", 5900.0, "P"): -1, ("dec", 5900.0, "P"): 1}
    assert positions.worst(pos, -1200.0) == pytest.approx(-1200.0)


def test_an_uncapped_position_is_flagged():
    assert positions.uncapped({("e", 6000.0, "C"): -1})
    assert not positions.uncapped({("e", 6000.0, "C"): -1, ("e", 6100.0, "C"): 1})


def test_adjustments_and_the_closing_event():
    f = bwb() + [fill(at("10-10"), "Sell", 1, P1, 40), fill(at("10-10", "06:05"), "Buy", 1, P2, 25)] + [fill(at("10-20"), "Buy", 1, P2, 20), fill(at("10-20", s=30), "Sell", 1, P3, 5)]
    r = positions.replay(f, at("10-20"))
    assert len(r["events"]) == 3 and r["flat"] and r["adj"] == 1  # fills 5 minutes apart are one ticket; the last event only closes


def test_a_trade_opened_and_closed_in_one_sitting_has_no_adjustments():
    r = positions.replay([fill(at("10-05"), "Buy", 1, P1, 50), fill(at("10-05", s=60), "Sell", 1, P1, 50)])
    assert r["adj"] == 0 and r["flat"]


def test_r_stays_on_the_entry_when_risk_is_added():
    entry = bwb()
    grown = entry + [fill(at("10-10"), "Sell", 2, P2, 40), fill(at("10-10", s=30), "Buy", 2, P3, 5)]
    a, b = positions.replay(entry, at("10-11")), positions.replay(grown, at("10-11"))
    assert a["risk0"] == b["risk0"]
    assert b["peak"] > b["risk0"] and b["lots_peak"] > b["lots0"]


def test_risk_days_weigh_each_span_by_the_risk_it_carried():
    f = [fill(at("10-05"), "Buy", 1, P1, 10), fill(at("10-05", s=30), "Sell", 1, P2, 5), fill(at("10-07"), "Buy", 1, P1, 10), fill(at("10-07", s=30), "Sell", 1, P2, 5)]
    r = positions.replay(f, at("10-08"))
    assert r["risk_days"] == pytest.approx(500 * 2 + 1000 * 1)


def test_load_reads_the_newest_detail_report(desk, monkeypatch):
    _, d = reports(desk)
    monkeypatch.setattr(one, "detail_path", lambda: str(d))
    positions._cache.clear()
    pos, exported = positions.load()
    assert pos["1.A14+HV7#7"]["adj"] == 2 and pos["1.A14+HV7#7"]["lots0"] == 2 and exported
    assert risk.adjustment_counts()[0]["1.A14+HV7#7"] == 2


# ------------------------------------------------------------------ twins, rolls, decisions
def row(key, strategy="A14", acct="MGN", ticker="SPX", exp="2026-11-20", us="2026-10-05", entry=None, close=None, pnl=None, risk0=1000.0, lab=None, group=None, **kw):
    entry = entry or dt.datetime.fromisoformat(f"{us}T20:00:00")
    return {"key": key, "keys": [key], "strategy": strategy, "labels": [strategy] if lab is None and strategy != "Other" else (lab or []), "acct": acct, "group": group or acct, "ticker": ticker,
            "expiry_iso": exp, "entry_us": us, "entry": entry, "close": close, "exit_us": close.date().isoformat() if close else None, "dte_exit": 5 if close else None, "pnl": pnl, "risk0": risk0,
            "peak": risk0, "adj": 0, "risk_days": 100.0, "lots_peak": 4, "r": pnl / risk0 if close else None, "ret": None, "rolls": 0, **kw}


def test_a_twin_named_only_on_one_side_takes_that_strategy():
    a, b = row("a", lab=["A14"]), row("b", "Other", "SMSF", lab=[])
    positions.resolve_twins([a, b])
    assert b["strategy"] == "A14"


def test_twins_take_the_strategy_both_names_share():
    a, b = row("a", "A14", lab=["A14", "HV7"]), row("b", "HV7", "SMSF", lab=["HV7"])
    positions.resolve_twins([a, b])
    assert a["strategy"] == b["strategy"] == "HV7"


def test_real_twin_names():
    assert trades.labels("1.A14+HV7", "A14.HV7.SPX.JUN 17 - 4 LOTS") == ["A14", "HV7"]
    assert trades.labels("4.SMSF", "SMSF.SPX.HV7.JUN 17 - 4 LOTS") == ["HV7"]
    assert trades.labels("4.SMSF", "07 AUG.14.SMSF.RUT- 4 LOTS") == []
    assert trades.classify("1.A14+HV7", "A14.HV7.SPX.JUN 17") == "A14"  # the rest of the desk is unchanged


def test_the_same_account_twice_is_not_a_twin():
    a, b = row("a", lab=["A14"]), row("b", "Other", "MGN", lab=[])
    positions.resolve_twins([a, b])
    assert b["strategy"] == "Other"


def test_a_loser_reopened_later_is_one_position():
    t0 = dt.datetime(2026, 8, 7, 6, 0)
    old = row("old", exp="2026-08-21", entry=t0 - dt.timedelta(days=20), close=t0, pnl=-100.0, risk0=2000.0, adj=2)
    new = row("new", exp="2026-08-31", entry=t0 + dt.timedelta(minutes=12), close=t0 + dt.timedelta(days=10), pnl=1900.0, risk0=4000.0, adj=1)
    positions.link_rolls([old, new], 60)
    assert new["roll_of"] == "old" and old["roll_of"] is None
    c = positions.chains([old, new])
    assert len(c) == 1 and c[0]["pnl"] == 1800 and c[0]["risk0"] == 2000 and c[0]["r"] == pytest.approx(0.9)
    assert c[0]["close"] == new["close"] and c[0]["rolls"] == 1 and c[0]["adj"] == 4  # the roll itself is an adjustment


def test_a_new_trade_after_a_winner_or_much_later_or_another_ticker_is_not_a_roll():
    t0 = dt.datetime(2026, 8, 7, 6, 0)
    won = row("w", close=t0, pnl=100.0, entry=t0 - dt.timedelta(days=2))
    late = row("l", close=t0, pnl=-100.0, entry=t0 - dt.timedelta(days=2), exp="2026-08-21")
    for k, kw in (("a", dict(ticker="SPX", entry=t0 + dt.timedelta(hours=3))), ("b", dict(ticker="RUT", entry=t0 + dt.timedelta(minutes=5))), ("c", dict(exp="2026-08-14", entry=t0 + dt.timedelta(minutes=5)))):
        r = row(k, **{"exp": "2026-11-20", **kw})
        positions.link_rolls([won, late, r], 60)
        assert r["roll_of"] is None


def test_decisions_fold_twins():
    t0 = dt.datetime(2026, 10, 10, 6, 0)
    a, b = row("a", close=t0, pnl=200.0, risk0=1000.0), row("b", acct="SMSF", close=t0, pnl=300.0, risk0=1000.0)
    for r in (a, b):
        r["decision"] = "d"
    d = positions.fold([a, b])
    assert len(d) == 1 and d[0]["pnl"] == 500 and d[0]["risk0"] == 2000 and d[0]["r"] == pytest.approx(0.25) and d[0]["n"] == 2


def test_a_half_closed_decision_is_not_counted_yet():
    t0 = dt.datetime(2026, 10, 10, 6, 0)
    a, b = row("a", close=t0, pnl=200.0), {**row("b", acct="SMSF"), "r": None}
    for r in (a, b):
        r["decision"] = "d"
    assert positions.fold([a, b])[0]["r"] is None


# ------------------------------------------------------------------ behaviour
CFG = {"streak_n": 4, "revenge_minutes": 30, "revenge_loss_r": 0.25, "revenge_size": 1.25}


def dec(i, pnl=100.0, entry=None, close=None, strategy="A14", ticker="SPX", r=None, risk0=1000.0, roll=False):
    entry = entry or dt.datetime(2026, 9, 1) + dt.timedelta(days=i)
    return {"decision": f"d{i}", "strategy": strategy, "ticker": ticker, "entry": entry, "close": close or entry + dt.timedelta(hours=12), "pnl": pnl, "r": pnl / risk0 if r is None else r, "risk0": risk0, "roll": roll}


def test_streak_counts_straight_winning_closes_before_entry():
    ds = [dec(i) for i in range(6)]
    b = positions.behaviour(ds, CFG)
    assert [b[f"d{i}"]["streak"] for i in range(6)] == [0, 1, 2, 3, 4, 5]
    assert not b["d3"]["hot"] and b["d4"]["hot"]


def test_a_loss_resets_the_streak():
    ds = [dec(0), dec(1), dec(2, pnl=-50.0), dec(3)]
    assert positions.behaviour(ds, CFG)["d3"]["streak"] == 0


def test_a_position_still_open_does_not_count_towards_the_streak():
    ds = [dec(0), {**dec(1), "close": None, "pnl": None, "r": None}, dec(2)]
    assert positions.behaviour(ds, CFG)["d2"]["streak"] == 1


def test_revenge_needs_a_real_loss_and_a_bigger_size_or_the_same_ticker():
    t0 = dt.datetime(2026, 9, 10, 6, 0)
    loss = dec(0, pnl=-500.0, close=t0, entry=t0 - dt.timedelta(days=3), risk0=1000.0)
    same = dec(1, entry=t0 + dt.timedelta(minutes=10), ticker="SPX")
    other = dec(2, entry=t0 + dt.timedelta(minutes=12), ticker="RUT", strategy="TimeEdge")
    late = dec(3, entry=t0 + dt.timedelta(minutes=45), ticker="SPX")
    b = positions.behaviour([loss, same, other, late], CFG)
    assert b["d1"]["revenge"] and not b["d2"]["revenge"] and not b["d3"]["revenge"]


def test_revenge_ignores_a_small_loss_and_a_roll():
    t0 = dt.datetime(2026, 9, 10, 6, 0)
    small = dec(0, pnl=-100.0, close=t0, entry=t0 - dt.timedelta(days=3))
    big = dec(1, pnl=-900.0, close=t0, entry=t0 - dt.timedelta(days=3))
    after_small = dec(2, entry=t0 + dt.timedelta(minutes=10))
    b = positions.behaviour([small, after_small], CFG)
    assert not b["d2"]["revenge"]
    rolled = dec(2, entry=t0 + dt.timedelta(minutes=10), roll=True)
    assert not positions.behaviour([big, rolled], CFG)["d2"]["revenge"]


def test_revenge_by_size_in_another_ticker():
    t0 = dt.datetime(2026, 9, 10, 6, 0)
    hist = [dec(i, strategy="TimeEdge", ticker="RUT") for i in range(3)]
    loss = dec(5, pnl=-500.0, close=t0, entry=t0 - dt.timedelta(days=3), ticker="SPX")
    bigger = dec(6, entry=t0 + dt.timedelta(minutes=10), strategy="TimeEdge", ticker="RUT", risk0=1500.0)
    b = positions.behaviour(hist + [loss, bigger], CFG)
    assert b["d6"]["size_x"] == pytest.approx(1.5) and b["d6"]["revenge"]


def test_after_loss_marks_the_next_five_entries():
    ds = [dec(0, pnl=-100.0)] + [dec(i) for i in range(1, 8)]
    b = positions.behaviour(ds, CFG)
    assert [b[f"d{i}"]["after_loss"] for i in range(1, 8)] == [1, 2, 3, 4, 5, None, None]


def test_extreme_flags_size_and_a_planned_loss_overrun():
    ds = [dec(0, pnl=-100.0), dec(1, pnl=-100.0), dec(2, pnl=-100.0), dec(3, pnl=-100.0), dec(4, pnl=-1000.0), dec(5, pnl=500.0)]
    out, avg = positions.extreme_flags(ds, {"d1": 50.0, "d5": 10.0}, 2.5)
    assert avg == pytest.approx(0.28) and out == {"d1": ["stop"], "d4": ["size"]}


# ------------------------------------------------------------------ rules only count from when they existed
def rr(**kw):
    return {"strategy": "A14", "close": dt.datetime(2026, 10, 30), "exit_us": "2026-10-29", "entry_us": "2026-10-01", "ret": -5.0, "dte_exit": 10, "adj": 0, "ivts": 0.85, "vs20": 1.0, "plan_pct": 0.7, **kw}


def test_a_rule_written_after_the_trade_never_marks_it_down():
    c = {x[0]: x for x in positions.rule_checks(rr(exit_us="2026-10-20", ret=-30.0), 2.0)}
    assert c["stop"][1] is False and c["stop"][2] is False


def test_a_stop_is_read_on_ones_percent():
    c = {x[0]: x for x in positions.rule_checks(rr(ret=-19.0), 2.0)}
    assert c["stop"] == ["stop", True, True]
    c = {x[0]: x for x in positions.rule_checks(rr(ret=-21.0), 2.0)}
    assert c["stop"] == ["stop", False, True]


def test_the_time_stop():
    assert {x[0]: x[1] for x in positions.rule_checks(rr(dte_exit=1), 2.0)}["time"] is False


def test_adjustment_limits():
    c = {x[0]: x[1] for x in positions.rule_checks(rr(strategy="TimeEdge", adj=2), 2.0)}
    assert c["adjust"] is False
    assert {x[0]: x[1] for x in positions.rule_checks(rr(strategy="TimeEdge", adj=1), 2.0)}["adjust"] is True
    assert {x[0]: x[1] for x in positions.rule_checks(rr(strategy="HV7", adj=1), 2.0)}["adjust"] is False
    assert "adjust" not in {x[0] for x in positions.rule_checks(rr(), 2.0)}  # A14's gates need the log kept at the time


def test_the_calendar_gate_and_the_a14_stand_aside():
    assert {x[0]: x[1] for x in positions.rule_checks(rr(strategy="TimeEdge", ivts=0.95), 2.0)}["gate"] is False
    assert {x[0]: x[1] for x in positions.rule_checks(rr(strategy="TimeEdge", vs20=-1.0), 2.0)}["gate"] is False
    assert {x[0]: x[1] for x in positions.rule_checks(rr(ivts=1.02), 2.0)}["aside"] is False


def test_the_cap_counts_only_from_when_it_was_set_and_a_trade_with_no_card_has_no_plan():
    c = {x[0]: x for x in positions.rule_checks(rr(plan_pct=3.0), 2.0)}
    assert c["cap"] == ["cap", False, False]
    assert {x[0]: x for x in positions.rule_checks(rr(plan_pct=3.0, entry_us="2026-11-02"), 2.0)}["cap"][2] is True
    assert positions.rule_checks(rr(strategy="Other", plan_pct=None), 2.0) == []


def test_the_card_table_matches_the_plan_in_the_page():
    text = (Path(__file__).parent.parent / "web" / "risk.js").read_text(encoding="utf8")
    block = text[text.index("const CARDS = {"):text.index("const PRI =")]
    for name, c in positions.CARDS.items():
        line = next(ln for ln in block.splitlines() if re.match(rf'\s*"?{re.escape(name)}"?: \{{', ln))
        stop = re.search(r"stop: (-?\d+)", line)
        assert (abs(int(stop.group(1))) if stop else None) == c["stop"], name
        time = re.search(r"timeDte: (\d+)", line)
        assert (int(time.group(1)) if time else None) == c["time"], name
        assert re.search(r'adjust: "(\w+)"', line).group(1) == c["adjust"], name


# ------------------------------------------------------------------ capital and typed data
def test_nav_is_turned_into_usd_on_the_entry_day(desk):
    accounts.init()
    db.write("INSERT INTO account_daily (date, account, nav) VALUES ('2026-10-01','U1111111',100000),('2026-10-05','U1111111',110000)")
    db.write("INSERT INTO fx_daily VALUES ('AUDUSD','2026-10-01',0.7),('AUDUSD','2026-10-03',0.65)")
    f = positions.nav_lookup()
    assert f("U1111111", "2026-10-04") == pytest.approx(65000)
    assert f("U1111111", "2026-10-06") == pytest.approx(71500)
    assert f("U1111111", "2026-09-01") is None and f("U2222222", "2026-10-04") is None


def test_settings_default_and_save(desk):
    assert journal.settings()["extreme_x"] == 2.5 and journal.settings()["loss_bar"] == 30
    journal.save_settings({"extreme_x": 3, "not_a_setting": 9})
    assert journal.settings()["extreme_x"] == 3 and "not_a_setting" not in journal.settings()


def test_typed_data_survives_export_and_import(desk, tmp_path, monkeypatch):
    journal.save_review({"decision": "SPX|A14|x|y", "cause": "gap", "emotion": "calm", "rule_broken": "", "lesson": "wait"})
    journal.save_tag({"decision": "SPX|A14|x|y", "phase": "before", "mood": "calm", "confidence": 3, "tired": True})
    tid = journal.save_ticket({"strategy": "A14", "ticker": "spx", "account": "MGN", "worst": 5000, "stop_pct": 20, "nav": 400000, "checklist": {"gate": True}})["id"]
    journal.save_override({"decision": "SPX|A14|x|y", "kind": "news", "rule": "stop", "why": "FOMC", "rules_said": "exit"})
    journal.log_plan([{"key": "1.A14#7", "act": "exit", "label": "Exit: hard stop", "adj": "no", "pct": -21}], "2026-10-30")
    journal.save_settings({"cap_pct": 1.5})
    saved = journal.export_manual()
    t = [x for x in saved["tables"]["journal_tickets"]][0]
    assert t["id"] == tid and t["ticker"] == "SPX" and t["plan"] == 1000
    monkeypatch.setattr(db, "_PATH", tmp_path / "fresh.db")
    db.init()
    journal.init()
    assert journal.manual()["journal_reviews"] == []
    assert journal.import_manual(saved)["rows"] == 6
    after = journal.manual()
    assert after["journal_reviews"][0]["lesson"] == "wait" and after["journal_tags"][0]["tired"] == 1
    assert after["journal_planlog"][0]["adj"] == "no" and journal.settings()["cap_pct"] == 1.5


def test_import_ignores_anything_that_is_not_a_journal_table(desk):
    assert journal.import_manual({"tables": {"executions": [{"exec_id": "x"}], "account_daily": [{"date": "x"}]}})["rows"] == 0


def test_the_snapshot_fingerprint_moves_when_something_is_typed(desk, monkeypatch):
    from desk import snapshot
    monkeypatch.setattr(snapshot, "load_config", lambda: {"trade_files": {}})
    a = snapshot.fingerprint()
    journal.save_review({"decision": "d", "cause": "x"})
    assert snapshot.fingerprint() != a


def test_the_journal_is_still_in_the_snapshot():
    from desk import snapshot
    assert "journal" in snapshot.PLAIN
