"""Commissions, one close for every tab: the kind of drift that looks right on each tab on its own."""
import datetime as dt

import pandas as pd
from ib_async import IB, CommissionReport, Contract, Execution

from desk import accounts, backtest, warnings


def test_todays_fills_keep_the_commission_that_req_executions_loses():
    ib, sent = IB(), []
    w = ib.wrapper

    def tws_answers(req):
        w._futures[req], w._results[req] = object(), []
        w.execDetails(req, Contract(), Execution(execId="e1"))
        w.commissionReport(CommissionReport(execId="e1", commission=1.5))
        return w._results[req]

    tws_answers(1)  # the fetch at connect
    ib.reqExecutions = lambda: sent.extend(tws_answers(2)) or sent
    ib.sleep = lambda s: None
    fills = accounts.todays_fills(ib)
    assert sent[0].commissionReport.commission == 0.0
    assert [f.commissionReport.commission for f in fills] == [1.5]


def closes(monkeypatch, live):
    rows = [{"date": "2026-10-28", "c": 100.0}, {"date": "2026-10-29", "c": 101.0}]
    monkeypatch.setattr(backtest.db, "query", lambda *a: rows)
    monkeypatch.setattr(backtest.db, "get_meta", lambda k: live)
    monkeypatch.setattr(backtest, "last_session", lambda: dt.date(2026, 10, 30))
    monkeypatch.setattr(backtest, "series", lambda n, s: pd.Series({"2026-10-29": 999.0, "2026-10-30": 102.0, "2026-11-02": 103.0}))
    return backtest._bars_all("^GSPC")


def test_backtest_takes_finished_closes_from_index_daily(monkeypatch):
    assert closes(monkeypatch, "") == {"2026-10-28": 100.0, "2026-10-29": 101.0, "2026-10-30": 102.0}


def test_a_live_bar_is_not_a_close(monkeypatch):
    assert closes(monkeypatch, "2026-10-30") == {"2026-10-28": 100.0, "2026-10-29": 101.0}


def test_warnings_read_the_last_value_of_a_series_that_is_a_day_late():
    idx = pd.to_datetime(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"])
    out = warnings._asof(pd.Series([0.888], index=idx[:1]), idx)
    assert out.iloc[:4].tolist() == [0.888] * 4 and pd.isna(out.iloc[4])  # at most 3 sessions old


def test_vix_ratio_never_spans_two_days():
    idx = pd.to_datetime(["2026-10-29", "2026-10-30"])
    vix, v3 = pd.Series([17.2], index=idx[:1]), pd.Series([19.37, 20.78], index=idx)  # VIX's file lands later
    assert warnings._ivts(vix, v3, idx).tolist() == [17.2 / 19.37] * 2
