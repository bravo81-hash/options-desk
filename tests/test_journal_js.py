"""Journal statistics, run in a real browser against web/jstats.js and checked against the same sums done here in Python."""
import json
import math
import statistics
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
JS = (Path(__file__).resolve().parents[1] / "web" / "jstats.js").read_text(encoding="utf-8")
R = [0.2, 0.15, -0.4, 0.1, 0.05, -0.9, 0.3, 0.12, -0.1, 0.25]


@pytest.fixture(scope="module")
def page():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            pytest.skip("no Chrome to run the page's statistics in")
        pg = b.new_page()
        pg.add_script_tag(content=JS)
        yield pg
        b.close()


def js(page, expr, *args):
    return page.evaluate(f"(a) => {{ const S = window.JStats; return {expr}; }}", json.loads(json.dumps(args)))


def rows(rs, **kw):
    return [{"decision": f"d{i}", "keys": [f"k{i}"], "strategy": "A14", "ticker": "SPX", "acct": "MGN", "entry": f"2026-06-{i + 1:02d}T06:00:00", "close": f"2026-07-{i + 1:02d}T06:00:00",
             "exit_us": f"2026-07-{i + 1:02d}", "entry_us": f"2026-06-{i + 1:02d}", "open": False, "r": r, "pnl": r * 1000, "risk0": 1000, "peak": 1000, "risk_days": 10000, "creep": 1, "adj": 0, "dit": 10, "checks": [], "followed": None, "followed_ever": None, **kw}
            for i, r in enumerate(rs)]


def wilson(w, n, z=1.2816):
    p, c = w / n, z * z
    m = z * math.sqrt(p * (1 - p) / n + c / (4 * n * n))
    return (p + c / (2 * n) - m) / (1 + c / n), (p + c / (2 * n) + m) / (1 + c / n)


def test_wilson_matches_the_formula(page):
    assert js(page, "S.wilson(7, 10)") == pytest.approx(wilson(7, 10))


def test_wilson_stays_inside_zero_and_one_at_the_ends(page):
    lo, hi = js(page, "S.wilson(0, 10)")
    assert lo == pytest.approx(0) and lo >= 0 and 0 < hi < 0.25
    lo, hi = js(page, "S.wilson(10, 10)")
    assert hi == pytest.approx(1) and hi <= 1 and 0.75 < lo < 1
    assert js(page, "S.wilson(0, 0)") == [None, None]


def test_std_dev_cv_and_skew_match_python(page):
    m, s = statistics.mean(R), statistics.stdev(R)
    assert js(page, "S.sd(a[0])", R) == pytest.approx(s)
    assert js(page, "S.cv(a[0])", R) == pytest.approx(s / m)
    assert js(page, "S.skew(a[0])", R) == pytest.approx(statistics.mean(((v - m) / s) ** 3 for v in R))
    assert js(page, "S.sqn(a[0])", R) == pytest.approx(m / s * math.sqrt(len(R)))


def test_skew_reads_negative_for_short_premium(page):
    assert js(page, "S.skew(a[0])", [0.1] * 9 + [-0.9]) < -1


def test_no_spread_gives_no_ratio_rather_than_infinity(page):
    assert js(page, "S.skew(a[0])", [0.2, 0.2, 0.2]) is None
    assert js(page, "S.sqn(a[0])", [0.2, 0.2, 0.2]) is None
    assert js(page, "S.cv(a[0])", [0.2, -0.2]) is None


def test_the_bootstrap_is_repeatable_and_brackets_the_mean(page):
    a, b = js(page, "S.bootMean(a[0])", R), js(page, "S.bootMean(a[0])", R)
    assert a == b and a[0] < statistics.mean(R) < a[1]


def test_decisions_fold_twins_once(page):
    a, b = rows([0.2]), rows([0.4])
    b[0].update(acct="SMSF", keys=["k9"])
    D = js(page, "S.fold(a[0])", a + b)
    assert len(D) == 1 and D[0]["r"] == pytest.approx(0.3) and D[0]["pnl"] == pytest.approx(600) and D[0]["accts"] == ["MGN", "SMSF"]


def test_a_half_closed_twin_is_not_counted(page):
    a, b = rows([0.2]), rows([0.4], open=True)
    assert js(page, "S.closed(S.fold(a[0])).length", a + b) == 0


def test_kpi_against_a_hand_count(page):
    k = js(page, "S.kpi(S.fold(a[0]))", rows(R))
    W, L = [v for v in R if v > 0], [-v for v in R if v < 0]
    assert (k["n"], k["wins"], k["losses"]) == (10, 7, 3)
    assert k["win"] == 0.7 and k["ci"] == pytest.approx(wilson(7, 10))
    assert k["avgWin"] == pytest.approx(sum(W) / 7) and k["avgLoss"] == pytest.approx(sum(L) / 3)
    assert k["payoff"] == pytest.approx((sum(W) / 7) / (sum(L) / 3))
    assert k["expR"] == pytest.approx(sum(R) / 10) and k["totalR"] == pytest.approx(sum(R))
    assert k["pf"] == pytest.approx(sum(W) / sum(L))
    assert k["median"] == pytest.approx(statistics.median(R))
    assert k["worstOverAvg"] == pytest.approx(0.9 / (sum(L) / 3))
    assert k["bestOverWorst"] == pytest.approx(0.3 / 0.9)
    assert k["tail"] == 0.1
    assert k["rod"] == pytest.approx(100 * sum(R) * 1000 / 100000)


def test_a_book_with_no_losses_has_no_profit_factor(page):
    k = js(page, "S.kpi(S.fold(a[0]))", rows([0.1, 0.2]))
    assert k["pf"] is None and k["payoff"] is None and k["worstOverAvg"] is None


def test_an_empty_view_is_handled(page):
    k = js(page, "S.kpi([])")
    assert k["n"] == 0 and k["win"] is None and k["bestR"] is None and js(page, "S.curve([], 100000).pts.length") == 0


def test_drawdown_in_r_and_percent(page):
    c = js(page, "S.curve(S.fold(a[0]), 10000)", rows([1, 1, -1.5, 0.5]))
    assert c["mddR"] == pytest.approx(-1.5)
    assert c["mddP"] == pytest.approx(100 * (10500 / 12000 - 1))
    assert c["ddNow"] == pytest.approx(-1)
    assert c["recover"] == pytest.approx(100 * (12000 / 10500 - 1))


def test_recovery_math(page):
    assert js(page, "[0.1, 0.2, 0.3, 0.5].map(S.recovery)") == pytest.approx([1 / 9, 0.25, 3 / 7, 1])


def test_histogram_counts_everything_and_edges_go_up(page):
    B = js(page, "S.hist(a[0])", R + [0.1, -0.1, 0])
    assert sum(b["n"] for b in B) == 13
    at = lambda x: next(b for b in B if b["x0"] - 1e-9 <= x < b["x1"] - 1e-9)["n"]  # noqa: E731
    assert at(0.1) == 4 and at(-0.1) == 2 and at(0) == 2
    assert js(page, "S.hist([0.1]).length") == 1


def test_a_losing_strategy_never_passes_on_cv(page):
    cfg = {"loss_bar": 30, "cv_max": 10, "skew_min": 0.5}
    D = rows([-0.2, 0.1, -0.3, 0.05])
    c = js(page, "S.confidence(S.fold(a[0]), null, a[1])", D, cfg)
    assert c["mean"] < 0 and c["cv"] < 10 and c["cvOk"] is False


def test_losses_before_one_count_towards_the_bar(page):
    cfg = {"loss_bar": 30, "cv_max": 10, "skew_min": 0.5}
    c = js(page, "S.confidence(S.fold(a[0]), {n: 40, losses: 28}, a[1])", rows([0.2, -0.1, -0.1, 0.2]), cfg)
    assert c["lossesAll"] == 30 and c["barOk"] is True and c["more"] == 0
    c = js(page, "S.confidence(S.fold(a[0]), null, a[1])", rows([0.2, -0.1, -0.1, 0.2]), cfg)
    assert c["barOk"] is False and c["more"] == 56  # 28 more losses at a 50% loss rate


def test_buckets_at_their_edges(page):
    assert js(page, "[14.99, 15, 20, 30].map((v) => S.bucket(v, S.VIX))") == ["under 15", "15–20", "20–30", "30+"]
    assert js(page, "[21, 22, 45, 46, 71].map((v) => S.bucket(v, S.DTE))") == ["up to 21", "22–45", "22–45", "46–70", "71+"]
    assert js(page, "[0, 1, 2, 3, 6].map((v) => S.bucket(v, S.ADJ))") == ["none", "1–2", "1–2", "3–5", "6+"]
    assert js(page, "S.bucket(null, S.VIX)") is None


def test_accuracy_counts_only_rules_that_existed_unless_asked(page):
    a = rows([0.3], followed=True, followed_ever=True, checks=[["stop", True, True]])
    b = rows([-0.4], followed=None, followed_ever=False, checks=[["stop", False, False]])
    b[0].update(decision="dB")
    live = js(page, "S.accuracy(S.fold(a[0]), false)", a + b)
    assert (live["scored"], live["unscored"], live["accuracy"]) == (1, 1, 1)
    assert live["rules"][0]["kept"]["n"] == 1 and live["rules"][0]["broke"]["n"] == 0
    ever = js(page, "S.accuracy(S.fold(a[0]), true)", a + b)
    assert (ever["scored"], ever["accuracy"]) == (2, 0.5)
    assert ever["broke"]["mean"] == pytest.approx(-0.4) and ever["rules"][0]["broke"]["n"] == 1


def test_accuracy_is_not_the_win_rate(page):
    a = rows([0.3, -0.2], followed=True, followed_ever=True, checks=[["stop", True, True]])
    x = js(page, "S.accuracy(S.fold(a[0]), false)", a)
    assert x["accuracy"] == 1 and x["kept"]["win"] == 0.5
