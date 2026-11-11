"""Process over P&L: the daily read and its scoring, the limits remembered per session, and the automatic log's wording."""
import datetime as dt

import pytest

from desk import db, process


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_PATH", tmp_path / "t.db")
    db.init()
    from desk import market
    market._init()
    process.init()
    return tmp_path


def _bars(closes, start=dt.date(2026, 11, 2)):
    rows, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        rows.append(("^GSPC", d.isoformat(), c, c, c, c, 0))
        d += dt.timedelta(days=1)
    db.write("INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?)", rows, many=True)


def test_the_desk_read_follows_the_readiness_odds_and_weeks_are_named_by_their_worst_close():
    assert [process.app_call(r) for r in (12, 17, 22.9, 23, 40, None)] == ["quiet", "normal", "normal", "rough", "rough", None]
    assert [process.outcome(w) for w in (0.4, -0.49, -0.5, -1.99, -2.0, -6)] == ["quiet", "quiet", "normal", "normal", "rough", "rough"]


def test_a_call_is_saved_for_the_us_session_can_change_and_rejects_other_words(desk):
    mon = dt.datetime(2026, 11, 2, 20, 0, tzinfo=dt.timezone.utc)  # Monday 15:00 ET
    assert "error" in process.save_call("crash", 18, mon)
    c = process.save_call("quiet", 25, mon)
    assert (c["today"], c["mine"], c["app"]) == ("2026-11-02", "quiet", "rough")
    c = process.save_call("rough", None, mon)  # changed mind; the desk's read stays
    assert (c["mine"], c["app"]) == ("rough", "rough") and len(c["rows"]) == 1
    assert process.save_call(None, 12, dt.datetime(2026, 11, 3, 20, 0, tzinfo=dt.timezone.utc))["mine"] is None  # the desk's read alone, next day


def test_calls_are_scored_after_five_sessions_or_as_soon_as_the_week_turns_rough(desk):
    _bars([100, 100.2, 100.1, 100.3, 100.5, 100.4, 97.0, 97.5])  # 2 Nov .. 11 Nov
    for d, mine, app in (("2026-11-02", "quiet", "normal"), ("2026-11-05", "quiet", "rough"), ("2026-11-10", "normal", "quiet")):
        db.write("INSERT INTO market_calls VALUES (?,?,?,?,?)", (d, mine, app, None, "x"))
    C = process.calls(dt.datetime(2026, 11, 11, 20, 0, tzinfo=dt.timezone.utc))
    r = {x["date"]: x for x in C["rows"]}
    assert r["2026-11-02"]["outcome"] == "quiet" and r["2026-11-02"]["worst"] == 0.1  # five sessions seen, never below the close
    assert r["2026-11-05"]["outcome"] == "rough" and r["2026-11-05"]["seen"] == 4  # known early: it already closed 3% lower
    assert r["2026-11-10"]["outcome"] is None and r["2026-11-10"]["seen"] == 1  # pending
    assert C["score"] == {"n": 2, "mine": 1, "mine_n": 2, "app": 1, "app_n": 2, "quiet": 1}


def test_the_limits_are_remembered_per_session(desk):
    when = dt.datetime(2026, 11, 13, 20, 0, tzinfo=dt.timezone.utc)
    process.snap_day([{"label": "MGN", "over": True}, {"label": "SMSF", "over": False}], when)
    assert process.over_on("2026-11-13") == {"MGN"} and process.over_on("2026-11-12") is None


def test_every_journal_check_has_plain_words():
    from desk import a14rules
    ids = {c[0] for c in a14rules.checks({"plan_pct": 1, "lots0": 1, "lots_peak": 1, "dte0": 49, "ladder_n": 1, "off_window": 0, "week_n": 1, "size_then": "Full size"}, "2026-11-13")}
    assert "a14week" in ids
    assert ids | {"stop", "time", "adjust", "gate", "aside", "cap", "limits"} <= set(process.WHY)


def test_the_rule_book_reads_its_numbers_from_the_rules_and_every_rule_has_a_reason(monkeypatch):
    from desk import a14rules, rulebook
    from desk import limitcfg
    monkeypatch.setattr(limitcfg, "current", lambda now=None: {"values": {"cap:A14": 20, "cap:F49": None, "cap:total": None, "stress": 10, "ids:A14": None}, "move": 5.0,
                                                               "pending": [{"key": "cap:A14", "new": 30.0, "effective": "2026-11-12"}], "log": []})
    B = rulebook.book()
    rules = [r for s in B["sections"] for r in s["rules"]]
    assert len(rules) >= 30 and all(r["name"] and r["rule"] and r["what"] and r["why"] and r["who"] for r in rules)
    by = {r["name"]: r for r in rules}
    R = a14rules.rule()
    assert f"+{R['target']:g}%" in by["Target"]["rule"] and f"−{R['stop']:g}%" in by["Hard stop"]["rule"] and f"{R['time_dte']} days" in by["Time stop"]["rule"]
    assert "20%" in by["A14 worst-case cap"]["rule"] and "fits 2 ids" in by["A14 worst-case cap"]["why"] and "10%" in by["Stress limit"]["rule"]
    assert "Changes to 30% from 2026-11-12" in by["A14 worst-case cap"]["rule"] and "not set" in by["F49 worst-case cap"]["rule"]  # a waiting change is said, an unset cap too
    assert f"±{R['delta_band']:g} a lot" in by["Adjustment gates"]["rule"] and "three-quarter size" in by["Entry"]["rule"]
    assert "TimeEdge" in by and "A14" not in by and "F49" not in by  # A14 and F49 have their own sections, the other cards one line each
    assert [s["title"] for s in B["sections"]][:3] == ["Your limits", "A14", "F49"]


def test_the_now_screen_and_the_rule_book_travel_in_the_encrypted_snapshot():
    from desk import snapshot
    assert {"process", "rulebook", "risk", "a14/rules", "limits", "f49"} <= set(snapshot.PLAIN)


# ------------------------------------------------------------------ limits changed in the desk (desk/limitcfg.py)
def test_a_tighter_limit_applies_at_once_and_a_looser_one_from_the_next_session(desk, monkeypatch):
    from desk import limitcfg
    monkeypatch.setattr(limitcfg, "load_config", lambda: {"risk": {"stress": {"cap_pct": 20, "limit_pct": 10, "move": 5}}})
    wed = dt.datetime(2026, 11, 11, 20, 0, tzinfo=dt.timezone.utc)  # Wednesday afternoon in New York
    assert limitcfg.current(wed)["values"] == {"cap:A14": 20, "cap:F49": None, "cap:total": None, "stress": 10, "ids:A14": None}
    c = limitcfg.save("cap:A14", 30, wed)
    assert c["values"]["cap:A14"] == 20 and [(p["key"], p["new"], p["effective"]) for p in c["pending"]] == [("cap:A14", 30.0, "2026-11-12")]
    assert limitcfg.current(wed + dt.timedelta(days=1))["values"]["cap:A14"] == 30.0  # in force the next session
    assert limitcfg.save("stress", 8, wed)["values"]["stress"] == 8.0  # tighter: now
    assert limitcfg.save("cap:F49", 15, wed)["values"]["cap:F49"] == 15.0  # a first cap is tighter than none
    gone = limitcfg.save("cap:F49", None, wed)
    assert gone["values"]["cap:F49"] == 15.0 and gone["pending"][-1]["new"] is None  # removing one waits too
    again = limitcfg.save("cap:A14", 25, wed)  # a second thought replaces the change still waiting
    assert [p["new"] for p in again["pending"] if p["key"] == "cap:A14"] == [25.0]
    fri = dt.datetime(2026, 11, 13, 20, 0, tzinfo=dt.timezone.utc)
    assert limitcfg.save("cap:A14", 40, fri)["pending"][0]["effective"] == "2026-11-16"  # over the weekend
    assert "error" in limitcfg.save("cap:A14", 0, wed) and "error" in limitcfg.save("cap:XYZ", 5, wed) and "error" in limitcfg.save("stress", "lots", wed)


def test_the_bar_size_for_a_session_is_kept_for_the_midweek_check(desk):
    wed = dt.datetime(2026, 11, 11, 20, 0, tzinfo=dt.timezone.utc)
    process.snap_sizes({"strategies": [{"name": "A14 SPX", "size": "Full size"}, {"name": "A14 RUT", "size": "Half size"}]}, wed)
    assert process.size_on("2026-11-11", "A14 SPX") == "Full size" and process.size_on("2026-11-11", "A14 RUT") == "Half size" and process.size_on("2026-11-10", "A14 SPX") is None


def test_id_cap_has_its_own_unit_and_preserves_the_nav_cap(desk, monkeypatch):
    from desk import a14rules, limitcfg
    monkeypatch.setattr(limitcfg, "load_config", lambda: {"risk": {"stress": {"cap_pct": 20}}})
    now = dt.datetime(2026, 11, 11, 20, tzinfo=dt.timezone.utc)
    c = limitcfg.save("ids:A14", 4, now)
    assert c["values"]["ids:A14"] == 4 and c["values"]["cap:A14"] == 20
    assert c["values"]["cap:F49"] is None and c["values"]["cap:total"] is None
    assert c["log"][0]["key"] == "ids:A14"
    assert "error" in limitcfg.save("ids:A14", 4.5, now)
    c = limitcfg.save("ids:A14", 5, now)
    assert c["values"]["ids:A14"] == 4 and c["pending"][0]["new"] == 5
    monkeypatch.setattr(limitcfg, "value", lambda key, *a, **kw: 3 if key == "ids:A14" else None)
    assert a14rules.rule()["cap"] == 3
    rows = [{"strategy": "A14", "acct": "MGN", "underlying": "SPX", "legs": [], "one_pnl": 0}] * 4
    b = a14rules.book(rows, {"MGN": 100000})["MGN"]
    assert b["cap"] == 3 and b["alerts"] == ["4 SPX ids open: the rule's cap is 3"]


def test_snapshot_fingerprint_changes_on_a_limit_edit(desk, monkeypatch):
    from desk import limitcfg, snapshot
    monkeypatch.setattr(snapshot, "load_config", lambda: {"trade_files": {}})
    limitcfg.init()
    before = snapshot.fingerprint()
    limitcfg.save("ids:A14", 4)
    assert snapshot.fingerprint() != before


def test_snapshot_build_carries_limits_and_f49_without_publishing(monkeypatch):
    from flask import Flask, jsonify
    from desk import snapshot
    app = Flask("snapshot_contract")
    @app.get("/api/<path:path>")
    def payload(path):
        return jsonify({"path": path})
    monkeypatch.setattr(snapshot, "FLASK", app)
    monkeypatch.setattr(snapshot, "_scrubber", lambda: lambda x: x)
    monkeypatch.setattr(snapshot, "_push", lambda *a, **kw: pytest.fail("must not publish"))
    result = snapshot.build()
    assert result["limits"] == {"path": "limits"} and result["f49"] == {"path": "f49"}


def test_f49_exit_source_is_a_completed_daily_close_after_entry(desk):
    from desk import risk
    db.write("INSERT INTO index_daily (symbol,date,close) VALUES (?,?,?)", [("SPX", "2026-11-10", 7500), ("SPX", "2026-11-11", 7100)], many=True)
    midday = dt.datetime(2026, 11, 11, 17, tzinfo=dt.timezone.utc)
    close = dt.datetime(2026, 11, 11, 22, tzinfo=dt.timezone.utc)
    assert risk.cached_close("SPX", "2026-11-09", midday)["price"] == 7500
    assert risk.cached_close("SPX", "2026-11-11", midday) is None
    assert risk.cached_close("SPX", "2026-11-11", close)["price"] == 7100


def test_an_id_is_scored_against_the_id_cap_in_force_the_day_it_was_entered(desk, monkeypatch):
    from desk import a14rules, limitcfg
    monkeypatch.setattr(limitcfg, "load_config", lambda: {"risk": {"stress": {}}})
    row = {"plan_pct": 1, "lots0": 1, "lots_peak": 1, "dte0": 49, "ladder_n": 4, "off_window": 0}
    cap = lambda day: {c[0]: c[1] for c in a14rules.checks(row, day)}["a14cap"]  # noqa: E731
    assert cap("2026-11-13") is True  # nothing set: the rule page's 4
    limitcfg.save("ids:A14", 3, dt.datetime(2026, 11, 16, 20, 0, tzinfo=dt.timezone.utc))  # tighter, from Monday 16 Nov
    assert limitcfg.on("ids:A14", "2026-11-13") is None and limitcfg.on("ids:A14", "2026-11-16") == 3
    assert cap("2026-11-13") is True and cap("2026-11-20") is False  # the fourth id on the 13th stands; one on the 20th is over
