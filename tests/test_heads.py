"""Event risk score, the feeds behind it, the leader and futures rules, and the gap what-if."""
import datetime as dt
import io

import pandas as pd

from desk import heads, risk, trades
from desk.recorder import ET

UTC = dt.timezone.utc


def et(y, m, d, h=12, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=ET)


def z(d):
    return d.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def report(when, sym="X", weight=1.0, top=False):
    return {"sym": sym, "when": z(when), "session": "after close", "firm": True, "weight": weight, "top": top, "groups": []}


def macro(when, title="ISM", kind=None, importance=1):
    return {"date": z(when), "title": title, "kind": kind, "importance": importance}


UP = {"macro": True, "earnings": True}
THU_CLOSE = et(2026, 11, 12, 16)  # an ordinary Thursday


# ---- the trading-hours window
def test_window_is_plain_24_hours_midweek():
    assert heads.window_end(THU_CLOSE, 24) == et(2026, 11, 13, 16)


def test_friday_evening_reaches_monday_evening():
    assert heads.window_end(et(2026, 11, 13, 17), 24) == et(2026, 11, 16, 17)


def test_saturday_covers_all_of_monday():
    assert heads.window_end(et(2026, 10, 31, 10), 24) == et(2026, 11, 3, 0)


def test_market_holiday_does_not_use_the_window_up():
    assert heads.window_end(et(2026, 11, 25, 20), 24) == et(2026, 11, 27, 20)  # across Thanksgiving


# ---- the score
def test_quiet_market_is_green():
    r = heads.event_score(THU_CLOSE, [macro(et(2026, 11, 20, 8), "CPI", "CPI")], [report(et(2026, 11, 13, 7), weight=0.4)], UP)
    assert r["level"] == "green" and r["pct24"] == 0.4


def test_over_15_percent_within_24h_is_red():
    r = heads.event_score(THU_CLOSE, [], [report(et(2026, 11, 13, 7), "A", 8.0), report(et(2026, 11, 13, 8), "B", 7.5)], UP)
    assert r["level"] == "red" and r["pct24"] == 15.5


def test_exactly_15_percent_is_amber_not_red():
    r = heads.event_score(THU_CLOSE, [], [report(et(2026, 11, 13, 7), weight=15.0)], UP)
    assert r["level"] == "amber"


def test_top_tier_release_within_24h_is_red():
    for kind in ("Payrolls", "CPI", "FOMC", "Election"):
        assert heads.event_score(THU_CLOSE, [macro(et(2026, 11, 13, 8, 30), kind, kind)], [], UP)["level"] == "red"


def test_top_tier_release_within_48h_is_amber():
    r = heads.event_score(THU_CLOSE, [macro(et(2026, 11, 16, 8, 30), "CPI", "CPI")], [], UP)
    assert r["level"] == "amber" and "CPI" in r["why"][0]


def test_five_percent_top_ten_and_other_high_impact_are_amber():
    day = et(2026, 11, 13, 8)
    assert heads.event_score(THU_CLOSE, [], [report(day, weight=5.0)], UP)["level"] == "amber"
    assert heads.event_score(THU_CLOSE, [], [report(day, "NVDA", 2.0, top=True)], UP)["level"] == "amber"
    assert heads.event_score(THU_CLOSE, [macro(day)], [], UP)["level"] == "amber"


def test_medium_release_alone_stays_green():
    assert heads.event_score(THU_CLOSE, [macro(et(2026, 11, 13, 8), importance=0)], [], UP)["level"] == "green"


def test_past_events_do_not_count():
    assert heads.event_score(THU_CLOSE, [macro(et(2026, 11, 12, 8), "CPI", "CPI")], [report(et(2026, 11, 12, 7), weight=20)], UP)["level"] == "green"


def test_feed_down_reads_unknown_never_green():
    r = heads.event_score(THU_CLOSE, [], [], {"macro": True, "earnings": False})
    assert r["level"] == "unknown" and r["feeds_down"] == ["earnings"] and "unavailable" in r["why"][0]


def test_feed_down_does_not_hide_a_known_event():
    r = heads.event_score(THU_CLOSE, [macro(et(2026, 11, 13, 8, 30), "CPI", "CPI")], [], {"macro": False, "earnings": True})
    assert r["level"] == "red" and r["feeds_down"] == ["macro calendar"]


def test_saturday_sees_mondays_reports_and_tuesday_nights_election():
    now = et(2026, 10, 31, 10)
    r = heads.event_score(now, [macro(et(2026, 11, 3, 19), "US midterm election", "Election")], [report(et(2026, 11, 2, 17, 30), "AAPL", 7.65, top=True)], UP)
    assert r["level"] == "amber" and r["pct24"] == 7.7 and any("election" in w for w in r["why"])


# ---- when a name reports
def test_tradingview_time_wins_when_it_is_confirmed():
    when, session, firm = heads.report_time({"sym": "AAPL", "next": 1793655000, "code": 1}, {"AAPL": ["2026-11-03", "time-after-hours"]})
    assert when == dt.datetime.fromtimestamp(1793655000, UTC) and session == "after close" and firm


def test_unconfirmed_date_defers_to_nasdaq():
    when, session, firm = heads.report_time({"sym": "XOM", "next": 1793655000, "code": 0}, {"XOM": ["2026-11-06", "time-pre-market"]})
    assert when.astimezone(ET).date().isoformat() == "2026-11-06" and session == "before open" and firm


def test_nasdaq_without_a_time_stays_an_estimate():
    _, session, firm = heads.report_time({"sym": "BRK.B", "next": 1793655000, "code": 0}, {"BRK.A": ["2026-11-06", "time-not-supplied"]})
    assert session == "time not set" and not firm


def test_no_source_at_all_is_no_date():
    assert heads.report_time({"sym": "X", "next": None, "code": 0}, {})[0] is None


def test_two_share_classes_count_as_one_issuer():
    row = lambda s: {"sym": s, "name": s, "cap": 100.0, "idx": ["SPX"]}  # noqa: E731
    iss = heads.issuers({"GOOGL": row("GOOGL"), "GOOG": row("GOOG"), "NVDA": row("NVDA")}, {"GOOGL": 2.5, "GOOG": 2.0, "NVDA": 7.8})
    assert set(iss) == {"GOOGL", "NVDA"} and iss["GOOGL"]["weight"] == 4.5


def test_weights_fall_back_to_market_cap_share():
    row = lambda s, c: {"sym": s, "name": s, "cap": c, "idx": ["SPX"]}  # noqa: E731
    assert heads.issuers({"A": row("A", 300.0), "B": row("B", 100.0)}, {})["A"]["weight"] == 75.0


# ---- parsers
def test_parse_ssga_finds_the_header_and_the_date():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Fund Name:", "SPDR"])
    ws.append(["Ticker Symbol:", "SPY"])
    ws.append(["Holdings:", "As of 29-Oct-2026"])
    ws.append([])
    ws.append(["Name", "Ticker", "Identifier", "Weight"])
    for i in range(25):
        ws.append([f"Co {i}", f"T{i}", "x", 1.0 + i])
    ws.append(["Cash", "-", "x", 0.1])
    b = io.BytesIO()
    wb.save(b)
    w, asof = heads.parse_ssga(b.getvalue())
    assert asof == "2026-10-29" and len(w) == 25 and w["T3"] == 4.0 and "-" not in w


def test_parse_vx_keeps_monthlies_in_expiry_order():
    csv = "Product,Symbol,Expiration Date,Price\nVX,VX/Z6,2026-12-16,19.79\nVX,VX44/X6,2026-11-04,20.36\nVX,VX/X6,2026-11-18,20.36\nVXM,VXM/X6,2026-11-18,20.4\n"
    assert [r["sym"] for r in heads.parse_vx(csv)] == ["VX/X6", "VX/Z6"]


def test_futures_compare_with_their_own_price_at_the_close():
    idx = pd.to_datetime(["2026-10-29 19:50", "2026-10-29 19:55", "2026-10-29 20:00", "2026-10-30 08:00"], utc=True)
    r = heads.move_since(pd.Series([7600.0, 7700.0, 7690.0, 7623.0], index=idx), et(2026, 10, 29, 16))
    assert r["ref"] == 7700.0 and round(r["chg"], 2) == -1.0 and len(r["spark"]) == 2


def test_quote_session_follows_the_et_clock():
    assert [heads.session(et(2026, 11, 2, h)) for h in (3, 8, 12, 17)] == ["post", "pre", "regular", "post"]
    assert heads.session(et(2026, 11, 1, 8)) == "post"


# ---- leaders
def closes(*moves):
    px, out = 100.0, []
    for k in range(70):
        px *= 1 + (0.01 if k % 2 else -0.01)
        out.append(px)
    for m in moves:
        px *= 1 + m / 100
        out.append(px)
    return pd.Series(out, index=[f"d{i}" for i in range(len(out))])


def test_three_sigma_day_breaks():
    m = heads.leader_moves(closes(-4.0))[0]
    assert m["z"] <= -3 and heads.is_break(m)


def test_seven_percent_day_breaks_on_a_volatile_name():
    assert heads.is_break({"ret": -7.2, "z": -2.0})


def test_ordinary_down_day_does_not_break():
    assert not heads.is_break(heads.leader_moves(closes(-1.0))[0])
    assert not heads.is_break({"ret": 9.0, "z": 5.0})


# ---- gap what-if
def fake_trade(und="SPX", acct="A", qty=-1, strike=5000.0, right="P", days=30, iv=0.2, spot=5000.0):
    exp = (dt.datetime.now(UTC) + dt.timedelta(days=days)).isoformat()
    return {"underlying": und, "spot": spot, "ib_account": acct, "group": acct, "legs": [{"qty": qty, "strike": strike, "right": right, "expiry_iso": exp, "mark": {"iv": iv}}]}


LABELS = {"A": "Acct A", "B": "Acct B"}
FUT = {"ts": "2026-11-02T01:00:00Z", "chg": {"SPX": -1.0, "RUT": -2.0}}
NOW = et(2026, 11, 2, 18)  # Monday evening: the next open is Tuesday's


def grid(*t, **k):
    return risk.gap_grid(list(t), LABELS, k.pop("futures", None), now=NOW, **k)


def test_next_open_skips_weekends_and_holidays():
    assert risk.next_open(et(2026, 10, 30, 17)) == et(2026, 11, 2, 9, 30)
    assert risk.next_open(et(2026, 11, 25, 17)) == et(2026, 11, 27, 9, 30)
    assert risk.next_open(et(2026, 11, 2, 8)) == et(2026, 11, 2, 9, 30)
    assert risk.next_open(et(2026, 11, 2, 12)) == et(2026, 11, 3, 9, 30)


def test_short_put_loses_on_a_gap_down_and_gains_on_a_gap_up():
    g = grid(fake_trade())
    assert g["rows"] == ["-2.5%", "-1.5%", "+1.5%", "+2.5%"] and g["vols"] == [-3, 0, 3, 6]
    flat = [row[1] for row in g["total"]]
    assert flat[0] < flat[1] < 0 < flat[2] < flat[3]


def test_short_premium_is_hurt_by_a_higher_vix():
    row = grid(fake_trade())["total"][0]
    assert row[0] > row[1] > row[2] > row[3]


def test_accounts_add_up_to_the_total():
    g = grid(fake_trade(acct="A"), fake_trade(acct="B", strike=4900.0), fake_trade(acct="A", und="RUT", spot=2300.0, strike=2200.0))
    assert [a["label"] for a in g["accounts"]] == ["Acct A", "Acct B"]
    for i, row in enumerate(g["total"]):
        for j, v in enumerate(row):
            assert abs(v - sum(a["cells"][i][j] for a in g["accounts"])) < 1e-6


def test_rut_moves_by_beta_on_the_percent_rows():
    t = fake_trade(und="RUT", spot=2300.0, strike=2300.0)
    a, b = grid(t, beta=1.0)["total"][0][1], grid(t, beta=2.0)["total"][0][1]
    assert b < a


def test_futures_row_uses_each_index_own_move():
    g = grid(fake_trade(), fake_trade(und="RUT", spot=2300.0, strike=2300.0), futures=FUT)
    assert g["rows"][2] == "Futures now" and g["futures"] == FUT["chg"]
    alone = grid(fake_trade(), futures={"chg": {"SPX": -1.0}})
    assert g["total"][2][1] < alone["total"][2][1]  # RTY's -2% adds a second loss


def test_stock_trades_take_the_spx_future():
    a = grid(fake_trade(und="NKE", spot=60.0, strike=60.0), futures={"chg": {"SPX": -2.0}})
    assert a["total"][2][1] < 0


def test_no_futures_quote_drops_the_row():
    assert "Futures now" not in grid(fake_trade(), futures={"chg": {}})["rows"]


def test_trade_without_a_spot_is_left_out_rather_than_breaking_the_grid():
    g = grid(fake_trade(), {**fake_trade(acct="B"), "spot": None})
    assert [a["label"] for a in g["accounts"]] == ["Acct A"]


def test_trade_expiring_before_the_open_is_frozen_at_expiry():
    soon = fake_trade(days=0.01, strike=5000.0, iv=0.2)
    v = grid(soon)["total"][1][1]  # -1.5%: intrinsic loss only, whatever the VIX shift
    assert v == grid(soon)["total"][1][3] or abs(v - grid(soon)["total"][1][3]) < 1e-9


def test_bad_iv_takes_the_expiry_average():
    t = fake_trade()
    t["legs"].append({**t["legs"][0], "qty": 1, "strike": 4800.0, "mark": {"iv": 9.0}})
    assert risk._legs(t)[1][3] == 0.2


def test_overnight_risk_shows_short_gamma_and_both_tails():
    r = risk.overnight_risk([fake_trade(right="P"), fake_trade(right="C")], 20.0, now=NOW)
    assert r["gamma_1pct"] < 0 and r["down2"] < 0 and r["up2"] < 0 and round(r["sd_pct"], 2) == 1.05


def test_overnight_risk_needs_a_vix():
    assert risk.overnight_risk([fake_trade()], None) is None


# ---- display fixes
def test_name_fix_is_whole_word_only(monkeypatch):
    monkeypatch.setattr(trades, "load_config", lambda: {"risk": {"name_fixes": {"MNG": "MGN"}}})
    assert trades.fix_name("13 NOV.A14.MNG.RUT - 4 LOTS") == "13 NOV.A14.MGN.RUT - 4 LOTS"
    assert trades.fix_name("MNGO.A14") == "MNGO.A14"
