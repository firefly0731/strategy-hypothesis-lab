import numpy as np
import pandas as pd
import pytest

from crypto_dirty_carry.config import StrategyConfig
from crypto_dirty_carry.portfolio import (compute_targets, neutralize, select_baskets, water_fill)

from .conftest import BTC, HIGH, LOW

CFG = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,))


def targets(data, cfg=CFG, t=None):
    t = data.close.index[-1] if t is None else t
    return compute_targets(data.snapshot(t, cfg.lookback, cfg.funding_history), cfg)


def test_dollar_neutral_and_caps(data):
    tg = targets(data)
    assert tg.status == "ok"
    assert set(tg.short) == set(HIGH) and set(tg.long) == set(LOW)
    for w in (tg.w_raw, tg.w):
        assert abs(w.sum()) < 1e-12
        assert w.abs().sum() <= CFG.gross_cap + 1e-12
        assert w.abs().max() <= CFG.max_weight + 1e-12
    assert np.isclose(tg.w_raw[list(tg.short)].sum(), -0.5) and np.isclose(tg.w_raw[list(tg.long)].sum(), 0.5)


def test_inverse_vol_within_basket(data):
    tg = targets(data)
    s = list(tg.short)
    prod = (tg.w_raw[s].abs() * tg.vol[s]).to_numpy()      # |w| ∝ 1/vol  ⇔  |w|·vol constant
    assert np.allclose(prod, prod[0])


def test_factor_neutralisation_removes_exposure(data):
    tg = targets(data)
    assert tg.exposure_raw["BTC"] < -0.1                      # shorts are higher beta than longs
    assert abs(tg.exposure["BTC"]) < 1e-8 and abs(tg.w.sum()) < 1e-12
    assert (tg.w[list(tg.short)] <= 0).all() and (tg.w[list(tg.long)] >= 0).all()
    # the projection moved short weight to the low-beta short (B) and long weight to the high-beta long (D)
    assert abs(tg.w["B"]) > abs(tg.w_raw["B"]) and tg.w["D"] > tg.w_raw["D"]


def test_hedge_mode_keeps_baskets_and_reports_net(data):
    cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), neutral_mode="hedge")
    tg = targets(data, cfg)
    basket = list(tg.short) + list(tg.long)
    pd.testing.assert_series_equal(tg.w[basket], tg.w_raw[basket])
    assert abs(tg.exposure["BTC"]) < 1e-8
    assert np.isclose(tg.w.sum(), tg.w[BTC]) and tg.w[BTC] > 0   # long BTC hedge = net dollar long


def test_projection_collapses_when_carry_is_collinear_with_beta():
    # shorts all high beta, longs all low beta: Σw = 0 and β'w = 0 leave (almost) nothing,
    # so the book shrinks to a few percent gross (README: limits of the projection mode)
    names = pd.Index(list("ABCDEF"))
    betas = pd.DataFrame({"BTC": [1.5, 1.4, 1.3, 0.6, 0.7, 0.8]}, index=names)
    w0 = pd.Series([-1 / 6] * 3 + [1 / 6] * 3, index=names)
    w, resid = neutralize(w0, betas, [0.0], max_weight=0.3)
    assert resid < 1e-10 and w.abs().sum() < 0.05


def test_neutralisation_without_hedge_leg(data):
    cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=())
    tg = targets(data, cfg)
    assert tg.status == "ok" and abs(tg.exposure["BTC"]) < 1e-8 and abs(tg.w.sum()) < 1e-12
    assert tg.w[BTC] == 0


def test_neutralize_two_names_collapses_to_flat():
    # Σw = 0 and β'w = 0 with two different betas have only the zero solution
    names = pd.Index(["S", "L"])
    betas = pd.DataFrame({"BTC": [1.5, 0.5]}, index=names)
    w, resid = neutralize(pd.Series([-0.5, 0.5], index=names), betas, [0.0], max_weight=0.5)
    assert resid < 1e-12 and np.allclose(w, 0)


def test_neutralize_reports_infeasible_target():
    # a nonzero exposure target that the weight cap cannot reach leaves a residual
    names = pd.Index(["S", "L", "M"])
    betas = pd.DataFrame({"BTC": [1.5, 0.5, 1.0]}, index=names)
    w, resid = neutralize(pd.Series([-0.3, 0.2, 0.1], index=names), betas, [0.5], max_weight=0.05)
    assert resid > 0.1 and w.abs().max() <= 0.05 + 1e-12


def test_neutralize_projection_matches_closed_form():
    rng = np.random.default_rng(1)
    names = pd.Index(list("abcdefgh"))
    betas = pd.DataFrame(rng.uniform(0.5, 1.5, (8, 2)), index=names, columns=["f1", "f2"])
    w0 = pd.Series([-0.1, -0.15, -0.1, -0.15, 0.1, 0.15, 0.1, 0.15], index=names)
    w, resid = neutralize(w0, betas, [0.0, 0.0], max_weight=1.0, keep_sign=False)
    A = np.vstack([np.ones(8), betas.T.to_numpy()])
    ref = w0.to_numpy() - A.T @ np.linalg.solve(A @ A.T, A @ w0.to_numpy())
    assert resid < 1e-12 and np.allclose(w.to_numpy(), ref)


def test_water_fill_caps_and_redistributes():
    w = water_fill(np.array([10.0, 1.0, 1.0]), 0.5, 0.2)
    assert np.isclose(w.sum(), 0.5) and w.max() <= 0.2 + 1e-12
    assert np.isclose(w[0], 0.2) and np.isclose(w[1], w[2])
    w = water_fill(np.array([1.0, 1.0]), 0.5, 0.2)         # cap binds for everyone
    assert np.allclose(w, 0.2)


def test_select_baskets_thresholds_and_flat():
    s = pd.Series({"a": 3e-3, "b": 2e-3, "c": 1e-3, "d": -1e-3})
    cfg = StrategyConfig(k=2)
    short, long = select_baskets(s, cfg)
    assert short == ["a", "b"] and long == ["d"]
    pos_only = pd.Series({"a": 3e-3, "b": 2e-3, "c": 1e-3})
    assert select_baskets(pos_only, cfg) == ([], [])          # no negative carry → flat
    rel = StrategyConfig(k=1, long_max_signal=None)
    assert select_baskets(pos_only, rel) == (["a"], ["c"])    # relative carry when allowed


def test_rank_buffer_keeps_held_names_inside_2k():
    s = pd.Series({f"n{i}": v for i, v in enumerate([9, 8, 7, 6, 5, 4, -4, -5, -6, -7, -8, -9])}) * 1e-4
    cfg = StrategyConfig(k=2, buffer_mult=2.0)
    # n3 (rank 4 of shorts) was held: kept, because 4 ≤ 2k; n5 (rank 6) was held: dropped
    short, long = select_baskets(s, cfg, prev_short=("n3", "n5"), prev_long=("n8",))
    assert short == ["n0", "n3"]
    assert long == ["n11", "n8"]
    assert select_baskets(s, StrategyConfig(k=2), ("n3", "n5"), ("n8",)) == (["n0", "n1"], ["n11", "n10"])


def test_flat_when_no_negative_funding(data):
    f = data.funding.copy()
    f["rate"] = f["rate"].abs()
    d2 = type(data)(close=data.close, funding=f, factors=data.factors, quote_volume=data.quote_volume)
    tg = targets(d2)
    assert tg.status == "flat:baskets" and tg.w.abs().sum() == 0


def test_vol_target_scales_without_breaking_neutrality(data):
    cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), target_vol=0.05)
    tg = targets(data, cfg)
    base = targets(data)
    assert tg.w.abs().sum() < base.w.abs().sum()
    assert abs(tg.w.sum()) < 1e-12 and abs(tg.exposure["BTC"]) < 1e-8


def test_hedge_instrument_is_never_a_basket_name(data):
    f = data.funding.copy()
    f.loc[f["symbol"] == BTC, "rate"] = -9e-4                  # BTC now has the lowest carry
    d2 = type(data)(close=data.close, funding=f, factors=data.factors, quote_volume=data.quote_volume)
    for mode in ("projection", "hedge"):
        cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), neutral_mode=mode)
        tg = targets(d2, cfg)
        assert BTC not in tg.short + tg.long and tg.w_raw[BTC] == 0
        assert tg.w.abs().max() <= cfg.max_weight + 1e-12


def _with_qv(data, qv):
    return type(data)(close=data.close, funding=data.funding, factors=data.factors, quote_volume=qv)


def test_liquidity_top_n_drops_least_liquid(data):
    qv = data.quote_volume.copy()
    qv["A"] = 1.0                                                # least liquid basket candidate
    qv["B"] = 10.0
    cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), liquidity_top_n=4)
    tg = targets(_with_qv(data, qv), cfg)
    assert set(tg.short) == {"C"} and set(tg.long) == {"D", "E", "F"}


def test_liquidity_uses_trailing_30d_median_only(data):
    t = data.close.index[-1]
    cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), min_median_quote_volume=100.0)
    qv = data.quote_volume.copy()
    qv.loc[qv.index > t - pd.Timedelta(days=10), "D"] = 1.0      # illiquid for 10 of 30 days
    assert "D" in targets(_with_qv(data, qv), cfg).long          # 30D median still high
    qv.loc[qv.index > t - pd.Timedelta(days=20), "D"] = 1.0      # illiquid for 20 of 30 days
    assert "D" not in targets(_with_qv(data, qv), cfg).long
    qv = data.quote_volume.copy()
    qv.loc[qv.index < t - pd.Timedelta(days=31), "D"] = 1.0      # illiquid only before the window
    assert "D" in targets(_with_qv(data, qv), cfg).long


def test_ridge_and_shrinkage_pull_betas():
    from crypto_dirty_carry.factors import estimate_betas
    rng = np.random.default_rng(2)
    F = pd.DataFrame({"BTC": rng.normal(0, 0.01, 500)})
    R = pd.DataFrame({"lo": 0.5 * F["BTC"] + rng.normal(0, 0.002, 500),
                      "hi": 1.5 * F["BTC"] + rng.normal(0, 0.002, 500),
                      "H": F["BTC"]})
    b0 = estimate_betas(R, F, 100)["BTC"]
    assert np.allclose(b0, [0.5, 1.5, 1.0], atol=0.03)
    br = estimate_betas(R, F, 100, ridge=1.0)["BTC"]             # λ = tr(X'X): slopes halve
    assert np.allclose(br, b0 / 2)
    bs = estimate_betas(R, F, 100, shrinkage=0.5, no_shrink=["H"])["BTC"]
    m = b0[["lo", "hi"]].mean()
    assert np.allclose(bs[["lo", "hi"]], 0.5 * b0[["lo", "hi"]] + 0.5 * m) and bs["H"] == b0["H"]


def test_config_validation():
    with pytest.raises(ValueError):
        StrategyConfig(k=3, quantile=0.2)
    with pytest.raises(ValueError):
        StrategyConfig(min_funding_events=1)
    with pytest.raises(ValueError):
        StrategyConfig(factors=(), neutralize=True)
