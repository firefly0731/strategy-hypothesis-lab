import numpy as np
import pandas as pd
import pytest

from crypto_cash_carry.data import Bundle, funding_to_grid, perp_to_spot
from crypto_cash_carry.engine import Market
from crypto_cash_carry.metrics import decomposition, performance, tbill_yearly, yearly
from crypto_cash_carry.strategies import GreedyRule, greedy_targets


def test_multiplier_contracts_map_to_spot():
    assert perp_to_spot("1000PEPEUSDT") == ("PEPEUSDT", 1000.0)
    assert perp_to_spot("1000000MOGUSDT") == ("MOGUSDT", 1e6)
    assert perp_to_spot("1MBABYDOGEUSDT") == ("BABYDOGEUSDT", 1e6)
    assert perp_to_spot("BTCUSDT") == ("BTCUSDT", 1.0)


def test_settlement_maps_to_first_close_at_or_after():
    idx = pd.date_range("2024-01-01 01:00", periods=10, freq="1h", tz="UTC")
    t = pd.Series(pd.to_datetime(["2024-01-01 00:00:00", "2024-01-01 08:00:00", "2024-01-01 07:59:00",
                                  "2024-01-02 00:00:00"], utc=True))
    g = funding_to_grid(t, pd.Series([1.0, 2.0, 3.0, 9.0]), idx)
    assert g[0] == 0.0          # 00:00 belongs to the bar (23:00, 00:00], which is before the grid
    assert g[idx.get_loc(pd.Timestamp("2024-01-01 08:00", tz="UTC"))] == 5.0   # 07:59 and 08:00 summed
    assert g.sum() == 5.0                                                      # 00:00 and 2024-01-02 are off-grid


def first_pick(tg):
    return min(t for t, v in tg.items() if v)


def bundle(sig, n_days=40, spot_qv=1e6, perp_qv=1e7):
    """S names, funding settled at 00/08/16 with a per-name constant rate."""
    sig = np.asarray(sig, float)
    idx = pd.date_range("2024-01-01 01:00", periods=24 * n_days, freq="1h", tz="UTC")
    N, S = len(idx), len(sig)
    f = np.zeros((N, S))
    f[idx.hour % 8 == 0] = sig / 3
    px = np.full((N, S), 100.0)
    mk = Market(index=idx, symbols=[f"S{i}" for i in range(S)], spot=px, perp=px.copy(), liq_high=px.copy(),
                funding=f, mmr=np.full(S, 0.01))
    return Bundle(market=mk, last_high=px.copy(), liq_proxy_bars=np.zeros(S, int), spot_qv=np.full((N, S), spot_qv, np.float32), perp_qv=np.full((N, S), perp_qv, np.float32),
                  n_settlements=np.zeros(S, int), neg_settlements=np.zeros(S, int), mult={})


def test_greedy_spec_picks_top_k_with_symbol_tie_break_after_history():
    b = bundle([0.001, 0.003, 0.003, 0.002, -0.001])
    tg, log = greedy_targets(b, GreedyRule(k=2))
    first = first_pick(tg)
    assert b.market.index[first] >= b.market.index[0] + pd.Timedelta(days=30) - pd.Timedelta(hours=1)
    assert tg[first] == ["S1", "S2"]                     # tie at 0.003 broken by name
    assert all(b.market.index[t].hour == 0 for t in tg)


def test_greedy_ignores_illiquid_names():
    b = bundle([0.001, 0.003])
    b.spot_qv[:, 1] = 10.0
    tg, _ = greedy_targets(b, GreedyRule(k=1))
    assert tg[first_pick(tg)] == ["S0"]


def test_improved_threshold_and_buffer():
    r = GreedyRule.improved()
    assert r.entry_threshold == pytest.approx(0.00285 / (0.75 * 7))
    b = bundle([0.0004, 0.0010, 0.0006], n_days=400)
    rule = GreedyRule(k=1, signal_days=3, min_history_days=30, entry_threshold=0.000543, keep_rank=2)
    tg, _ = greedy_targets(b, rule)
    assert tg[first_pick(tg)] == ["S1"]
    # S1's carry falls to rank 2 (still > 0): it is kept, S2 is not added since k = 1
    b.market.funding[24 * 100:, 1] = 0.0005 / 3 * (b.market.index[24 * 100:].hour % 8 == 0)
    tg, _ = greedy_targets(b, rule)
    later = [t for t in tg if t > 24 * 110]
    assert tg[later[0]] == ["S1"]
    # with no buffer the spec rule switches to S2
    tg2, _ = greedy_targets(b, GreedyRule(k=1, signal_days=3, min_history_days=30))
    assert tg2[later[0]] == ["S2"]


def test_below_threshold_names_are_not_entered():
    b = bundle([0.0004, 0.0005])
    tg, _ = greedy_targets(b, GreedyRule(k=2, signal_days=3, entry_threshold=0.000543, keep_rank=4))
    assert all(v == [] for v in tg.values())


def test_selection_uses_no_future_funding():
    b = bundle([0.001, 0.002, 0.003])
    tg, _ = greedy_targets(b, GreedyRule(k=1))
    T = sorted(tg)[3]
    b.market.funding[T + 1:, 0] = 1.0                    # huge future funding on S0
    tg2, _ = greedy_targets(b, GreedyRule(k=1))
    assert all(tg[t] == tg2[t] for t in tg if t <= T)


def test_metrics_and_tbill_accrual():
    idx = pd.date_range("2024-01-01 01:00", periods=24 * 366, freq="1h", tz="UTC")
    eq = pd.Series(np.linspace(1.0, 1.1, len(idx)), index=idx)
    bars = pd.DataFrame({"equity": eq, "funding": eq.diff().fillna(eq.iloc[0] - 1.0), "spot_pnl": 0.0, "perp_pnl": 0.0,
                         "fee": 0.0, "slippage": 0.0, "liq_loss": 0.0, "n_rebal": 0, "n_liq": 0,
                         "n_entries": 0, "n_exits": 0, "traded": 0.0})
    assert decomposition(bars)["total"] == pytest.approx(0.1)
    p = performance(bars)
    assert p["total_return"] == pytest.approx(0.1) and p["mdd"] == 0.0
    y = yearly(bars)
    rate = pd.Series(5.0, index=pd.date_range("2023-12-01", "2025-02-01", freq="D", tz="UTC"))
    tb = tbill_yearly(rate, y)
    assert tb.loc[2024, "tbill_avg_pct"] == pytest.approx(5.0)
    assert tb.loc[2024, "tbill_return"] == pytest.approx((1 + 0.05 / 365) ** 366 - 1)
