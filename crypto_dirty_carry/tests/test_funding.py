"""Funding sign convention, settlement-to-bar mapping and the carry signal."""
import numpy as np
import pandas as pd

from crypto_dirty_carry.backtest import funding_matrices, simulate
from crypto_dirty_carry.config import CostConfig
from crypto_dirty_carry.data import MarketData
from crypto_dirty_carry.factors import funding_carry

T0 = pd.Timestamp("2024-03-01 01:00", tz="UTC")
FREE = CostConfig(fee_bps=0, slippage_bps=0)


def flat_market(funding_rows, n=48, bar="1h", prices=None):
    idx = pd.date_range(T0, periods=n, freq=bar)
    close = pd.DataFrame({"A": 100.0, "B": 50.0}, index=idx) if prices is None else prices.set_axis(idx)
    funding = pd.DataFrame(funding_rows, columns=["time", "symbol", "rate"])
    funding["time"] = pd.to_datetime(funding["time"], utc=True)
    factors = pd.DataFrame(index=idx)
    return MarketData(close=close, funding=funding, factors=factors)


def test_sign_short_collects_positive_long_pays_positive():
    d = flat_market([("2024-03-01 08:00", "A", 1e-4), ("2024-03-01 08:00", "B", 3e-4)])
    orders = pd.DataFrame({"A": [-0.5], "B": [0.5]}, index=[T0 + pd.Timedelta(hours=2)])
    bars, _ = simulate(d, orders, FREE)
    s = bars.loc["2024-03-01 08:00", "funding_pnl"]
    assert np.isclose(s, 0.5 * 1e-4 - 0.5 * 3e-4)               # short A +0.5bp, long B -1.5bp
    orders = pd.DataFrame({"A": [-0.5], "B": [0.0]}, index=orders.index)
    bars, _ = simulate(d, orders, FREE)
    assert np.isclose(bars["funding_pnl"].sum(), 0.5 * 1e-4)    # short receives positive funding


def test_negative_rate_long_collects():
    d = flat_market([("2024-03-01 08:00", "B", -2e-4)])
    orders = pd.DataFrame({"A": [0.0], "B": [0.5]}, index=[T0])
    bars, _ = simulate(d, orders, FREE)
    assert np.isclose(bars["funding_pnl"].sum(), 0.5 * 2e-4)


def test_position_opened_at_settlement_does_not_get_it():
    s = "2024-03-01 08:00"
    d = flat_market([(s, "A", 1e-4), ("2024-03-01 16:00", "A", 1e-4)])
    orders = pd.DataFrame({"A": [-0.5], "B": [0.0]}, index=[pd.Timestamp(s, tz="UTC")])
    bars, _ = simulate(d, orders, FREE)
    assert bars.loc[s, "funding_pnl"] == 0.0                    # executed after the 08:00 settlement
    assert np.isclose(bars.loc["2024-03-01 16:00", "funding_pnl"], 0.5e-4)
    # closing exactly at a settlement still receives it (held through the bar ending there)
    orders = pd.DataFrame({"A": [-0.5, 0.0], "B": [0.0, 0.0]},
                          index=[T0, pd.Timestamp(s, tz="UTC")])
    bars, _ = simulate(d, orders, FREE)
    assert np.isclose(bars["funding_pnl"].sum(), 0.5e-4)


def test_settlement_mapping_hourly_and_inside_bar():
    rows = [("2024-03-01 08:00", "A", 1e-4), ("2024-03-01 06:00", "B", 2e-4)]
    d1 = flat_market(rows)                                       # 1h bars: both on bar closes
    fe, fi = funding_matrices(d1)
    j8 = d1.close.index.get_loc(pd.Timestamp("2024-03-01 08:00", tz="UTC"))
    assert fe[j8, 0] == 1e-4 and fi.sum() == 0
    idx4 = pd.date_range("2024-03-01 04:00", periods=12, freq="4h", tz="UTC")
    d4 = MarketData(close=pd.DataFrame({"A": 100.0, "B": 50.0}, index=idx4),
                    funding=d1.funding, factors=pd.DataFrame(index=idx4))
    fe, fi = funding_matrices(d4)
    j = idx4.get_loc(pd.Timestamp("2024-03-01 08:00", tz="UTC"))
    assert fe[j, 0] == 1e-4 and fi[j, 1] == 2e-4                # 06:00 falls inside (04:00, 08:00]


def test_inside_bar_settlement_uses_bar_start_notional():
    idx4 = pd.date_range("2024-03-01 04:00", periods=6, freq="4h", tz="UTC")
    close = pd.DataFrame({"A": [100.0, 200.0, 200, 200, 200, 200], "B": 50.0}, index=idx4)
    f = pd.DataFrame({"time": [pd.Timestamp("2024-03-01 06:00", tz="UTC")], "symbol": ["A"], "rate": [1e-4]})
    d = MarketData(close=close, funding=f, factors=pd.DataFrame(index=idx4))
    orders = pd.DataFrame({"A": [-0.5], "B": [0.0]}, index=[idx4[0]])
    bars, _ = simulate(d, orders, FREE)
    assert np.isclose(bars["funding_pnl"].iloc[1], 0.5 * 1e-4)   # notional at 04:00, not at 08:00
    assert np.isclose(bars["price_pnl"].iloc[1], -0.5)           # short loses 100% of 0.5


def test_carry_is_per_day_for_mixed_intervals():
    t = pd.Timestamp("2024-03-10", tz="UTC")
    s8 = pd.date_range(t - pd.Timedelta(days=5), t, freq="8h")
    s1 = pd.date_range(t - pd.Timedelta(days=5), t, freq="1h")
    f = pd.concat([pd.DataFrame({"time": s8, "symbol": "X", "rate": 3e-4}),
                   pd.DataFrame({"time": s1, "symbol": "Y", "rate": 3e-4 / 8})]).sort_values("time")
    c = funding_carry(f, ["X", "Y"], t, pd.Timedelta(days=3), min_events=3)
    assert np.allclose(c, 9e-4)                                  # 3 × 3bp per day for both


def test_carry_uses_only_settlements_up_to_t():
    t = pd.Timestamp("2024-03-10", tz="UTC")
    s = pd.date_range(t - pd.Timedelta(days=4), t + pd.Timedelta(days=2), freq="8h")
    rate = np.where(s <= t, 1e-4, 9.0)
    f = pd.DataFrame({"time": s, "symbol": "X", "rate": rate})
    c = funding_carry(f, ["X"], t, pd.Timedelta(days=3), min_events=3)
    assert np.isclose(c["X"], 3e-4)


def test_first_ever_settlement_excluded_from_numerator():
    t = pd.Timestamp("2024-03-10", tz="UTC")
    s = pd.date_range(t - pd.Timedelta(hours=16), t, freq="8h")   # 3 settlements, no earlier one
    f = pd.DataFrame({"time": s, "symbol": "X", "rate": [5.0, 1e-4, 1e-4]})
    c = funding_carry(f, ["X"], t, pd.Timedelta(days=3), min_events=3)
    assert np.isclose(c["X"], 2e-4 / (16 / 24))
