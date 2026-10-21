"""Black-Scholes, implied vol, forward vol and maturity interpolation.

Vols are decimals (0.15 = 15%). Time is in years of 365 calendar days.
"""
import math

R = 0.0  # rates barely move calendar/skew comparisons; kept at zero on purpose


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot, strike, t, vol, right):
    if t <= 0 or vol <= 0:
        return max(0.0, (spot - strike) if right == "C" else (strike - spot))
    sd = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if right == "C":
        return spot * _ncdf(d1) - strike * _ncdf(d2)
    return strike * _ncdf(-d2) - spot * _ncdf(-d1)


def bs_delta(spot, strike, t, vol, right):
    if t <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    return _ncdf(d1) if right == "C" else _ncdf(d1) - 1.0


def implied_vol(price, spot, strike, t, right, lo=0.005, hi=3.0):
    """Bisection; returns None when the price is outside no-arbitrage bounds."""
    if price is None or price <= 0 or t <= 0:
        return None
    intrinsic = max(0.0, (spot - strike) if right == "C" else (strike - spot))
    if price < intrinsic or price > (spot if right == "C" else strike):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if bs_price(spot, strike, t, mid, right) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def forward_vol(iv1, t1, iv2, t2):
    """Vol implied between two maturities: sqrt((iv2^2 t2 - iv1^2 t1) / (t2 - t1))."""
    if None in (iv1, iv2) or t2 <= t1:
        return None
    var = (iv2 * iv2 * t2 - iv1 * iv1 * t1) / (t2 - t1)
    return math.sqrt(var) if var > 0 else None


def interp_total_variance(points, t):
    """points: sorted [(t, iv)]; linear in total variance, flat-vol extrapolation."""
    pts = [(a, b) for a, b in points if a and a > 0 and b is not None]
    if not pts:
        return None
    pts.sort()
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t1, v1), (t2, v2) in zip(pts, pts[1:]):
        if t1 <= t <= t2:
            w1, w2 = v1 * v1 * t1, v2 * v2 * t2
            w = w1 + (w2 - w1) * (t - t1) / (t2 - t1)
            return math.sqrt(max(w, 1e-12) / t)
    return None


def interp_by_delta(quotes, target):
    """quotes: [(delta, iv)] for one right; linear interpolation of iv at target delta."""
    q = sorted((d, v) for d, v in quotes if d is not None and v is not None)
    if len(q) < 2:
        return None
    if not (q[0][0] <= target <= q[-1][0]):
        return None
    for (d1, v1), (d2, v2) in zip(q, q[1:]):
        if d1 <= target <= d2:
            return v1 if d2 == d1 else v1 + (v2 - v1) * (target - d1) / (d2 - d1)
    return None


def zscore(series, value, min_n=20):
    xs = [x for x in series if x is not None]
    if len(xs) < min_n or value is None:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))
    return None if sd == 0 else (value - m) / sd


def percentile(series, value):
    xs = [x for x in series if x is not None]
    if not xs or value is None:
        return None
    return 100.0 * sum(1 for x in xs if x <= value) / len(xs)
