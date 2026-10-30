"""Release dates, IV at strikes and next-day entries: quiet errors here would mislead without looking wrong."""
import datetime as dt
import math

import numpy as np

from desk import analytics, backtest, market, risk


def day(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_releases_keep_the_headline_prints_only():
    rows = [{"title": t, "date": d} for t, d in [
        ("Inflation Rate YoY", "2026-11-10T13:30:00.000Z"), ("Core Inflation Rate MoM", "2026-11-10T13:30:00.000Z"), ("CPI s.a", "2026-11-10T13:30:00.000Z"),
        ("Non Farm Payrolls", "2026-11-06T13:30:00.000Z"), ("Manufacturing Payrolls", "2026-11-06T13:30:00.000Z"),
        ("FOMC Minutes", "2026-11-18T19:00:00.000Z"), ("Michigan Inflation Expectations Prel", "2026-11-06T15:00:00.000Z"),
        ("Atlanta Fed GDPNow", "2026-11-02T16:00:00.000Z"), ("GDP Growth Rate QoQ 2nd Est", "2026-11-25T13:30:00.000Z"),
        ("Core PCE Price Index MoM", "2026-11-25T13:30:00.000Z"), ("Fed Barkin Speech", "2026-10-30T13:30:00.000Z")]]
    assert [(r["date"], r["kind"]) for r in market.parse_releases(rows)] == [
        ("2026-11-06", "Payrolls"), ("2026-11-10", "CPI"), ("2026-11-25", "GDP"), ("2026-11-25", "PCE")]


def test_fomc_days_are_the_last_day_of_each_meeting():
    html = """<a>2026 FOMC Meetings</a>
    <div class="fomc-meeting__month x"><strong>October</strong></div><div class="fomc-meeting__date y">27-28</div><a>Statement</a>
    <div class="fomc-meeting__month x"><strong>December</strong></div><div class="fomc-meeting__date y">8-9*</div>
    <a>2027 FOMC Meetings</a>
    <div class="fomc-meeting__month x"><strong>Jan/Feb</strong></div><div class="fomc-meeting__date y">31-1</div>"""
    assert market.parse_fomc(html) == ["2026-10-28", "2026-12-09", "2027-02-01"]


def test_an_empty_list_is_not_called_clean_past_the_known_dates():
    rel = {"ok": True, "rows": [{"date": day(5), "kind": "CPI", "title": "CPI"}, {"date": day(-1), "kind": "PCE", "title": "PCE"}], "ts": "x", "to": day(30)}
    inside = market.releases_past(rel, day(10))
    assert [e["kind"] for e in inside["events"]] == ["CPI"] and inside["beyond"] is False
    assert market.releases_past(rel, day(3)) == {"events": [], "beyond": False}
    assert market.releases_past(rel, day(40))["beyond"] is True
    assert market.releases_past({**rel, "ok": False}, day(10)) == {"events": None, "beyond": True}


def test_calendar_checks_read_iv_at_the_trades_own_strikes():
    leg = lambda q, d, iv: {"qty": q, "right": "P", "strike": 100.0, "expiry_iso": f"{day(d)}T16:00:00-04:00", "mark": {"iv": iv}}
    rel = {"ok": True, "rows": [{"date": day(5), "kind": "CPI", "title": "CPI"}, {"date": day(20), "kind": "FOMC", "title": "FOMC"}], "ts": "x", "to": day(60)}
    out = risk.calendar_checks({"legs": [leg(-2, 14, 0.15), leg(2, 21, 0.17)]}, rel, 12.0)
    p = out["pairs"][0]
    fwd = 100 * math.sqrt((0.17 ** 2 * 21 - 0.15 ** 2 * 14) / 7)
    assert (p["fdte"], p["bdte"], p["front_iv"], p["back_iv"], p["spread"]) == (14, 21, 15.0, 17.0, 2.0)
    assert p["fwd_vol"] == round(fwd, 2) and p["fwd_vs_rv"] == round(fwd - 12, 2)
    assert [e["kind"] for e in p["events"]] == ["CPI"]  # the FOMC falls after the front expires


def test_a_long_only_or_single_expiry_trade_has_no_calendar_pairs():
    leg = lambda q, s: {"qty": q, "right": "P", "strike": s, "expiry_iso": f"{day(14)}T16:00:00-04:00", "mark": {"iv": 0.2}}
    rel = {"ok": True, "rows": [], "ts": "x", "to": day(60)}
    assert risk.calendar_checks({"legs": [leg(1, 100.0), leg(-2, 95.0), leg(1, 90.0)]}, rel, 12.0)["pairs"] == []


def test_strike_ivs_interpolate_each_smile_onto_one_grid(monkeypatch):
    smiles = {"F": [(90.0, 0.30, 7), (100.0, 0.20, 7), (110.0, 0.10, 7)], "B": [(95.0, 0.26, 21), (105.0, 0.18, 21)]}
    monkeypatch.setattr(analytics.db, "query", lambda sql, a: [{"strike": k, "iv": v, "dte": d} for k, v, d in smiles[a[1]]])
    rows = analytics.strike_ivs(1, "F", "B", 100.0, 100.0)
    assert [r["strike"] for r in rows] == [95.0, 100.0, 105.0]  # 90 and 110 are outside the back smile: not extrapolated
    assert rows[1]["front"] == 20.0 and rows[1]["back"] == 22.0 and rows[1]["spread"] == 2.0


def fake_days(n=60):
    d0 = dt.date(2026, 1, 1)
    days = [d0 + dt.timedelta(days=i) for i in range(n * 2)]
    days = [d for d in days if d.weekday() < 5][:n]
    return {"date": np.array(days, dtype=object), "SPX": np.full(len(days), 100.0)}


def test_next_day_keeps_the_signal_but_moves_the_fill(monkeypatch):
    D = fake_days()
    monkeypatch.setattr(backtest, "_cond", lambda D, u, i: {"signal": i})
    monkeypatch.setattr(backtest, "_cost", lambda *a: 0.0)
    monkeypatch.setattr(backtest, "_bwb", lambda *a: (102.0, 100.0, 96.0))
    monkeypatch.setattr(backtest, "_span", lambda D, i0, exp: i0 + 3 if i0 + 3 < len(D["date"]) else None)
    monkeypatch.setattr(backtest, "_bwb_value", lambda D, u, idx, exp, K: (np.ones(len(idx)), np.ones((len(idx), 3))))
    same, nxt = backtest.a14_paths(D, "SPX", 45), backtest.a14_paths(D, "SPX", 45, lag=1)
    assert same and nxt
    assert all(D["date"][p["cond"]["signal"]].weekday() == 4 and p["i0"] == p["cond"]["signal"] for p in same)
    assert all(D["date"][p["cond"]["signal"]].weekday() == 4 and p["i0"] == p["cond"]["signal"] + 1 for p in nxt)
