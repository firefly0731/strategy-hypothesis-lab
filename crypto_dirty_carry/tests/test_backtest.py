import numpy as np
import pandas as pd

from crypto_dirty_carry.backtest import (compute_schedule, performance, realized_betas,
                                         rebalance_times, run_backtest, simulate)
from crypto_dirty_carry.config import CostConfig, StrategyConfig

from .conftest import BTC, make_data

CFG = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,))


def test_attribution_adds_up_to_equity_change():
    r = run_backtest(make_data(), CFG)
    a = r.attribution
    assert np.isclose(a["total"], a["equity_change"], rtol=0, atol=1e-12)
    assert np.isclose(a["price_pnl"], a["price_pnl_baskets"] + a["price_pnl_hedge"])
    assert a["trading_cost"] < 0


def test_execution_lag_and_dollar_neutral_orders():
    d = make_data()
    sched = compute_schedule(d, CFG)
    r = run_backtest(d, CFG, schedule=sched)
    first = next(tg for tg in sched if not tg.status.startswith("flat"))
    exec_t = d.close.index[d.close.index.get_loc(first.t) + CFG.exec_lag_bars]
    assert r.orders.index[r.orders.abs().sum(axis=1) > 0][0] == exec_t
    assert np.allclose(r.orders.sum(axis=1), 0, atol=1e-12)
    assert (r.orders.abs().sum(axis=1) <= CFG.gross_cap + 1e-12).all()


def test_cost_and_turnover_definitions():
    d = make_data(n_days=5)
    t = d.close.index[10]
    w = pd.Series(0.0, index=d.symbols)
    w["A"], w["D"] = -0.4, 0.4
    costs = CostConfig(fee_bps=4, slippage_bps=1)
    bars, _ = simulate(d, pd.DataFrame([w], index=[t]), costs)
    assert np.isclose(bars.loc[t, "turnover"], 0.5 * 0.8)        # 0.5 Σ|Δw|
    assert np.isclose(bars.loc[t, "cost"], 0.8 * 1.0 * 5e-4)     # Σ|Δw| × equity × 5bp


def test_drifted_weights_are_the_turnover_baseline():
    d = make_data(n_days=5)
    t1, t2 = d.close.index[10], d.close.index[20]
    w = pd.Series(0.0, index=d.symbols)
    w["A"], w["D"] = -0.4, 0.4
    bars, held = simulate(d, pd.DataFrame([w, w], index=[t1, t2]), CostConfig(0, 0))
    drift = held.iloc[19]
    pre = drift * bars["equity"].iloc[19]
    # weights just before the t2 trade = drifted notional / equity after the t2 bar move
    move = d.close.iloc[20] / d.close.iloc[19]
    w_pre = (pre * move) / (bars["equity"].iloc[20])
    assert np.isclose(bars.loc[t2, "turnover"], 0.5 * (w - w_pre).abs().sum())


def test_hedged_book_has_lower_realised_beta_than_raw():
    d = make_data(n_days=120, seed=3)
    sched = compute_schedule(d, CFG)
    hedged = run_backtest(d, CFG, "hedged", schedule=sched).betas.loc["BTC", "beta"]
    raw = run_backtest(d, CFG, "raw", schedule=sched).betas.loc["BTC", "beta"]
    assert raw < -0.1 and abs(hedged) < 0.05


def test_missing_price_closes_position():
    d = make_data(n_days=5)
    close = d.close.copy()
    close.loc[close.index[30]:, "A"] = np.nan                     # delisted after bar 29
    d2 = type(d)(close=close, funding=d.funding[d.funding["symbol"] != "A"], factors=d.factors,
                 quote_volume=d.quote_volume)
    w = pd.Series(0.0, index=d.symbols)
    w["A"], w["D"] = -0.4, 0.4
    bars, held = simulate(d2, pd.DataFrame([w], index=[d.close.index[10]]), CostConfig(4, 1))
    assert held["A"].iloc[30] == 0 and held["A"].iloc[29] != 0
    assert bars["cost"].iloc[30] > 0


def test_outage_is_held_and_booked_when_price_returns():
    d = make_data(n_days=5)
    close = d.close.copy()
    p29 = close["A"].iloc[29]
    close.iloc[30:33, close.columns.get_loc("A")] = np.nan       # 3-bar outage, A trades again
    d2 = type(d)(close=close, funding=d.funding, factors=d.factors, quote_volume=d.quote_volume)
    w = pd.Series(0.0, index=d.symbols)
    w["A"], w["D"] = -0.4, 0.4
    bars, held = simulate(d2, pd.DataFrame([w], index=[d.close.index[10]]), CostConfig(4, 1))
    assert (held["A"].iloc[30:34] != 0).all() and bars["cost"].iloc[30:34].sum() == 0
    n29 = held["A"].iloc[29] * bars["equity"].iloc[29]
    pnl_A = n29 * (close["A"].iloc[33] / p29 - 1)                # whole gap booked at bar 33
    pnl_D = (held["D"].iloc[32] * bars["equity"].iloc[32]) * (close["D"].iloc[33] / close["D"].iloc[32] - 1)
    assert np.isclose(bars["price_pnl"].iloc[33], pnl_A + pnl_D)


def test_no_price_at_execution_keeps_that_position():
    d = make_data(n_days=5)
    close = d.close.copy()
    close.iloc[20, close.columns.get_loc("A")] = np.nan
    d2 = type(d)(close=close, funding=d.funding, factors=d.factors, quote_volume=d.quote_volume)
    w1 = pd.Series(0.0, index=d.symbols); w1["A"], w1["D"] = -0.4, 0.4
    w2 = pd.Series(0.0, index=d.symbols); w2["B"], w2["E"] = -0.4, 0.4
    bars, held = simulate(d2, pd.DataFrame([w1, w2], index=d.close.index[[10, 20]]), CostConfig(0, 0))
    assert held["A"].iloc[20] != 0 and held["B"].iloc[20] == -0.4 and np.isclose(held["E"].iloc[20], 0.4)
    assert np.isclose(bars["untraded"].iloc[20], abs(held["A"].iloc[20]))   # A's target was 0


def test_post_trade_weights_equal_target():
    d = make_data(n_days=5)
    w = pd.Series(0.0, index=d.symbols); w["A"], w["D"] = -0.4, 0.4
    t = d.close.index[10]
    _, held = simulate(d, pd.DataFrame([w], index=[t]), CostConfig(4, 1))
    assert np.allclose(held.loc[t, ["A", "D"]], [-0.4, 0.4], atol=1e-15)


def test_lag_zero_executes_at_decision_time():
    d = make_data()
    cfg = StrategyConfig(k=3, max_weight=0.3, hedge_instruments=(BTC,), exec_lag_bars=0)
    r = run_backtest(d, cfg)
    first = next(tg for tg in r.schedule if not tg.status.startswith("flat"))
    assert r.orders.index[r.orders.abs().sum(axis=1) > 0][0] == first.t


def test_offset_must_be_a_multiple_of_the_bar():
    import pytest
    with pytest.raises(ValueError):
        compute_schedule(make_data(n_days=5), StrategyConfig(rebalance_offset="5min"))


def test_ruin_stops_trading():
    d = make_data(n_days=5)
    close = d.close.copy()
    close.iloc[15:, close.columns.get_loc("A")] *= 5.0              # +400% against a 0.4 short
    d2 = type(d)(close=close, funding=d.funding, factors=d.factors, quote_volume=d.quote_volume)
    w = pd.Series(0.0, index=d.symbols); w["A"] = -1.0
    bars, held = simulate(d2, pd.DataFrame([w, w], index=d.close.index[[10, 20]]), CostConfig(0, 0))
    assert bars["equity"].iloc[15] <= 0 and (held.iloc[15:] == 0).all().all()


def test_performance_known_series():
    idx = pd.date_range("2024-01-01", periods=366, freq="1D", tz="UTC")
    eq = pd.Series(1.0005 ** np.arange(366), index=idx)
    m = performance(eq, 365)
    assert np.isclose(m["cagr"], 1.0005 ** 365 - 1) and m["mdd"] == 0
    eq2 = pd.Series([1.0, 1.2, 0.9, 1.1], index=idx[:4])
    m2 = performance(eq2, 365)
    r = np.array([0.2, -0.25, 1.1 / 0.9 - 1])
    assert np.isclose(m2["mdd"], 0.9 / 1.2 - 1)
    assert np.isclose(m2["sharpe"], r.mean() / r.std(ddof=1) * np.sqrt(365))
    assert np.isclose(m2["sortino"], r.mean() * 365 / (np.sqrt((np.minimum(r, 0) ** 2).mean()) * np.sqrt(365)))
    assert np.isclose(m2["calmar"], m2["cagr"] / (1 - 0.9 / 1.2))


def test_daily_sharpe_keeps_the_first_partial_day():
    idx = pd.date_range("2024-01-01 01:00", periods=72, freq="1h", tz="UTC")
    eq = pd.Series(1.0, index=idx)
    eq.iloc[5:] = 1.1                                              # +10% on day 1
    eq.iloc[30:] = 1.0                                             # back on day 2
    eq.iloc[60:] = 1.05
    m = performance(eq, 24 * 365)
    d = np.array([0.1, 1.0 / 1.1 - 1, 0.05])
    assert np.isclose(m["sharpe_daily"], d.mean() / d.std(ddof=1) * np.sqrt(365))


def test_realized_beta_recovers_known_beta():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=24 * 200, freq="1h", tz="UTC")
    f = pd.DataFrame({"BTC": rng.normal(0, 0.005, len(idx))}, index=idx)
    r = pd.Series(0.3 * f["BTC"] + rng.normal(0, 0.001, len(idx)), index=idx)
    b = realized_betas(r, f)
    assert abs(b.loc["BTC", "beta"] - 0.3) < 0.03


def test_rebalance_grid_with_offset():
    idx = pd.date_range("2024-01-01 01:00", periods=48, freq="1h", tz="UTC")
    t = rebalance_times(idx, "8h", "1h")
    assert list(t.hour) == [1, 9, 17, 1, 9, 17]
