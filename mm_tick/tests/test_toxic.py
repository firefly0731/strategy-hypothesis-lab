import numpy as np

from mm_tick.toxic import window_features


def tape():
    rng = np.random.default_rng(0)
    n = 5000
    t = np.cumsum(rng.integers(10, 2000, n)).astype(np.int64)
    lp = np.log(100) + np.cumsum(rng.standard_normal(n)) * 1e-4
    side = rng.choice([-1, 1], n).astype(np.int8)
    notional = rng.lognormal(3, 1, n)
    return t, lp, side, notional


def test_features_ignore_trades_at_or_after_the_decision_time():
    t, lp, side, notional = tape()
    tau = np.array([t[3000], t[4000] + 1])          # one tau exactly on a trade, one just after
    d = np.array([1.0, -1.0])
    f0 = window_features(t, lp, side, notional, tau, d)
    lp2, side2, n2 = lp.copy(), side.copy(), notional.copy()
    for i in (3000, 3001, 3002, 4001, 4002):        # change the trade at tau and the ones after it
        lp2[i] += 0.05
        side2[i] *= -1
        n2[i] *= 10
    f1 = window_features(t, lp2, side2, n2, tau, d)
    for k in f0:
        assert np.allclose(f0[k], f1[k], equal_nan=True), k


def test_return_is_signed_by_side():
    t = np.array([0, 1000, 2000, 3000], np.int64)
    lp = np.log(np.array([100.0, 100.0, 100.0, 101.0]))
    side = np.array([1, 1, 1, 1], np.int8)
    f = window_features(t, lp, side, np.ones(4), np.array([3500, 3500]), np.array([1.0, -1.0]))
    assert f["ret_1s"][0] > 0 and np.isclose(f["ret_1s"][0], -f["ret_1s"][1])
