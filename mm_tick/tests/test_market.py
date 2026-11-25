import numpy as np

from mm_tick.market import Market


def test_market_features_use_only_seconds_before_and_are_signed():
    m = Market.__new__(Market)
    m.M = np.arange(4000, dtype=float) * 1e-4          # +1 bp per second
    m.br5 = np.full(4000, 0.5, np.float32)
    m.br30 = np.full(4000, -0.2, np.float32)
    m.tb = np.arange(4000, dtype=np.int64) * 2           # 2 trades per second, steady
    m.start_ms = 0
    f = m.features(np.array([3700, 3700]), np.array([1.0, -1.0]), np.array([10.0, -10.0]))
    assert np.allclose(f["mkt_ret_30s"], [30.0, -30.0]) and np.allclose(f["mkt_ret_1s"], [1.0, -1.0])
    assert np.allclose(f["mkt_br_5s"], [0.5, -0.5])
    assert np.allclose(f["mkt_act_5s"], [1.0, 1.0])     # activity is not signed
    assert np.allclose(f["rel_ret_30s"], [-20.0, 20.0])
    g = m.features(np.array([10]), np.array([1.0]), np.array([0.0]))
    assert np.isnan(g["mkt_ret_30s"][0])                 # window starts before the series
