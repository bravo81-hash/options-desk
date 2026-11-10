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
    ids = {c[0] for c in a14rules.checks({"plan_pct": 1, "lots0": 1, "lots_peak": 1, "dte0": 49, "ladder_n": 1, "off_window": 0}, "2026-11-13")}
    assert ids | {"stop", "time", "adjust", "gate", "aside", "cap", "limits"} <= set(process.WHY)


def test_the_rule_book_reads_its_numbers_from_the_rules_and_every_rule_has_a_reason(monkeypatch):
    from desk import a14rules, rulebook
    monkeypatch.setattr(rulebook, "load_config", lambda: {"risk": {"stress": {"cap_pct": 20, "limit_pct": 10, "move": 5}}})
    B = rulebook.book()
    rules = [r for s in B["sections"] for r in s["rules"]]
    assert len(rules) >= 30 and all(r["name"] and r["rule"] and r["what"] and r["why"] and r["who"] for r in rules)
    by = {r["name"]: r for r in rules}
    R = a14rules.rule()
    assert f"+{R['target']:g}%" in by["Target"]["rule"] and f"−{R['stop']:g}%" in by["Hard stop"]["rule"] and f"{R['time_dte']} days" in by["Time stop"]["rule"]
    assert "20%" in by["Worst-case cap"]["rule"] and "fits 2 ids" in by["Worst-case cap"]["why"] and "10%" in by["Stress limit"]["rule"]
    assert "TimeEdge" in by and "A14" not in by  # A14 has its own section, the other cards one line each
