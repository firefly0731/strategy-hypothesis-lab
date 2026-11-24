import numpy as np
import pytest

from mm_tick import anchored as A
from mm_tick import events as E


@pytest.fixture(scope="module")
def base():
    rng = np.random.default_rng(0)
    n = 32 * E.DAY_S
    px = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 2e-5))
    az = A.anchored_z(px, 5)
    return px, az, E.thresholds(az["z"], az["n_days"])


def test_anchor_is_window_start_price(base):
    px, az, _ = base
    i = 20 * E.DAY_S + 7 * 300 + 123                 # inside a 5-minute window
    a = px[i - 123 - 1]
    assert az["y"][i] == pytest.approx(np.log(px[i] / a), abs=1e-6)


def test_anchored_uses_only_the_past(base):
    px, az, k = base
    rng = np.random.default_rng(1)
    for cut_day, cut_sec in ((29, 4000), (30, 50000)):
        i0 = cut_day * E.DAY_S + cut_sec
        px2 = px.copy()
        px2[i0 + 1:] *= np.exp(np.cumsum(rng.normal(0, 1e-3, len(px) - i0 - 1)))
        az2 = A.anchored_z(px2, 5)
        k2 = E.thresholds(az2["z"], az2["n_days"])
        ok = np.isfinite(az["z"][: i0 + 1])
        assert ok.any()
        np.testing.assert_array_equal(az["z"][: i0 + 1][ok], az2["z"][: i0 + 1][ok])
        np.testing.assert_array_equal(k[: cut_day + 1], k2[: cut_day + 1])


def test_first_break_per_window_and_min_tau():
    Rs = 20
    z = np.zeros(60)
    k = np.full(60, 1.0)
    z[3] = 5          # tau < 10: ignored
    z[12] = 5         # first break of window 0
    z[15] = 5         # second break in the same window: ignored
    z[45] = -5        # window 2, tau 5: ignored
    z[52] = -5        # window 2, tau 12
    assert A._first_breaks(z, k, Rs, 10).tolist() == [12, 52]


def test_matched_controls_keep_hour_and_tau():
    import pandas as pd
    ev = pd.DataFrame({"i": [30 * E.DAY_S + 5 * 3600 + 2 * 300 + 77]})
    c = A.matched_controls(40, ev, 300, np.random.default_rng(0))
    i = c["i"].iloc[0]
    assert (i % E.DAY_S) // 3600 == 5 and i % 300 == 77
