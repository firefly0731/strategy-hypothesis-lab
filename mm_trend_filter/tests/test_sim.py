import numpy as np
import pytest

from mm_trend_filter.policies import permissions, to_bars, window_state
from mm_trend_filter.sim import ANCHOR, MID, simulate

T = 0.0005


def run(C, H=None, L=None, mode=ANCHOR, delta=0.01, cap=5, allow_bid=None, allow_ask=None, flat=None):
    C = np.atleast_2d(np.asarray(C, float))
    O = np.concatenate([C[:, :1], C[:, :-1]], axis=1)
    H = C if H is None else np.atleast_2d(np.asarray(H, float))
    L = C if L is None else np.atleast_2d(np.asarray(L, float))
    one = np.ones(C.shape, dtype=np.bool_)
    ab = one if allow_bid is None else np.atleast_2d(allow_bid)
    aa = one if allow_ask is None else np.atleast_2d(allow_ask)
    fl = np.zeros(C.shape, dtype=np.bool_) if flat is None else np.atleast_2d(flat)
    return simulate(O, H, L, C, ab, aa, fl, delta, mode, cap, T)


def test_flat_path_no_fills():
    eq, nf = run(np.ones(50))
    assert nf.sum() == 0 and np.all(eq == 0)


def test_touch_is_not_a_fill():
    # bid at 0.99: a low of exactly 0.99 does not trade through
    eq, nf = run([1, 1, 1], L=[1, 0.99, 1])
    assert nf.sum() == 0


def test_round_trip_earns_delta():
    # bar1 low 0.985 fills the bid at 0.99, close 0.99; bar2 high 1.0005 fills the ask at 0.99*1.01
    C = [1.0, 0.99, 1.0]
    eq, nf = run(C, H=[1.0, 0.99, 1.0005], L=[1.0, 0.985, 0.99])
    assert nf.sum() == 2
    assert eq[0, -1] == pytest.approx(0.99 * 1.01 - 0.99)


def test_anchor_ladder_vs_mid():
    # price falls 3% in one bar: anchor buys at 0.99 then next bid is 0.99^n below the close
    C = [1.0, 0.97, 0.97]
    L = [1.0, 0.969, 0.95]
    eq_a, nf_a = run(C, L=L, mode=ANCHOR)
    eq_m, nf_m = run(C, L=L, mode=MID)
    assert nf_a[0, 1] == 1 and nf_a[0, 2] == 1 and nf_m[0, 2] == 1
    # anchor's next bid is the first 0.99^n below the close 0.97: 0.99^3 = 0.9703 is not, 0.99^4 is
    ok_a = -0.99 - 0.99 ** 4
    ok_m = -0.99 - 0.97 * 0.99
    end = 0.97
    assert eq_a[0, -1] == pytest.approx(ok_a + 2 * end * (1 - T))
    assert eq_m[0, -1] == pytest.approx(ok_m + 2 * end * (1 - T))


def test_cap_and_session_end_flatten():
    n = 20
    C = np.linspace(1, 0.8, n)
    eq, nf = run(C, L=C * 0.98, cap=3, delta=0.005)
    assert nf.sum() == 3                         # never more than the cap
    assert eq[0, -1] < 0


def test_no_quotes_no_fills_and_flatten_cost():
    C = [1.0, 0.99, 0.95, 0.95]
    L = [1.0, 0.985, 0.95, 0.95]
    ab = np.array([True, True, False, False])
    flat = np.array([False, False, True, False])
    eq, nf = run(C, L=L, allow_bid=ab, allow_ask=ab, flat=flat)
    assert nf.sum() == 1
    # bought at 0.99, flattened at the open of bar 2 (= close of bar 1 = 0.99) with taker cost
    assert eq[0, -1] == pytest.approx(-0.99 * T)


def test_window_state_and_permissions():
    class S:
        px = np.array([[1.0, 1.2, 0.8]])
        ub = np.array([[1.1, 1.1, np.nan]])
        lb = np.array([[0.9, 0.9, 0.9]])
    st = window_state(S)
    assert st.tolist() == [[0, 1, -1]]
    dm = np.array([2, 4, 6])
    bars = to_bars(st, dm, 8)
    assert bars.tolist() == [[0, 0, 0, 0, 1, 1, -1, -1]]
    ab, aa, _ = permissions("band_skew", st, dm, 8)
    assert ab.tolist() == [[True] * 6 + [False] * 2]
    assert aa.tolist() == [[True] * 4 + [False] * 2 + [True] * 2]
    ab, _, _ = permissions("sticky_off", st, dm, 8)
    assert ab.tolist() == [[True] * 4 + [False] * 4]
    _, _, fl = permissions("band_flat", st, dm, 8)
    assert np.flatnonzero(fl[0]).tolist() == [4, 6]


def test_vol_state_uses_only_prior_bars():
    from mm_trend_filter.policies import path_length_state
    rng = np.random.default_rng(0)
    n_s, n_k = 30, 120
    C = np.exp(np.cumsum(rng.normal(0, 1e-3, (n_s, n_k)), axis=1))
    O0 = np.ones(n_s)
    dm = np.array([30, 60, 90])
    base = path_length_state(C, O0, dm, lookback=5, mult=1.0)
    for i in (10, 20):
        for j, m in enumerate(dm):
            C2 = C.copy()
            C2[i, m:] *= np.exp(rng.normal(0, 5e-2, n_k - m))   # perturb bars >= m of session i
            C2[i + 1:] *= np.exp(rng.normal(0, 5e-2, (n_s - i - 1, n_k)))  # and all later sessions
            pert = path_length_state(C2, O0, dm, lookback=5, mult=1.0)
            assert (pert[:i] == base[:i]).all()
            assert (pert[i, :j + 1] == base[i, :j + 1]).all()
