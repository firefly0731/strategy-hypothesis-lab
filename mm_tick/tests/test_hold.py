import numpy as np
import pandas as pd

from mm_tick.hold import CHECKS, cut_price, policy, rows_for_trips


def test_cut_price_uses_the_touch_before_the_cut():
    t = np.array([0, 100, 200, 300], np.int64)
    price = np.array([10.0, 10.1, 9.9, 10.2])
    side = np.array([-1, 1, -1, 1], np.int8)
    # at 250: last sell 9.9, last buy 10.1 -> long sells at 9.9, short buys at 10.1
    x = cut_price(t, price, side, np.array([1.0, -1.0]), np.array([250, 250]), 0.1)
    assert np.allclose(x, [9.9, 10.1])
    # at 350 the buy at 10.2 is later; a long still sells at min(9.9, 10.2 - 0.1)
    x = cut_price(t, price, side, np.array([1.0]), np.array([350]), 0.1)
    assert np.allclose(x, [9.9])


def _tape():
    rng = np.random.default_rng(0)
    n = 40_000
    t = np.cumsum(rng.integers(20, 100, n)).astype(np.int64)
    price = 100 + 0.01 * np.cumsum(rng.choice([-1, 1], n))
    side = rng.choice([-1, 1], n).astype(np.int8)
    return t, price, side, price * 1.0


def test_rows_only_while_open_and_target_is_final_minus_cut():
    t, price, side, notional = _tape()
    trips = pd.DataFrame({"t": [10_000, 20_000], "ex_t": [10_000 + 7_000, 20_000 + 1_000_000],
                          "d": [1, -1], "entry": [price[200], price[400]], "tp": [price[200] + 0.05, price[400] - 0.05],
                          "tick_px": 0.01, "pnl_bp": [3.0, -50.0], "improved": [False, True], "trip": [0, 1]})
    n_s = int(t.max() // 1000) + 2
    r = rows_for_trips(t, price, side, notional, trips, 0, np.full(n_s, 0.5, np.float32),
                       np.zeros(n_s), np.ones(n_s, np.float32), np.full(5, 10.0), 0.01)
    assert sorted(r.loc[r.trip == 0, "c"]) == [5]                      # open at 5 s only
    assert len(r[r.trip == 1]) == sum(1 for c in CHECKS if c * 1000 < 1_000_000)
    assert np.allclose(r["A"], np.where(r.trip == 0, 3.0, -50.0) - r["cut_bp"], atol=1e-4)
    # a short's unrealised PnL is positive when the price fell
    row = r[(r.trip == 1)].iloc[0]
    assert np.sign(row["unreal_bp"]) == np.sign(price[400] - price[np.searchsorted(t, row["t"]) - 1]) or row["unreal_bp"] == 0


def test_policy_cuts_at_the_first_negative_prediction():
    trips = pd.DataFrame({"sym": "X", "trip": [0, 1], "pnl_bp": [-90.0, 3.0]})
    rows = pd.DataFrame({"sym": "X", "trip": [0, 0, 1], "c": [5, 10, 5], "cut_bp": [-20.0, -30.0, -6.0]})
    tr = policy(rows, trips, np.array([1.0, -1.0, 2.0]))
    assert tr.loc[0, "pol_bp"] == -30.0 and tr.loc[1, "pol_bp"] == 3.0
    assert tr.loc[0, "oracle_bp"] == -20.0 and tr.loc[1, "oracle_bp"] == 3.0
