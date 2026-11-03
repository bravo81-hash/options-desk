"""The A14 rule page: sizing, expiry and strike choice, the tilt, the 13-week target and the Journal checks."""
import datetime as dt

import pytest

from desk import a14rules as ar, positions


def test_tilt_moves_only_past_the_line():
    assert ar.tilt(1.01) == ar.TILT_SD
    assert ar.tilt(-1.01) == -ar.TILT_SD
    assert ar.tilt(1.0) == 0.0 and ar.tilt(-1.0) == 0.0 and ar.tilt(0.0) == 0.0
    assert ar.tilt(None) == 0.0


def test_worst_case_follows_the_stop():
    r = ar.rule()
    assert r["worst_nav"] == 7.5 and r["stop"] == 20 and r["time_dte"] == 7


@pytest.mark.parametrize("size,want", [("Full size", 2), ("Three-quarter size", 1), ("Half size", 1), ("Quarter size", 0), ("Stand aside", 0)])
def test_lots_scale_with_the_readiness_step_and_round_down(size, want):
    assert ar.lots(5000, 143000, size) == want  # 7.5% of 143k = 10,725 of worst case at full size


def test_lots_never_pass_the_rule():
    for nav in (50000, 143000, 178000):
        for risk in (2400, 5100):
            n = ar.lots(risk, nav, "Full size")
            assert n * risk * 0.20 <= nav * ar.STOP_NAV / 100


def test_lots_without_a_price():
    assert ar.lots(0, 143000, "Full size") == 0
    assert ar.lots(5000, 143000, "Not a step") == 0


def _sm(*days):
    base = dt.date(2026, 11, 2)
    return {(base + dt.timedelta(days=d)).strftime("%Y%m%d"): {"dte": d} for d in days}


def test_expiry_is_the_friday_nearest_49():
    assert ar.expiry_for(_sm(39, 46, 53, 60))[:8] == (dt.date(2026, 11, 2) + dt.timedelta(days=46)).strftime("%Y%m%d")


def test_expiry_ignores_days_that_are_not_friday():
    fri, wed = dt.date(2026, 12, 18), dt.date(2026, 12, 23)  # 46 DTE Friday, 51 DTE Wednesday
    S = {fri.strftime("%Y%m%d"): {"dte": 46}, wed.strftime("%Y%m%d"): {"dte": 51}}
    assert ar.expiry_for(S) == fri.strftime("%Y%m%d")


def test_expiry_none_outside_the_window():
    assert ar.expiry_for(_sm(4, 11, 74)) is None


def test_expiry_takes_the_sooner_on_a_tie():
    fri = dt.date(2026, 12, 11)
    S = {fri.strftime("%Y%m%d"): {"dte": 45}, (fri + dt.timedelta(days=7)).strftime("%Y%m%d"): {"dte": 53}}
    assert ar.expiry_for(S) == fri.strftime("%Y%m%d")


def test_strikes_snap_to_the_chain_and_keep_the_lower_wing_wide():
    ks = list(range(6000, 8000, 25))
    u, s, l = ar.strikes(7500, 0.07, (0.0, 0.29, 0.38), 0.0, ks)
    assert u in ks and s in ks and l in ks
    assert l < s < u and s - l >= u - s


def test_tilt_lifts_the_whole_tent():
    ks = list(range(6000, 9000, 5))
    base, up = ar.strikes(7500, 0.07, (0.0, 0.29, 0.38), 0.0, ks), ar.strikes(7500, 0.07, (0.0, 0.29, 0.38), 0.2, ks)
    assert all(b < c for b, c in zip(base, up))


def test_next_id_prices_the_rule_shape(monkeypatch):
    import numpy as np
    from desk import a14, backtest
    sm = {"20261218": {"F": 7500.0, "dte": 46, "T": 46 / 365, "strikes": list(range(6000, 8000, 25))}}
    monkeypatch.setattr(a14, "_smiles", lambda sb: sm)
    monkeypatch.setattr(a14, "_iv_at", lambda s, k: np.full(np.shape(k), 0.18))
    monkeypatch.setattr(a14, "trend", lambda u: {"vs_sma20": 1.5})
    monkeypatch.setattr(backtest, "sd_now", lambda D, u, d: 0.07)
    n = ar.next_id("SPX", {"symbols": {"SPX": {"spot": 7500.0}}}, {}, 143000)
    assert n["expiry"] == "20261218" and n["tilt"] == ar.TILT_SD and n["upper"] > n["short"] > n["lower"]
    assert n["risk"] == pytest.approx(max(n["L"] - n["U"] - n["credit"], -n["credit"], 0.05) * 100, abs=2)
    assert n["theta"] > 0 and n["vega"] < 0
    assert n["lots"]["Full size"] >= n["lots"]["Half size"] >= n["lots"]["Stand aside"] == 0


def test_next_id_without_a_chain():
    assert ar.next_id("SPX", {}, {}, 143000) is None


def _weekly(pcts, name="A", extra=None):
    start = dt.date(2026, 1, 5)
    weeks = [{"week": (start + dt.timedelta(days=7 * i)).isoformat(), "acct": {"U1111111": {"pct": p}}, "notes": []} for i, p in enumerate(pcts)]
    return {"accounts": [{"id": "U1111111", "label": name}], "weeks": list(reversed(weeks + (extra or [])))}


def test_target_is_the_13_week_mean_of_the_last_finished_weeks():
    T = ar.target(_weekly([0.0] * 3 + [1.0] * 13), {"A"})["A"]
    assert T["now"] == 1.0 and T["n"] == 13 and T["hit"] == 13 and len(T["series"]) == 4
    assert T["series"][0]["v"] == pytest.approx(10 / 13, abs=1e-3)


def test_target_leaves_out_the_week_in_progress():
    live = {"week": "2027-01-04", "acct": {"U1111111": {"pct": 50.0}}, "notes": ["week to date (1 of 5 sessions)"]}
    T = ar.target(_weekly([1.0] * 13, extra=[live]), {"A"})["A"]
    assert T["now"] == 1.0 and len(T["weeks"]) == 13


def test_target_needs_13_weeks_and_a_traded_account():
    assert ar.target(_weekly([1.0] * 5), {"A"})["A"]["now"] is None
    assert ar.target(_weekly([1.0] * 20), {"Other"}) == {}


def _row(**k):
    return {"strategy": "A14", "entry_us": "2026-11-06", "exit_us": None, "close": None, "ret": None, "dte_exit": None, "plan_pct": 1.4, "lots0": 8, "lots_peak": 8, "dte0": 49,
            "ladder_n": 3, "off_window": 0, "ivts": None, **k}


def _by(checks):
    return {c[0]: c[1:] for c in checks}


def test_a_trade_on_the_rules_passes_every_check():
    C = _by(ar.checks(_row(), "2026-11-06"))
    assert set(C) == {"a14size", "a14add", "a14dte", "a14day", "a14cap", "a14window"}
    assert all(v == [True, True] for v in C.values())


@pytest.mark.parametrize("field,value,rule", [("plan_pct", 1.6, "a14size"), ("lots_peak", 12, "a14add"), ("dte0", 41, "a14dte"), ("dte0", 57, "a14dte"), ("ladder_n", 5, "a14cap"), ("off_window", 1, "a14window")])
def test_each_rule_fails_on_its_own(field, value, rule):
    C = _by(ar.checks(_row(**{field: value}), "2026-11-06"))
    assert [k for k, v in C.items() if not v[0]] == [rule]


def test_entry_must_be_a_friday():
    assert _by(ar.checks(_row(), "2026-11-04"))["a14day"][0] is False


def test_a_trade_is_never_marked_down_by_a_later_rule():
    assert all(c[2] is False for c in ar.checks(_row(plan_pct=9, entry_us="2026-10-30"), "2026-10-30"))
    assert all(c[2] is True for c in ar.checks(_row(), ar.FROM))


def test_the_old_time_stop_scores_ids_entered_before_the_change():
    base = {"close": "x", "ret": 1, "plan_pct": None, "cap": None, "exit_us": "2026-11-20", "ivts": None}
    old = _by(positions.rule_checks(_row(**{**base, "entry_us": "2026-10-23", "dte_exit": 3}), 2.0))
    new = _by(positions.rule_checks(_row(**{**base, "entry_us": "2026-11-06", "dte_exit": 3}), 2.0))
    assert old["time"][0] is True and new["time"][0] is False


def test_score_fields_counts_the_ladder_and_off_window_adjustments():
    at = lambda s: dt.datetime.fromisoformat(s)  # noqa: E731
    r = lambda k, e, c=None: {"key": k, "keys": [k], "strategy": "A14", "acct": "A", "ticker": "SPX", "entry": at(e), "close": at(c) if c else None}  # noqa: E731
    rows = [r("a", "2026-10-02 06:00"), r("b", "2026-10-09 06:00", "2026-10-12 06:00"), r("c", "2026-10-16 06:00")]
    # Sydney stamps: 07:00 on the 14th is the US Tuesday the 13th, 07:00 on the 15th is the US Wednesday the 14th
    pos = {"a": {"events": [at("2026-10-02 06:00"), at("2026-10-14 07:00"), at("2026-10-15 07:00")], "flat": False},
           "b": {"events": [at("2026-10-09 06:00"), at("2026-10-12 06:00")], "flat": True}, "c": {"events": [at("2026-10-16 06:00")], "flat": False}}
    ar.score_fields(rows, pos)
    assert [x["ladder_n"] for x in rows] == [1, 2, 2]
    assert [x["off_window"] for x in rows] == [1, 0, 0]


def test_a_holiday_friday_moves_the_week_to_thursday():
    d = dt.date
    assert ar.weekly(d(2026, 12, 18)) and ar.weekly(d(2026, 12, 24)) and not ar.weekly(d(2026, 12, 23))
    assert ar.entry_day(d(2026, 12, 24)) and not ar.entry_day(d(2026, 12, 25)) and not ar.entry_day(d(2026, 12, 17))
    assert ar.entry_next(d(2026, 11, 3)) == d(2026, 11, 6) and ar.entry_next(d(2026, 12, 21)) == d(2026, 12, 24) and ar.entry_next(d(2026, 11, 6)) == d(2026, 11, 6)
    assert _by(ar.checks(_row(), "2026-12-24"))["a14day"][0] is True


def test_expiry_can_be_a_holiday_thursday():
    S = {"20261218": {"dte": 45}, "20261224": {"dte": 51}}  # Christmas Friday: that week's expiry is the Thursday
    assert ar.expiry_for(S) == "20261224"


def test_the_chain_fetch_keeps_a_holiday_weeks_thursday(monkeypatch):
    from desk import a14
    today = dt.date(2026, 11, 3)
    monkeypatch.setattr(a14, "dte", lambda e: (dt.datetime.strptime(e, "%Y%m%d").date() - today).days)
    params = {e: ("SPXW", [], e) for e in ("20261217", "20261218", "20261223", "20261224", "20261230", "20261231")}
    assert a14._expiries(params, 7, 110) == ["20261218", "20261224", "20261231"]
