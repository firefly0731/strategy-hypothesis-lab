import numpy as np
import pandas as pd

from crypto_intraday_momentum.backtest import Config, run_backtest
from crypto_intraday_momentum.cpcv import cpcv_splits, run_cpcv
from crypto_intraday_momentum.sessions import US, build_sessions
from crypto_intraday_momentum.signals import compute_signals
from crypto_intraday_momentum.tests.test_lookahead import synth


def test_splits_disjoint_and_embargoed():
    n, N, k, emb = 500, 10, 2, 30
    splits = list(cpcv_splits(n, N, k, emb))
    assert len(splits) == 45
    for test_ids, tr, te, groups in splits:
        assert not set(tr) & set(te)
        for g in test_ids:
            b = groups[g][-1]
            after = set(range(b + 1, min(b + 1 + emb, n)))
            assert not after & set(tr)          # embargo after every test group


def test_paths_cover_every_session_once():
    rng = np.random.default_rng(0)
    R = pd.DataFrame(rng.normal(0, 0.01, (400, 6)), columns=list("abcdef"))
    res = run_cpcv(R, n_groups=8, k_test=2, embargo=10)
    assert res.paths.shape == (400, 7)                    # C(7,1) paths
    # every path value comes from one of the combos at that session
    X = R.to_numpy()
    for p in range(res.paths.shape[1]):
        v = res.paths.iloc[:, p].to_numpy()
        assert all(np.isclose(X[i], v[i]).any() for i in range(len(v)))
    assert 0.0 <= res.pbo <= 1.0


def test_pbo_high_for_pure_noise():
    rng = np.random.default_rng(1)
    R = pd.DataFrame(rng.normal(0, 0.01, (1000, 50)))
    assert run_cpcv(R, 10, 2, 0).pbo > 0.3                 # noise selection doesn't persist


def test_cost_filter_only_removes_entries():
    df = synth()
    m = build_sessions(df, US)
    s = compute_signals(m)
    r0 = run_backtest(m, s, Config())
    r1 = run_backtest(m, s, Config(cost_filter_mult=4.0))
    assert len(r1.trades) < len(r0.trades)
    rtc = Config().round_trip_cost()
    assert np.isclose(rtc, 2 * (0.0005 + 1e-4))
    huge = run_backtest(m, s, Config(cost_filter_mult=1e6))
    assert len(huge.trades) == 0


def test_entry_cutoff_and_vwap_confirm():
    df = synth()
    m = build_sessions(df, US)
    s = compute_signals(m)
    r = run_backtest(m, s, Config(entry_cutoff_min=270))
    assert len(r.trades) and (r.trades["dec_min"] < 270).all()
    base = run_backtest(m, s, Config())
    rv = run_backtest(m, s, Config(vwap_confirm_k=0.6))
    assert len(rv.trades) < len(base.trades)
    i, j, side = rv.trades["sess_idx"], rv.trades["dec_j"], rv.trades["side"]
    dist = side * (s.px[i, j] / s.vwap[i, j] - 1) / s.sigma[i, j]
    assert (dist >= 0.6 - 1e-12).all()
