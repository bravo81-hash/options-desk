"""The size call must only see releases still to come: past events never step a structure down."""
import datetime as dt
import json

from desk import db, market, readiness


def _feed(monkeypatch, *when):
    feed = json.dumps([{"country": "USD", "impact": "High", "title": "FOMC Statement", "date": w.isoformat()} for w in when])
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    monkeypatch.setattr(db, "get_meta", lambda key: stamp if key.endswith(":ts") else feed if key == "ff:thisweek" else "[]")


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
