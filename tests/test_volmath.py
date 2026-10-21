import math
from desk.volmath import bs_price, implied_vol, forward_vol, interp_total_variance, interp_by_delta, zscore


def test_iv_roundtrip():
    for right in "PC":
        p = bs_price(100, 95, 30 / 365, 0.22, right)
        assert abs(implied_vol(p, 100, 95, 30 / 365, right) - 0.22) < 1e-6


def test_forward_vol_flat_curve():
    assert abs(forward_vol(0.2, 0.1, 0.2, 0.3) - 0.2) < 1e-12


def test_forward_vol_upward_curve_is_above_back():
    fv = forward_vol(0.10, 15 / 365, 0.12, 22 / 365)
    assert fv > 0.12


def test_interp_total_variance_hits_points():
    pts = [(0.1, 0.2), (0.3, 0.25)]
    assert abs(interp_total_variance(pts, 0.1) - 0.2) < 1e-12
    assert abs(interp_total_variance(pts, 0.3) - 0.25) < 1e-12
    mid = interp_total_variance(pts, 0.2)
    assert 0.2 < mid < 0.25


def test_interp_by_delta():
    assert abs(interp_by_delta([(-0.5, 0.10), (-0.1, 0.20)], -0.3) - 0.15) < 1e-12


def test_zscore():
    assert zscore([1, 2, 3] * 10, 2) == 0
