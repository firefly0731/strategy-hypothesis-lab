"""Settlement-aware execution and loss limits."""
from dataclasses import replace

import numpy as np
import pandas as pd

from crypto_dirty_carry.backtest import run_backtest
from crypto_dirty_carry.config import CostConfig, StrategyConfig
from crypto_dirty_carry.data import MarketData
from crypto_dirty_carry.risk import RiskConfig, run_managed

from .conftest import BTC, make_data

CFG = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), rebalance_every="1D", buffer_mult=2.0,
                     short_min_signal=None, long_max_signal=None)


def test_all_off_matches_plain_engine():
    d = make_data(n_days=100)
    a = run_backtest(d, CFG)
    b = run_managed(d, CFG, RiskConfig.off(timing=False))
    cols = ["equity", "price_pnl", "funding_pnl", "cost", "turnover", "gross", "net"]
    pd.testing.assert_frame_equal(a.bars[cols], b.bars[cols])


def test_timing_enters_before_and_exits_after_settlement():
    d = make_data(n_days=100)
    r = run_managed(d, CFG, RiskConfig.off(timing=True))
    trades = r.bars.index[r.bars["turnover"] > 0]
    assert set(trades.hour) <= {23, 0}                           # increases 23:00, reductions 00:00
    first_dec = r.schedule[0].t
    assert first_dec.hour == 22                                  # T - entry_before(1) - lag(1)
    w = r.weights
    t_in = pd.Timestamp(first_dec.date(), tz="UTC") + pd.Timedelta(hours=23)
    # entered at 23:00, so held during the bar that ends at the 00:00 settlement
    assert (w.loc[t_in].abs() > 0).any()
    assert r.bars.loc[t_in + pd.Timedelta(hours=1), "funding_pnl"] != 0


def test_exit_happens_after_the_settlement_is_paid():
    idx = pd.date_range("2024-01-01 01:00", periods=24 * 50, freq="1h", tz="UTC")
    close = pd.DataFrame({"A": 100.0, "B": 100.0, "C": 100.0}, index=idx)
    t = pd.date_range(pd.Timestamp("2024-01-01 08:00", tz="UTC"), idx[-1], freq="8h")
    # A has high carry until day 40, then collapses; B and C fixed
    rate_a = np.where(t < pd.Timestamp("2024-02-10", tz="UTC"), 5e-4, -5e-4)
    f = pd.concat([pd.DataFrame({"time": t, "symbol": "A", "rate": rate_a}),
                   pd.DataFrame({"time": t, "symbol": "B", "rate": 1e-4}),
                   pd.DataFrame({"time": t, "symbol": "C", "rate": -3e-4})])
    d = MarketData(close=close, funding=f, factors=pd.DataFrame(index=idx))
    cfg = StrategyConfig(k=1, factors=(), neutralize=False, hedge_instruments=(), rebalance_every="1D",
                         short_min_signal=None, long_max_signal=None, min_history="10D", vol_window="10D",
                         beta_window="10D", liquidity_window="10D", costs=CostConfig(0, 0))
    r = run_managed(d, cfg, RiskConfig.off(timing=True))
    w = r.weights["A"]
    exit_t = w.index[(w.shift(1) < 0) & (w == 0)][0]
    assert exit_t.hour == 0                                      # left at 00:00, after settling
    assert r.bars.loc[exit_t, "funding_pnl"] != 0                # the 00:00 settlement was received


def test_stop_loss_closes_and_cools_down():
    d = make_data(n_days=100)
    base = run_managed(d, CFG, RiskConfig.off(timing=True))
    tg = base.schedule[-30]
    short = tg.w[list(tg.short)].idxmin()                       # the largest held short
    t0 = base.schedule[-30].t + pd.Timedelta(hours=5)
    close = d.close.copy()
    close.loc[close.index > t0, short] *= 1.5                    # +50% squeeze on a held short
    d2 = MarketData(close=close, funding=d.funding, factors=d.factors, quote_volume=d.quote_volume)
    risk = RiskConfig(timing=True, stop_loss=0.02, recap_mult=None, dd_reduce=None, dd_flat=None)
    r = run_managed(d2, CFG, risk)
    j = r.weights.index.get_loc(r.weights.index[r.weights.index > t0][0])
    assert r.bars["stops"].iloc[j] >= 1                          # detected on the jump bar
    assert r.weights[short].iloc[j + 1] == 0                     # closed on the next bar
    later = [tg for tg in r.schedule if r.weights.index[j] < tg.t < r.weights.index[j] + pd.Timedelta(days=7)]
    assert later and all(short not in tg.short + tg.long for tg in later)   # cooldown


def test_recap_cuts_drifted_weight():
    d = make_data(n_days=100)
    base = run_managed(d, CFG, RiskConfig.off(timing=True))
    tg = base.schedule[-30]
    short = tg.w[list(tg.short)].idxmin()                       # the largest held short
    t0 = base.schedule[-30].t + pd.Timedelta(hours=5)
    close = d.close.copy()
    close.loc[close.index > t0, short] *= 2.0
    d2 = MarketData(close=close, funding=d.funding, factors=d.factors, quote_volume=d.quote_volume)
    risk = RiskConfig(timing=True, stop_loss=None, recap_mult=1.5, dd_reduce=None, dd_flat=None)
    r = run_managed(d2, CFG, risk)
    w = r.weights[short]
    j = w.index.get_loc(w.index[w.index > t0][0])
    assert abs(w.iloc[j]) > 1.5 * CFG.max_weight                # drifted past the limit
    assert r.bars["recaps"].iloc[j] >= 1
    assert np.isclose(abs(w.iloc[j + 1]), CFG.max_weight, rtol=1e-6)


def test_drawdown_floor_flattens_and_pauses():
    d = make_data(n_days=100)
    base = run_managed(d, CFG, RiskConfig.off(timing=True))
    t0 = base.schedule[-30].t + pd.Timedelta(hours=5)
    close = d.close.copy()
    for s in base.schedule[-30].short:
        close.loc[close.index > t0, s] *= 4.0                    # every short squeezed
    d2 = MarketData(close=close, funding=d.funding, factors=d.factors, quote_volume=d.quote_volume)
    r = run_managed(d2, CFG, RiskConfig(timing=True, stop_loss=None, recap_mult=None))
    j = int(np.argmax(r.bars["flatten"].to_numpy() > 0))
    assert r.bars["flatten"].iloc[j] == 1
    assert r.weights.iloc[j + 1].abs().sum() == 0
    pause = r.bars["paused"].iloc[j + 1: j + 1 + 24 * 6]
    assert (pause == 1).all() and (r.weights.iloc[j + 1: j + 1 + 24 * 6].abs().sum(axis=1) == 0).all()


def test_managed_run_ignores_the_future():
    from .test_lookahead import perturb_after
    d = make_data(n_days=120)
    T = d.close.index[len(d.close) * 4 // 5]
    risk = RiskConfig()
    a = run_managed(d, CFG, risk)
    b = run_managed(perturb_after(d, T), CFG, risk)
    pd.testing.assert_frame_equal(a.bars.loc[:T], b.bars.loc[:T])
