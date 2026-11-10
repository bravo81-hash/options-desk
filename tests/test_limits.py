"""The fixes from the 7 Nov review: the book against the A14 rule page and the stress limit, jump frequencies, the provisional
13-week week, and plans that never come from a partial total."""
import datetime as dt

import pytest

from desk import a14rules as ar, db, journal, market, risk


def leg(qty, strike, right="P", open_price=10.0, exp="2026-12-31T16:00:00-05:00"):
    return {"qty": qty, "strike": strike, "right": right, "open_price": open_price, "expiry_iso": exp}


def bwb(acct="MGN", und="SPX", lots=1, one_pnl=0.0, opened="2026-11-06T06:00:00", strategy="A14", **k):
    """Put BWB 7050/6950/6800 for a 2.80 credit: worst case (150 - 100 - 2.80) x 100 = $4,720 a lot below the lower wing."""
    return {"id": f"{acct}#{und}{lots}{opened}", "name": f"{und} {acct} {lots} lots", "acct": acct, "underlying": und, "strategy": strategy, "one_pnl": one_pnl, "opened_iso": opened,
            "legs": [leg(lots, 7050, open_price=60.0), leg(-2 * lots, 6950, open_price=40.0), leg(lots, 6800, open_price=17.2)], **k}


# ------------------------------------------------------------------ the rule page, per account
def test_an_id_worst_case_is_intrinsic_at_any_price_with_what_it_has_realised():
    assert ar.id_worst(bwb()) == pytest.approx(-4720.0)
    assert ar.id_worst(bwb(lots=2, one_pnl=-500.0)) == pytest.approx(-9940.0)  # realised losses count against it
    assert ar.id_worst({**bwb(), "legs": [leg(-1, 7400, "C")]}) == float("-inf")  # a naked short call has no ceiling
    assert ar.id_worst({**bwb(), "legs": [leg(1, 7050, open_price=None)]}) is None


def test_book_flags_an_id_over_seven_and_a_half_percent_and_a_ticker_over_the_cap():
    navs = {"MGN": 100000.0, "SMSF": 50000.0}
    rows = [bwb("MGN", opened=f"2026-11-{d:02d}T06:00:00") for d in (3, 10, 17, 24, 30)] + [bwb("SMSF", lots=1), bwb("SMSF", und="RUT", lots=2, opened="2026-10-20T06:00:00")]
    B = ar.book(rows, navs)
    m, s = B["MGN"], B["SMSF"]
    assert m["ids"] == {"SPX": 5} and m["over"] == [] and m["largest"] == pytest.approx(4.7) and m["worst_pct"] == pytest.approx(23.6)
    assert m["alerts"] == ["5 SPX ids open: the rule's cap is 4"]
    assert s["ids"] == {"SPX": 1, "RUT": 1} and s["largest"] == pytest.approx(18.9)  # 2 lots of $4,720 on a $50k account
    assert [o["pct"] for o in s["over"]] == [pytest.approx(9.4), pytest.approx(18.9)]
    assert s["over"][1]["before"] is True and s["over"][0]["before"] is False  # 20 Oct predates the 2 Nov rules
    assert "over the rule's 7.5%" in s["alerts"][0] and s["alerts"][1].endswith("(opened before the 2 Nov rules)")


def test_book_counts_only_a14_and_says_when_it_cannot_price_an_id():
    B = ar.book([bwb(strategy="TimeEdge"), {**bwb(), "legs": [leg(1, 7050, open_price=None)]}], {"MGN": 100000.0})
    assert B["MGN"]["ids"] == {"SPX": 1} and B["MGN"]["unpriced"] == 1 and B["MGN"]["alerts"] == []


# ------------------------------------------------------------------ the stress limit
def grid_for(down, up, label="MGN"):
    """A gap grid with only the ±5% and ±10% joint cells that matter here."""
    gaps = [-10, -7, -5, -3, -1.5, 1.5, 3, 5, 7, 10]
    cells = [[{-5: down, 5: up, -10: 2 * down, 10: 2 * up}.get(g, 0.0)] + [0.0] * 4 for g in gaps]
    return {"gaps": gaps, "vols": ["joint", -3, 0, 3, 6], "accounts": [{"label": label, "cells": cells}]}


BOOK = {"margin": [{"label": "MGN", "nav": 145000.0, "rate": 1.45}]}  # A$145k = US$100k
TR = [{**bwb(), "ib_account": "U1", "group": "x"}]


def test_stress_is_the_worse_side_of_a_five_percent_day_as_percent_of_nav():
    L = risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-21000.0, -9000.0), cfg={"move": 5, "limit_pct": None})[0]
    assert L["nav_usd"] == 100000 and L["stress"]["pct"] == 21.0 and L["stress"]["limit"] is None and L["stress"]["ten"] == [-42000.0, -18000.0]
    assert L["alerts"] == []  # no limit set: the figure shows, nothing alerts
    up = risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-3000.0, -16000.0), cfg={"move": 5, "limit_pct": None})[0]
    assert up["stress"]["pct"] == 16.0  # a rally can be the worse side


def test_stress_alerts_only_past_the_limit_and_per_account_limits_work():
    over = risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-21000.0, 0.0), cfg={"move": 5, "limit_pct": 12.5})[0]
    assert over["alerts"] == ["a 5% day with IVs moving with it would cost 21.0% of NAV, over your 12.5% limit"]
    assert risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-12000.0, 0.0), cfg={"move": 5, "limit_pct": 12.5})[0]["alerts"] == []
    per = risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-21000.0, 0.0), cfg={"move": 5, "limit_pct": {"MGN": 25, "SMSF": 10}})[0]
    assert per["stress"]["limit"] == 25 and per["alerts"] == []


def test_stress_reads_the_default_smile_and_shows_the_sticky_strike_figure_beside_it():
    g = {**grid_for(-9000.0, 0.0), "mode": "moneyness", "modes": {"strike": grid_for(-18000.0, 0.0)}}
    s = risk.limits(TR, {"U1": "MGN"}, BOOK, g, cfg={"move": 5, "limit_pct": 12.5})[0]
    assert s["stress"]["pct"] == 9.0 and s["stress"]["strike_pct"] == 18.0 and s["stress"]["mode"] == "moneyness" and s["alerts"] == []  # alerts on the default only
    assert risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-9000.0, 0.0), cfg={"move": 5})[0]["stress"]["strike_pct"] is None


def test_the_worst_case_cap_alerts_and_marks_the_account_over():
    g = grid_for(-5000.0, 0.0)
    over = risk.limits(TR * 5, {"U1": "MGN"}, BOOK, g, cfg={"limit_pct": 10, "cap_pct": 20})[0]  # 5 ids x 4.72% = 23.6%
    assert over["over"] is True and over["cap"] == 20 and "all A14 worst cases add to 23.6% of NAV, over your 20% cap" in over["alerts"]
    under = risk.limits(TR * 4, {"U1": "MGN"}, BOOK, g, cfg={"limit_pct": 10, "cap_pct": 20})[0]  # 18.9%, stress 5%
    assert under["over"] is False and under["alerts"] == []
    assert risk.limits(TR, {"U1": "MGN"}, BOOK, grid_for(-11000.0, 0.0), cfg={"limit_pct": 10, "cap_pct": 20})[0]["over"] is True  # stress alone


def test_stress_without_a_nav_reads_nothing_and_rule_alerts_still_come_through():
    L = risk.limits(TR * 5, {"U1": "MGN"}, {"margin": []}, grid_for(-21000.0, 0.0), cfg={"limit_pct": 10})[0]
    assert L["stress"]["pct"] is None and L["nav_usd"] is None and L["alerts"] == ["5 SPX ids open: the rule's cap is 4"]


# ------------------------------------------------------------------ jumps: how often, against the VIX's σ
@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_PATH", tmp_path / "t.db")
    db.init()
    market._init()
    journal.init()
    return tmp_path


def test_jump_frequencies_count_each_way_and_on_calm_days(desk):
    d0, px, rows, vix = dt.date(2000, 1, 3), 1000.0, [], []
    moves = {100: -0.045, 200: -0.031, 300: 0.052, 400: -0.06}  # one 4.5% fall from a calm VIX, a 3.1% fall, a 5.2% rise, a 6% fall from a high VIX
    for i in range(600):
        px *= 1 + moves.get(i, 0.0)
        d = (d0 + dt.timedelta(days=i)).isoformat()
        rows.append(("^GSPC", d, px, px, px, px, 0))
        vix.append(("VIX", d, 35.0 if 390 <= i < 400 else 15.0))
    db.write("INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?)", rows, many=True)
    db.write("INSERT INTO index_daily (symbol, date, close) VALUES (?,?,?)", vix, many=True)
    J = risk.jump_freq(16.0, since="2000-01-01")
    r = {x["pct"]: x for x in J["rows"]}
    assert r[3]["down"]["n"] == 3 and r[4]["down"]["n"] == 2 and r[5]["down"]["n"] == 1 and r[5]["up"]["n"] == 1 and r[7]["down"]["n"] == 0
    assert r[4]["down"]["calm_n"] == 1 and r[5]["down"]["calm_n"] == 0  # the 6% fall began with the VIX at 35
    assert r[4]["down"]["last"] == (d0 + dt.timedelta(days=400)).isoformat()
    assert 0 < r[4]["down"]["normal_per_yr"] < 0.02  # a normal curve at VIX 16: a 4% fall about once a century
    assert risk.jump_freq(16.0, since="2030-01-01") is None


# ------------------------------------------------------------------ plans never come from a partial total
def test_a_plan_without_full_marks_is_never_logged(desk):
    out = journal.log_plan([{"key": "a", "act": "marks", "label": "Marks incomplete"}, {"key": "b", "act": "close", "label": "Close: target", "partial": True},
                            {"key": "c", "act": "hold", "label": "Hold", "adj": "yes", "pct": 1.0}], sess="2026-11-06")
    assert out["n"] == 1 and [r["trade_key"] for r in db.query("SELECT trade_key FROM journal_planlog")] == ["c"]


def test_the_plan_can_fall_back_on_this_sessions_fully_priced_total(desk, monkeypatch):
    from desk import recorder
    monkeypatch.setattr(recorder, "session_date", lambda now=None: dt.date(2026, 11, 6))
    db.write("INSERT INTO trade_pnl VALUES (?,?,?,?,?,?,?,?)", [("2026-11-06", "k1", "n", "U1", "SPX", 512.5, 9000.0, "2026-11-06T21:18:59+00:00"),
                                                              ("2026-11-05", "k2", "n", "U1", "SPX", 99.0, 9000.0, "2026-11-05T21:18:59+00:00")], many=True)
    assert risk._full_marks() == {"k1": (512.5, "2026-11-06T21:18:59+00:00")}  # an older session's total is too stale to label from


# ------------------------------------------------------------------ the 13-week target with the week to date
def _weekly(pcts, extra=None):
    start = dt.date(2026, 1, 5)
    weeks = [{"week": (start + dt.timedelta(days=7 * i)).isoformat(), "acct": {"U1": {"pct": p}}, "notes": []} for i, p in enumerate(pcts)]
    return {"accounts": [{"id": "U1", "label": "A"}], "weeks": list(reversed(weeks + (extra or [])))}


def test_the_week_to_date_shows_apart_as_provisional():
    live = {"week": "2026-04-06", "acct": {"U1": {"pct": -13.0}}, "notes": ["week to date (4 of 5 sessions)"]}
    T = ar.target(_weekly([1.0] * 13, extra=[live]), {"A"})["A"]
    assert T["now"] == 1.0 and len(T["weeks"]) == 13  # finished weeks unchanged
    assert T["prov"] == {"d": "2026-04-06", "v": -13.0, "note": "week to date (4 of 5 sessions)", "now": pytest.approx((12 - 13.0) / 13, abs=1e-3)}
    assert ar.target(_weekly([1.0] * 13), {"A"})["A"]["prov"] is None
    assert ar.target(_weekly([1.0] * 5, extra=[live]), {"A"})["A"]["prov"]["now"] is None  # too few weeks for an average


def test_the_rule_page_carries_the_trade_plan_exits():
    r = ar.rule()
    assert (r["target"], r["stop"], r["time_dte"], r["cap"], r["worst_nav"], r["entry_dte"], r["dte_lo"], r["dte_hi"]) == (7.0, 20, 7, 4, 7.5, 49, 42, 56)
