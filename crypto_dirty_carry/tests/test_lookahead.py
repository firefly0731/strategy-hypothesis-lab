"""Perturbation tests: changing anything after t must not change the decision at t."""
import numpy as np
import pandas as pd

from crypto_dirty_carry.backtest import compute_schedule, run_backtest
from crypto_dirty_carry.config import StrategyConfig
from crypto_dirty_carry.data import MarketData

from .conftest import BTC, make_data

CFG = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), rebalance_every="8h")


def perturb_after(d: MarketData, T: pd.Timestamp, seed=7) -> MarketData:
    rng = np.random.default_rng(seed)
    close = d.close.copy()
    after = close.index > T
    close.loc[after] = close.loc[after] * np.exp(rng.normal(0, 0.2, close.loc[after].shape))
    factors = d.factors.copy()
    factors.loc[after] = rng.normal(0, 0.1, factors.loc[after].shape)
    qv = d.quote_volume.copy()
    qv.loc[after] = 0.0
    f = d.funding.copy()
    late = f["time"] > T
    f.loc[late, "rate"] = -f.loc[late, "rate"] * 50              # flip and blow up future funding
    return MarketData(close=close, funding=f, factors=factors, quote_volume=qv)


def test_decisions_up_to_T_ignore_the_future():
    d = make_data(n_days=120)
    T = d.close.index[len(d.close) * 4 // 5]
    a = compute_schedule(d, CFG)
    b = compute_schedule(perturb_after(d, T), CFG)
    checked = 0
    for ta, tb in zip(a, b):
        assert ta.t == tb.t
        if ta.t > T:
            continue
        checked += 1
        pd.testing.assert_series_equal(ta.w, tb.w)
        pd.testing.assert_series_equal(ta.w_raw, tb.w_raw)
        pd.testing.assert_series_equal(ta.signal, tb.signal)
        pd.testing.assert_frame_equal(ta.betas, tb.betas)
    assert checked > 50
    # and the perturbation is real: later decisions do change
    assert any(not ta.w.equals(tb.w) for ta, tb in zip(a, b) if ta.t > T)


def test_buffered_schedule_ignores_the_future():
    from dataclasses import replace
    cfg = replace(CFG, buffer_mult=2.0, funding_lookback="7D", rebalance_every="1D")
    d = make_data(n_days=120)
    T = d.close.index[len(d.close) * 4 // 5]
    a, b = compute_schedule(d, cfg), compute_schedule(perturb_after(d, T), cfg)
    n = 0
    for ta, tb in zip(a, b):
        if ta.t <= T:
            n += 1
            pd.testing.assert_series_equal(ta.w, tb.w)
    assert n > 10


def test_equity_up_to_T_ignores_the_future():
    d = make_data(n_days=120)
    T = d.close.index[len(d.close) * 4 // 5]
    ra = run_backtest(d, CFG)
    rb = run_backtest(perturb_after(d, T), CFG)
    pd.testing.assert_frame_equal(ra.bars.loc[:T], rb.bars.loc[:T])


def test_snapshot_has_no_rows_after_t():
    d = make_data(n_days=120)
    t = d.close.index[500]
    s = d.snapshot(t, CFG.lookback, CFG.funding_history)
    assert s.close.index.max() == t and s.factors.index.max() == t
    assert (s.funding["time"] <= t).all()


def test_settlement_at_t_is_used_but_later_one_is_not():
    d = make_data(n_days=120)
    t = pd.Timestamp("2024-04-10 08:00", tz="UTC")
    base = compute_schedule(d, CFG)
    tg = next(x for x in base if x.t == t)
    for when, should_change in ((t, True), (t + pd.Timedelta(hours=8), False)):
        f = d.funding.copy()
        f.loc[(f["time"] == when) & (f["symbol"] == "D"), "rate"] = 0.05
        d2 = MarketData(close=d.close, funding=f, factors=d.factors, quote_volume=d.quote_volume)
        tg2 = next(x for x in compute_schedule(d2, CFG) if x.t == t)
        assert (tg2.signal["D"] != tg.signal["D"]) == should_change
