import numpy as np
import pytest

from mm_tick import revert as V


def fp(path_hi, path_lo, pos, delta=10, hmax=5, px=None):
    n = len(path_hi)
    px = np.full(n, 100.0) if px is None else np.asarray(px, float)
    hi = np.asarray(path_hi, np.float32)
    lo = np.asarray(path_lo, np.float32)
    return V.first_passage(np.array([0]), np.array([pos]), px, hi, lo, float(delta), hmax)[0]


def test_short_reverts_down():
    assert fp([100, 100.05, 100.0, 100, 100, 100, 100], [100, 99.95, 99.89, 100, 100, 100, 100], -1) == 10


def test_short_adverse_up():
    assert fp([100, 100.11, 100, 100, 100, 100, 100], [100, 100, 100, 100, 100, 100, 100], -1) == -10


def test_tie_in_one_second_is_adverse():
    assert fp([100, 100.2, 100, 100, 100, 100, 100], [100, 99.8, 100, 100, 100, 100, 100], 1) == -10


def test_no_trade_seconds_skipped_and_timeout_marks_to_market():
    nan = np.nan
    px = [100, 100, 100, 100, 100, 100.05, 100.05]
    v = fp([100, nan, nan, 100.02, 100, 100.05, 100], [100, nan, nan, 99.99, 100, 100.0, 100], 1, px=px)
    assert v == pytest.approx(np.log(100.05 / 100) * 1e4, rel=1e-6)


def test_samples_require_push_away_from_anchor():
    import pandas as pd
    from mm_tick import events as E
    n_days = 30
    n = n_days * E.DAY_S
    az = {"n_days": n_days, "Rs": 300, "y": np.full(n, 1e-3, np.float32), "z": np.ones(n, np.float32)}
    side = np.zeros(n, np.int8)
    i0 = 2 * E.LOOKBACK_D * E.DAY_S + 20
    side[i0] = 1          # taker buy while above the anchor: counts
    side[i0 + 10] = -1    # taker sell while above: does not
    cdf = np.tile(np.linspace(0, 1, len(E.EDGES) - 1), (n_days, 1))
    s = V.samples(az, side, np.ones(n, np.float32), cdf)
    assert s["i"].tolist() == [i0] and s["pos"].tolist() == [-1]
