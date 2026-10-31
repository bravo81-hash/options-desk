"""IBKR Flex statements: what is read from one, what it replaces, and where the token must never appear."""
import datetime as dt
import json
import xml.etree.ElementTree as ET

import pytest
import requests

from desk import accounts, db, flex

TOKEN = "123456789012345678901234"
STATEMENT = """<FlexQueryResponse queryName="Options Desk" type="AF"><FlexStatements count="2">
<FlexStatement accountId="U1111111" fromDate="20251031" toDate="20261029">
  <EquitySummaryInBase>
    <EquitySummaryByReportDateInBase accountId="U1111111" currency="AUD" reportDate="20261027" total="100000" />
    <EquitySummaryByReportDateInBase accountId="U1111111" currency="AUD" reportDate="20261028" total="101000" />
    <EquitySummaryByReportDateInBase accountId="U1111111" currency="AUD" reportDate="20261029" total="103500" />
    <EquitySummaryByReportDateInBase accountId="U1111111" model="Income" currency="AUD" reportDate="20261029" total="5" />
    <EquitySummaryByReportDateInBase accountId="F3333333" currency="AUD" reportDate="20261029" total="999999" />
    <EquitySummaryByReportDateInBase accountId="-" currency="AUD" reportDate="20261029" total="999999" />
  </EquitySummaryInBase>
  <Trades>
    <Trade accountId="U1111111" ibExecID="e1" ibCommission="-5.40112" ibCommissionCurrency="USD" levelOfDetail="EXECUTION" />
    <Trade accountId="U1111111" ibExecID="older" ibCommission="-1.35" levelOfDetail="EXECUTION" />
    <Trade accountId="U1111111" ibExecID="" ibCommission="-9" levelOfDetail="ORDER" />
  </Trades>
  <CashTransactions>
    <CashTransaction accountId="U1111111" type="Deposits/Withdrawals" currency="USD" fxRateToBase="1.5" amount="1000" reportDate="20261028" transactionID="d1" levelOfDetail="DETAIL" />
    <CashTransaction accountId="U1111111" type="Deposits/Withdrawals" currency="BASE_SUMMARY" fxRateToBase="1" amount="1500" reportDate="20261028" levelOfDetail="SUMMARY" />
    <CashTransaction accountId="U1111111" type="Broker Interest Received" currency="AUD" fxRateToBase="1" amount="50" reportDate="20261028" transactionID="i1" />
  </CashTransactions>
  <Transfers>
    <Transfer accountId="U1111111" type="INTERNAL" direction="OUT" currency="AUD" fxRateToBase="1" cashTransfer="-200" reportDate="20261029" transactionID="x1" />
  </Transfers>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_PATH", tmp_path / "t.db")
    monkeypatch.setattr(flex, "KEYFILE", tmp_path / "flex_key.json")
    monkeypatch.setattr(accounts, "load_config", lambda: {"risk": {"account_labels": {}, "cash_flows": []}})
    db.init()
    accounts.init()
    return tmp_path


def fill(exec_id, commission, sec_type="OPT", account="U1111111"):
    db.write("INSERT INTO executions (exec_id, account, sec_type, commission) VALUES (?,?,?,?)", (exec_id, account, sec_type, commission))


def nav_row(day, nav, daily=None, source="Options Desk", account="U1111111"):
    db.write("INSERT INTO account_daily VALUES (?,?,?,?,?,?,?)", (day, account, nav, daily, "AUD", source, day))


def parsed():
    return flex.parse(ET.fromstring(STATEMENT))


def test_a_statement_gives_sub_account_nav_commissions_and_real_flows():
    p = parsed()
    assert p["nav"] == {("2026-10-27", "U1111111"): (100000.0, "AUD"), ("2026-10-28", "U1111111"): (101000.0, "AUD"),
                        ("2026-10-29", "U1111111"): (103500.0, "AUD")}
    assert p["comm"] == {"e1": 5.40112, "older": 1.35}  # positive, as TWS and the journal hold it
    assert p["flows"] == {"d1": ("2026-10-28", "U1111111", 1500.0, "deposit"), "x1": ("2026-10-29", "U1111111", -200.0, "transfer")}
    assert (p["from"], p["to"], p["missing"]) == ("2025-10-31", "2026-10-29", [])


def test_a_query_without_a_section_says_which():
    root = ET.fromstring('<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" fromDate="20260101" toDate="20260102"><Trades /></FlexStatement></FlexStatements></FlexQueryResponse>')
    assert flex.parse(root)["missing"] == ["Net Asset Value (NAV) Summary in Base", "Trades at Execution level", "Cash Transactions", "Transfers (ACATS, Internal)"]


def test_official_nav_replaces_a_capture_and_keeps_ibkrs_daily_figure(desk):
    nav_row("2026-10-28", 100900.0, daily=321.0)
    out = flex.store(parsed())
    rows = {r["date"]: r for r in db.query("SELECT * FROM account_daily")}
    assert (rows["2026-10-28"]["nav"], rows["2026-10-28"]["daily_pnl"], rows["2026-10-28"]["source"]) == (101000.0, 321.0, "IBKR Flex")
    assert (rows["2026-10-27"]["nav"], rows["2026-10-27"]["daily_pnl"]) == (100000.0, None)
    assert (out["through"], out["nav_days"], out["new_days"], out["flows"]) == ("2026-10-29", 3, 2, 2)


def test_commissions_land_on_journal_fills_and_add_none(desk):
    fill("e1", 0.0)
    fill("not-in-statement", None)
    out = flex.store(parsed())
    got = {r["exec_id"]: r["commission"] for r in db.query("SELECT exec_id, commission FROM executions")}
    assert got == {"e1": 5.40112, "not-in-statement": None}
    assert (out["fills_matched"], out["statement_fills"]) == (1, 2)


def test_deposits_and_transfers_come_off_the_weekly_pnl(desk):
    flex.store(parsed())
    db.set_meta("flex_last", json.dumps({"from": "2025-10-31", "to": "2026-10-29"}))
    daily = accounts.weekly()["weeks"][0]["acct"]["U1111111"]["daily"]
    assert [d["pnl"] for d in daily] == [None, -500.0, 2700.0]  # +1000 less the 1500 deposit; +2500 plus the 200 sent out


def test_a_flow_on_a_day_with_no_nav_lands_on_the_next_reading(desk):
    nav_row("2026-10-27", 100000.0)
    nav_row("2026-10-29", 101600.0)
    db.write("INSERT INTO flex_flows VALUES ('d', '2026-10-28', 'U1111111', 1500.0, 'deposit')")
    daily = accounts.weekly()["weeks"][0]["acct"]["U1111111"]["daily"]
    assert daily[1]["pnl"] == 100.0


def test_config_flows_only_count_outside_what_statements_covered(desk, monkeypatch):
    flows = [{"date": "2026-10-28", "account": "U1111111", "amount": 500}, {"date": "2025-01-02", "account": "U1111111", "amount": 700}]
    monkeypatch.setattr(accounts, "load_config", lambda: {"risk": {"account_labels": {}, "cash_flows": flows}})
    assert len(accounts._cash_flows()) == 2
    db.set_meta("flex_last", json.dumps({"from": "2025-10-31", "to": "2026-10-29"}))
    assert accounts._cash_flows() == {("2025-01-02", "U1111111"): 700.0}


class Reply:
    def __init__(self, body):
        self.content = body.encode()

    def raise_for_status(self):
        pass


SENT = "<FlexStatementResponse><Status>Success</Status><ReferenceCode>555</ReferenceCode><Url>https://elsewhere.example/GetStatement</Url></FlexStatementResponse>"
WAIT = "<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode><ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"


def test_fetch_waits_for_the_statement_and_ignores_the_url_ibkr_returns(monkeypatch):
    calls, replies = [], [SENT, WAIT, STATEMENT]
    monkeypatch.setattr(flex.requests, "get", lambda url, params, headers, timeout: calls.append((url, params["q"])) or Reply(replies.pop(0)))
    monkeypatch.setattr(flex.time, "sleep", lambda s: None)
    assert flex.fetch(TOKEN, "800969").tag == "FlexQueryResponse"
    assert calls == [(f"{flex.BASE}/SendRequest", "800969"), (f"{flex.BASE}/GetStatement", "555"), (f"{flex.BASE}/GetStatement", "555")]


def test_a_bad_token_says_what_to_do(desk, monkeypatch):
    fail = "<FlexStatementResponse><Status>Fail</Status><ErrorCode>1015</ErrorCode><ErrorMessage>Token is invalid.</ErrorMessage></FlexStatementResponse>"
    monkeypatch.setattr(flex.requests, "get", lambda *a, **k: Reply(fail))
    assert flex.set_key(TOKEN, "800969") == {"ok": True}
    assert flex.run() == {"error": flex.FIXES["1015"]}
    assert flex.info()["error"] == flex.FIXES["1015"]


def test_the_token_never_leaves_in_an_error_or_a_status(desk, monkeypatch, caplog):
    def boom(url, params, **k):
        raise requests.ConnectionError(f"failed: {url}?t={params['t']}&q={params['q']}")

    monkeypatch.setattr(flex.requests, "get", boom)
    flex.set_key(TOKEN, "800969")
    out = flex.run()
    assert out == {"error": "Could not reach IBKR (ConnectionError)"}
    for text in (json.dumps(out), json.dumps(flex.info()), db.get_meta("flex_try"), caplog.text):
        assert TOKEN not in text


def test_nothing_is_saved_from_something_that_is_not_a_token(desk):
    assert flex.set_key("my password!", "800969")["error"]
    assert flex.set_key(TOKEN, "abc")["error"]
    assert not flex.KEYFILE.exists()


def test_an_update_only_asks_when_a_statement_can_be_new(desk):
    now = dt.datetime(2026, 10, 31, 1, 0, tzinfo=dt.timezone.utc)
    assert "Recorder" in flex.skip_reason(now, "2026-10-30")
    flex.set_key(TOKEN, "800969")
    assert flex.skip_reason(now, "2026-10-30") is None
    db.set_meta("flex_last", json.dumps({"through": "2026-10-30"}))
    assert "current" in flex.skip_reason(now, "2026-10-30")
    db.set_meta("flex_last", json.dumps({"through": "2026-10-29"}))
    db.set_meta("flex_try", json.dumps({"ts": (now - dt.timedelta(minutes=40)).isoformat()}))
    assert flex.skip_reason(now, "2026-10-30") == "asked IBKR 40 min ago"
    db.set_meta("flex_try", json.dumps({"ts": (now - dt.timedelta(hours=4)).isoformat()}))
    assert flex.skip_reason(now, "2026-10-30") is None


def test_commission_coverage_counts_sub_account_option_fills_only(desk):
    fill("a", 5.4)
    fill("b", 0.0)
    fill("c", None)
    fill("bag", 0.0, sec_type="BAG")
    fill("master", 0.0, account="F3333333")
    f = flex.info()
    assert (f["fills"], f["fills_priced"]) == (3, 1)


def test_the_one_file_writes_charges_negative_like_a_real_flex_file(desk, monkeypatch):
    db.write("""INSERT INTO executions (exec_id, account, time_utc, local_symbol, sec_type, symbol, side, qty, price, mult, commission)
                VALUES ('e', 'U1111111', '2026-10-30T19:39:31+00:00', 'SPX   261120P07550000', 'OPT', 'SPX', 'BOT', 4, 114.95, 100, 5.4)""")
    row = accounts.one_import_rows("U1111111", "2026-10-31")[0]
    assert row[6] == "-5.4"
    assert float(row[8]) == pytest.approx(-(4 * 114.95 * 100) - 5.4)
