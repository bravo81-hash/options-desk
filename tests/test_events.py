"""The size call must only see releases still to come: past events never step a structure down."""
import datetime as dt
import json

from desk import db, market, readiness


def _feed(monkeypatch, *when):
    feed = json.dumps([{"country": "USD", "impact": "High", "title": "FOMC Statement", "date": w.isoformat()} for w in when])
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    monkeypatch.setattr(db, "get_meta", lambda key: stamp if key.endswith(":ts") else feed if key == "ff:thisweek" else "[]")
    monkeypatch.setattr(market, "KNOWN", {})  # the real schedule would make these depend on today's date


def test_past_events_are_ignored_when_nothing_is_coming(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    _feed(monkeypatch, now - dt.timedelta(days=2))
    assert readiness._events() == []


def test_event_earlier_today_is_ignored(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    _feed(monkeypatch, now - dt.timedelta(minutes=1), now + dt.timedelta(days=30))
    assert readiness._events() == []


def test_coming_event_counts(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    _feed(monkeypatch, now + dt.timedelta(days=1))
    assert [e["title"] for e in readiness._events()] == ["FOMC Statement"]


def test_market_page_still_falls_back_to_the_week(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    _feed(monkeypatch, now - dt.timedelta(days=2))
    assert market.calendar(now.date().isoformat(), now.date().isoformat())["result"]


# ---- the feed fallback: a week the feeds don't cover must never read as a week with no events
def _feeds(monkeypatch, ff=None, tv=None, tv_age_days=0):
    now = dt.datetime.now()
    meta = {"ff:thisweek": json.dumps(ff) if ff is not None else None, "ff:thisweek:ts": now.isoformat() if ff is not None else None,
            "tv:events": json.dumps(tv or []), "tv:events:ts": (now - dt.timedelta(days=tv_age_days)).isoformat(), "fed:fomc": "[]"}
    monkeypatch.setattr(db, "get_meta", lambda key: meta.get(key))
    monkeypatch.setattr(db, "set_meta", lambda *a: None)
    monkeypatch.setattr(market, "_ff_tried", dt.datetime.now())  # no network in tests


def _soon(days, hour=12):
    d = dt.datetime.now(dt.timezone.utc).replace(hour=hour, minute=30, second=0, microsecond=0) + dt.timedelta(days=days)
    return d.isoformat(timespec="seconds").replace("+00:00", "Z")


def _window(days=7):
    today = dt.datetime.now(dt.timezone.utc).date()
    return today.isoformat(), (today + dt.timedelta(days=days)).isoformat()


def test_both_feeds_down_shows_the_known_schedule_and_says_so(monkeypatch):
    day = _soon(2)[:10]
    monkeypatch.setattr(market, "KNOWN", {"Payrolls": ("08:30", "Nonfarm payrolls (schedule)", [day])})
    _feeds(monkeypatch)
    r = market.calendar(*_window())
    assert r["feed"] == "unavailable" and "unavailable" in r["note"]
    assert [(e["title"], e["kind"], e["source"]) for e in r["result"]] == [("Nonfarm payrolls (schedule)", "Payrolls", "schedule")]


def test_stale_feed_is_reported_as_down_rather_than_empty(monkeypatch):
    """Forex Factory's file still holding last week, TradingView down: the case that showed 'no events'."""
    monkeypatch.setattr(market, "KNOWN", {})
    _feeds(monkeypatch, ff=[{"country": "USD", "impact": "High", "title": "CPI m/m", "date": _soon(-6)}])
    r = market.calendar(*_window(), widen=False)
    assert r["result"] == [] and r["feed"] == "unavailable" and r["note"]


def test_tradingview_covers_the_days_after_forex_factory(monkeypatch):
    monkeypatch.setattr(market, "KNOWN", {})
    ff = [{"country": "USD", "impact": "High", "title": "CPI m/m", "date": _soon(-1)}, {"country": "USD", "impact": "Low", "title": "Bill auction", "date": _soon(1)}]
    tv = [{"date": _soon(-1), "title": "Inflation Rate YoY", "importance": 1, "kind": "CPI", "source": "tv"},  # Forex Factory's day: its own row stands
          {"date": _soon(3), "title": "ISM Manufacturing PMI", "importance": 1, "kind": None, "source": "tv"}]
    _feeds(monkeypatch, ff=ff, tv=tv)
    today = dt.datetime.now(dt.timezone.utc).date()
    r = market.calendar((today - dt.timedelta(days=2)).isoformat(), (today + dt.timedelta(days=3)).isoformat())
    assert [e["title"] for e in r["result"]] == ["CPI m/m", "ISM Manufacturing PMI"] and r["feed"] == "ok"


def test_known_row_only_when_the_feeds_lack_that_event(monkeypatch):
    day = _soon(3)
    monkeypatch.setattr(market, "KNOWN", {"Payrolls": ("08:30", "Nonfarm payrolls (schedule)", [day[:10]]), "CPI": ("08:30", "CPI (schedule)", [_soon(4)[:10]])})
    _feeds(monkeypatch, tv=[{"date": day, "title": "Non Farm Payrolls", "importance": 1, "kind": "Payrolls", "source": "tv"}])
    assert [e["title"] for e in market.calendar(*_window())["result"]] == ["Non Farm Payrolls", "CPI (schedule)"]


def test_election_keeps_its_evening_time_not_the_feeds_date_only_row(monkeypatch):
    monkeypatch.setattr(market, "KNOWN", {"Election": ("19:00", "US midterm election", [_soon(2)[:10]])})
    _feeds(monkeypatch, tv=[{"date": _soon(2, 0), "title": "Midterm Elections", "importance": 1, "kind": None, "source": "tv"}, {"date": _soon(5), "title": "ISM", "importance": 1, "kind": None, "source": "tv"}])
    r = [e for e in market.calendar(*_window())["result"] if "lection" in e["title"]]
    assert len(r) == 1 and r[0]["kind"] == "Election" and r[0]["date"][11:13] in ("23", "00")  # 19:00 ET


def test_old_tradingview_copy_does_not_count_as_a_live_feed(monkeypatch):
    monkeypatch.setattr(market, "KNOWN", {})
    _feeds(monkeypatch, tv=[{"date": _soon(1), "title": "ISM", "importance": 1, "kind": None, "source": "tv"}], tv_age_days=5)
    r = market.calendar(*_window())
    assert r["feed"] == "unavailable" and r["result"]  # still shown, flagged


def test_partial_window_says_where_the_feeds_stop(monkeypatch):
    monkeypatch.setattr(market, "KNOWN", {})
    _feeds(monkeypatch, tv=[{"date": _soon(2), "title": "ISM", "importance": 1, "kind": None, "source": "tv"}])
    r = market.calendar(*_window(10))
    assert r["feed"] == "partial" and r["live_to"] == _soon(2)[:10] and r["live_to"] in r["note"]


def test_step_down_sees_tradingview_titles_but_not_the_election(monkeypatch):
    monkeypatch.setattr(market, "KNOWN", {"Election": ("19:00", "US midterm election", [_soon(2)[:10]])})
    _feeds(monkeypatch, tv=[{"date": _soon(2), "title": "Non Farm Payrolls", "importance": 1, "kind": "Payrolls", "source": "tv"},
                            {"date": _soon(2), "title": "ISM Manufacturing PMI", "importance": 1, "kind": None, "source": "tv"}])
    assert [e["title"] for e in readiness._events()] == ["Non Farm Payrolls"]


def test_step_down_skips_titles_that_only_look_like_big_releases(monkeypatch):
    rows = [("Atlanta Fed GDPNow", None), ("Nonfarm Productivity QoQ Prel", None), ("GDP Growth Rate QoQ 2nd Est", "GDP")]
    _feeds(monkeypatch, tv=[{"date": _soon(2), "title": t, "importance": 0, "kind": k, "source": "tv"} for t, k in rows])
    assert [e["title"] for e in readiness._events()] == ["GDP Growth Rate QoQ 2nd Est"]


def test_parse_events_keeps_medium_and_high_only():
    rows = [{"title": "A", "date": "2026-11-02T15:00:00.000Z", "importance": 1}, {"title": "B", "date": "2026-11-02T15:00:00.000Z", "importance": 0},
            {"title": "C", "date": "2026-11-02T15:00:00.000Z", "importance": -1}]
    out = market.parse_events(rows)
    assert [(e["title"], e["importance"], e["date"]) for e in out] == [("A", 1, "2026-11-02T15:00:00Z"), ("B", 0, "2026-11-02T15:00:00Z")]


def test_forex_factory_titles_map_to_the_same_kinds():
    assert [market._release_kind(t) for t in ("Non-Farm Employment Change", "Federal Funds Rate", "Advance GDP q/q", "Core PCE Price Index m/m", "CPI m/m", "FOMC Meeting Minutes", "ISM Services PMI")] \
        == ["Payrolls", "FOMC", "GDP", "PCE", "CPI", None, None]
