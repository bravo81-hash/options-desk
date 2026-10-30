"""Dates and marks: a wrong day here quietly moves P&L and every entry-day reading."""
import datetime as dt

from desk import conditions, expected, recorder, trades


def test_closing_marks_are_taken_after_the_option_close():
    assert recorder.close_capture("2026-10-29") == "2026-10-29T20:15:00+00:00"  # EDT
    assert recorder.close_capture("2026-12-15") == "2026-12-15T21:15:00+00:00"  # EST


def test_optionstrat_local_time_maps_to_the_us_session():
    assert trades._os_session(dt.datetime(2026, 1, 17, 6, 40)) == dt.date(2026, 1, 16)  # Saturday morning here = Friday's close
    assert trades._os_session(dt.datetime(2026, 7, 15, 6, 40)) == dt.date(2026, 7, 14)
    assert trades._os_session(dt.datetime(2026, 1, 19, 6, 40)) == dt.date(2026, 1, 16)  # Monday morning here: no US session


def test_settled_expiries_drop_and_moves_are_recounted(monkeypatch):
    days = {"20261029": -1, "20261030": 0, "20261106": 7}
    monkeypatch.setattr(expected, "dte", days.get)
    v = {"spot": 100.0, "expiries": [{"expiry": e, "iv": 0.2, "dte": 9, "sd": 99.0} for e in days]}
    expected._age(v)
    assert "20261029" not in [e["expiry"] for e in v["expiries"]]
    assert v["expiries"][-1]["dte"] == 7
    assert round(v["expiries"][-1]["sd"], 2) == round(100 * 0.2 * (7 / 365) ** 0.5, 2)
    assert round(v["day_sd"], 3) == round(100 * 0.2 / 365 ** 0.5, 3)  # from the first expiry a day or more out


def test_ordinals():
    assert [conditions._ordinal(x) for x in (51, 52, 53, 11, 12, 13, 72, 21)] == ["51st", "52nd", "53rd", "11th", "12th", "13th", "72nd", "21st"]
